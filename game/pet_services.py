"""Pet egg shop services: image generation, storage, and hatch dispatch.

The hatch pipeline itself lives in game.tasks; this module owns the pieces it
calls (DeepAI generation, blank-image detection, image normalization) plus the
buy/serialize helpers used by the AJAX views.

NOTE: game.views re-exports deepai_generate/looks_blank/save_pet_image under
their historical underscore names, and game.tasks resolves them through the
views module at call time, so tests can patch "game.views._deepai_generate".
"""

import json
import logging
import os
import threading

from django.conf import settings

from . import pets as petgen
from .models import Pet

logger = logging.getLogger(__name__)

HATCH_STALE_SECONDS = 180  # in-flight hatch older than this is considered stuck


def pet_dict(p):
    """Standard JSON serialization of a pet for the AJAX endpoints."""
    return {
        "id": p.pk,
        "name": p.name,
        "hatched": p.hatched,
        "is_companion": p.is_companion,
        "tier": p.tier,
        "traits": json.loads(p.traits_json),
        "phrases": json.loads(p.phrases_json),
        "human_sayings": p.human_sayings if p.tier == "hd" else [],
        "image_url": f"/petimage/{p.pk}/" if p.hatched and p.image_path else None,
    }


def create_egg(kid, is_hd=False):
    """Create a new un-hatched pet from a fresh random blueprint.

    is_hd=True creates a Legendary egg: higher-resolution image prompt,
    human-readable English sayings, and the tier field set to 'hd'.
    """
    bp = petgen.new_pet_blueprint(is_hd=is_hd)
    return Pet.objects.create(
        kid=kid,
        name=bp["name"],
        traits_json=json.dumps(bp["traits"]),
        prompt=bp["prompt"],
        phrases_json=json.dumps(bp["phrases"]),
        voice_json=json.dumps(bp["voice"]),
        tier="hd" if is_hd else "basic",
        human_sayings_json=json.dumps(bp.get("human_sayings", [])),
    )


def pet_media_allowed(request, kid, pet):
    """May this request view a pet's image/voice? Owner classmates or teacher."""
    return bool(
        (kid and kid.classroom_id == pet.kid.classroom_id)
        or (request.user.is_authenticated
            and pet.kid.classroom.teacher_id == request.user.pk)
    )


# DeepAI text2img generator tier. "standard" is the cheapest (non-pro)
# tier so a subscription's token budget goes further; other values DeepAI
# accepts are "hd" and "genius" (the pro tier). Override via env.
DEFAULT_DEEPAI_VERSION = "standard"


def deepai_image_version():
    return os.environ.get("DEEPAI_IMAGE_VERSION", DEFAULT_DEEPAI_VERSION)


def deepai_text2img(prompt):
    """Call DeepAI text2img; return raw image bytes.  Raises on any failure."""
    import requests as rq

    api_key = os.environ.get("DEEPAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("no_api_key")
    resp = rq.post(
        "https://api.deepai.org/api/text2img",
        data={"text": prompt,
              "image_generator_version": deepai_image_version(),
              "width": str(petgen.IMAGE_SIZE), "height": str(petgen.IMAGE_SIZE)},
        headers={"api-key": api_key},
        timeout=60,
    )
    resp.raise_for_status()
    url = resp.json().get("output_url")
    if not url:
        raise RuntimeError("no_output_url")
    img = rq.get(url, timeout=60)
    img.raise_for_status()
    return img.content


# Cheapest Imagen tier by default — NOT the ultra/pro model — so the same
# token budget goes further.  Override with IMAGEN_MODEL if needed, e.g.
# imagen-4.0-generate-001 or imagen-3.0-generate-002.
DEFAULT_IMAGEN_MODEL = "imagen-4.0-fast-generate-001"


def imagen_generate(prompt):
    """Generate via Google Imagen (Gemini API); return raw image bytes.

    Needs GEMINI_API_KEY.  Raises on any failure (same contract as DeepAI).
    """
    import base64
    import requests as rq

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("no_api_key")
    model = os.environ.get("IMAGEN_MODEL", DEFAULT_IMAGEN_MODEL)
    resp = rq.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:predict",
        json={"instances": [{"prompt": prompt}],
              "parameters": {"sampleCount": 1, "aspectRatio": "1:1",
                             "personGeneration": "dont_allow"}},
        headers={"x-goog-api-key": api_key},
        timeout=60,
    )
    resp.raise_for_status()
    preds = resp.json().get("predictions") or []
    b64 = preds[0].get("bytesBase64Encoded") if preds else None
    if not b64:
        raise RuntimeError("no_image_data")
    return base64.b64decode(b64)


