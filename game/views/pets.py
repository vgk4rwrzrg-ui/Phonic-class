"""Pet egg shop: buy, hatch (async), collect, companion, media serving."""

import json
import logging
import os

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..context import get_kid
from ..jsonapi import (json_body, json_fail, json_ok, read_nonce, require_kid,
                       require_kid_feature, store_nonce)
from ..models import Kid, Pet
from .. import pet_services, tts
from ..pet_services import HATCH_STALE_SECONDS, pet_dict

logger = logging.getLogger(__name__)


def pet_area(request):
    """Kid-facing pet page: buy eggs, hatch, collect, pick a companion."""
    kid = get_kid(request)
    if not kid:
        return redirect("picker")
    cr = kid.classroom
    if not cr.pets_enabled:
        return redirect("game")
    return render(request, "game/pets.html", {
        "kid": kid,
        "classroom": cr,
        "spendable": kid.spendable,
        "egg_cost": cr.egg_cost,
        "pets": kid.pets.all(),
    })


def _buy_locked(kid, egg_cost):
    """Atomically charge for and create one egg; returns (pet, error_resp)."""
    with transaction.atomic():
        locked = Kid.objects.select_for_update().get(pk=kid.pk)
        if locked.spendable < egg_cost:
            return None, JsonResponse(
                {"ok": False, "error": "not_enough_points",
                 "spendable": locked.spendable,
                 "egg_cost": egg_cost}, status=400)
        locked.points_spent += egg_cost
        locked.save()
        return pet_services.create_egg(locked), None


@require_POST
@require_kid_feature("pets_enabled", "pets disabled")
def api_pet_buy(request, kid):
    """Buy one egg.  Deducts egg_cost from spendable points.  Idempotent via nonce."""
    cr = kid.classroom
    nonce, seen_pet_id = read_nonce(request, "egg", kid, json_body(request))
    if seen_pet_id:
        pet = Pet.objects.filter(pk=seen_pet_id, kid=kid).first()
        return json_ok(duplicate=True, pet=pet_dict(pet) if pet else None,
                       spendable=kid.spendable)

    pet, error = _buy_locked(kid, cr.egg_cost)
    if error:
        return error
    store_nonce(request, "egg", kid, nonce, value=pet.pk)
    return json_ok(pet=pet_dict(pet), spendable=pet.kid.spendable)


def _kid_pet_or_404(kid, pet_id, **filters):
    pet = Pet.objects.filter(pk=pet_id, kid=kid, **filters).first()
    if not pet:
        return None, json_fail("not found", status=404)
    return pet, None


@require_POST
@require_kid
def api_pet_hatch(request, kid, pet_id):
    """Start async hatching via Celery (or thread fallback)."""
    pet, error = _kid_pet_or_404(kid, pet_id)
    if error:
        return error
    if pet.hatched:
        return json_ok(status="complete", pet=pet_dict(pet))

    # Already hatching? Return current status -- unless it is stuck.
    # A worker crash can strand a pet in an in-flight status forever; if the
    # status has not advanced in HATCH_STALE_SECONDS, restart the hatch.
    if pet.hatch_status not in ("unhatched", "failed"):
        if not pet_services.hatch_is_stale(pet):
            return json_ok(status=pet.hatch_status, pet_id=pet.pk)
        age = pet.hatch_age_seconds()
        logger.warning(
            f"Pet {pet.pk} hatch stuck in '{pet.hatch_status}' "
            f"(age={'unknown' if age is None else int(age)}s) - restarting"
        )

    # Mark as started BEFORE dispatching, so the task's own status writes
    # (which may land immediately, e.g. eager mode) are never clobbered.
    pet.set_hatch_status("cracking")
    pet_services.dispatch_hatch(pet)
    return json_ok(status="cracking", pet_id=pet.pk)


def _effective_hatch_status(pet):
    """Current hatch status, downgrading a stuck in-flight hatch to failed."""
    status = pet.hatch_status
    if (not pet.hatched and status in Pet.HATCHING_STATUSES
            and pet_services.hatch_is_stale(pet)):
        logger.warning(
            f"Pet {pet.pk} hatch poll: stuck in '{status}', reporting failed")
        pet.set_hatch_status("failed")
        status = "failed"
    return status


@require_kid
def api_pet_hatch_status(request, kid, pet_id):
    """Poll the hatch progress."""
    pet, error = _kid_pet_or_404(kid, pet_id)
    if error:
        return error
    status = _effective_hatch_status(pet)
    response = {"ok": True, "status": status, "hatched": pet.hatched}
    if pet.hatched:
        response["pet"] = pet_dict(pet)
    elif status == "failed":
        response["error"] = "The egg is not ready - try again soon!"
    return JsonResponse(response)


@require_POST
@require_kid
def api_pet_companion(request, kid, pet_id):
    """Choose which hatched pet comes along on the spelling quest."""
    pet, error = _kid_pet_or_404(kid, pet_id, hatched=True)
    if error:
        return error
    kid.pets.update(is_companion=False)
    pet.is_companion = True
    pet.save()
    return json_ok(pet=pet_dict(pet))


# ---- Pet media (image + creature voice), owner or their teacher only --------

def _pet_media_guard(request, pet_id, need_image=False):
    """Fetch a pet for media serving; returns (pet, error_response)."""
    pet = Pet.objects.filter(pk=pet_id).select_related("kid__classroom").first()
    if not pet or (need_image and not (pet.hatched and pet.image_path)):
        return None, JsonResponse({"error": "not found"}, status=404)
    if not pet_services.pet_media_allowed(request, get_kid(request), pet):
        return None, JsonResponse({"error": "forbidden"}, status=403)
    return pet, None


def pet_image(request, pet_id):
    """Serve a pet image (owner or their teacher only)."""
    pet, error = _pet_media_guard(request, pet_id, need_image=True)
    if error:
        return error
    path = os.path.join(settings.MEDIA_ROOT, pet.image_path)
    if not os.path.exists(path):
        return JsonResponse({"error": "not found"}, status=404)
    return FileResponse(open(path, "rb"), content_type="image/png")


def _creature_phrase_path(pet, idx):
    """Cached creature-phrase mp3 path, synthesizing on first use (may raise)."""
    rel = f"petvoices/pet_{pet.pk}_{idx}.mp3"
    path = os.path.join(settings.MEDIA_ROOT, rel)
    if not os.path.exists(path):
        phrases = json.loads(pet.phrases_json)
        voice = json.loads(pet.voice_json)
        audio_bytes = tts.synthesize_creature(
            phrases[idx], voice["language_code"], voice["voice_name"],
            voice["pitch"], voice["rate"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(audio_bytes)
    return path


def pet_sound(request, pet_id, idx):
    """Serve (generating+caching on first use) creature phrase #idx (0-4)."""
    pet, error = _pet_media_guard(request, pet_id)
    if error:
        return error
    idx = int(idx)
    if not 0 <= idx < len(json.loads(pet.phrases_json)):
        return JsonResponse({"error": "not found"}, status=404)
    try:
        path = _creature_phrase_path(pet, idx)
    except Exception:
        logger.exception("Pet voice synthesis failed (pet %s)", pet.pk)
        return JsonResponse({"error": "tts unavailable"}, status=404)
    return FileResponse(open(path, "rb"), content_type="audio/mpeg")