def generate_pet_image(prompt):
    """Generate a pet image with the configured backend.

    PET_IMAGE_BACKEND: "deepai" | "imagen" | unset (auto).
    Auto prefers DeepAI whenever DEEPAI_API_KEY is configured (the primary,
    subscription-backed service); Imagen is the alternative when only
    GEMINI_API_KEY exists. game.views re-exports this as _deepai_generate
    (historical name) so tests and game.tasks keep patching one entry point.
    """
    backend = os.environ.get("PET_IMAGE_BACKEND", "").strip().lower()
    if backend == "deepai":
        return deepai_text2img(prompt)
    if backend == "imagen":
        return imagen_generate(prompt)
    # Auto: DeepAI first (subscription-friendly); Imagen only when there is
    # no DeepAI key but a Gemini key is configured.
    if os.environ.get("DEEPAI_API_KEY"):
        return deepai_text2img(prompt)
    if os.environ.get("GEMINI_API_KEY"):
        return imagen_generate(prompt)
    return deepai_text2img(prompt)


def looks_blank(raw_bytes):
    """True if the image is (nearly) one flat color - a failed generation."""
    import io
    from PIL import Image, ImageStat

    try:
        im = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except Exception:
        return True
    stat = ImageStat.Stat(im)
    return max(stat.stddev) < 8.0


def save_pet_image(pet, raw_bytes):
    """Normalize to exactly 512x512 PNG and store under MEDIA_ROOT/pets/."""
    import io
    from PIL import Image

    im = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    im = im.resize((petgen.IMAGE_SIZE, petgen.IMAGE_SIZE), Image.LANCZOS)
    rel = f"pets/pet_{pet.pk}.png"
    path = os.path.join(settings.MEDIA_ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, "PNG")
    return rel


def hatch_is_stale(pet):
    """True if an in-flight hatch has not advanced recently (or age unknown).

    A worker crash can strand a pet in an in-flight status forever; an age of
    None means the row predates hatch_updated tracking and is treated as
    stale so it can restart rather than stick forever.
    """
    age = pet.hatch_age_seconds()
    return age is None or age >= HATCH_STALE_SECONDS


def dispatch_hatch(pet):
    """Start the async hatch via Celery, falling back to a local thread.

    The thread fallback calls _do_hatch directly rather than invoking the
    Celery task as a plain function, which would bypass Celery's bind/retry
    machinery and could silently swallow the catch-all exception guard.
    """
    try:
        from game.tasks import hatch_pet_task
        result = hatch_pet_task.apply_async(args=[pet.pk])
        pet.hatch_task_id = result.id
        pet.save(update_fields=["hatch_task_id"])
        logger.info(f"Started Celery hatch task {result.id} for pet {pet.pk}")
    except Exception as e:
        # Celery not available — use a plain thread so the app still works
        # without a broker (SQLite + threads is the common dev/small deployment).
        logger.warning(
            f"Celery unavailable, using thread fallback for pet {pet.pk}: {e}")

        pet_pk = pet.pk  # capture before the thread starts

        def _thread_hatch():
            from game.tasks import _do_hatch
            from game.models import Pet as _Pet
            try:
                _pet = _Pet.objects.get(pk=pet_pk)
                _do_hatch(_pet)
            except Exception as exc:
                logger.exception(
                    f"Thread hatch crashed for pet {pet_pk}: {exc}")
                try:
                    _pet = _Pet.objects.get(pk=pet_pk)
                    _pet.set_hatch_status("failed")
                except Exception:
                    pass

        threading.Thread(target=_thread_hatch, daemon=True).start()
