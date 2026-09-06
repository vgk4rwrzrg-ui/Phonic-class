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
        "traits": json.loads(p.traits_json),
        "phrases": json.loads(p.phrases_json),
        "image_url": f"/petimage/{p.pk}/" if p.hatched and p.image_path else None,
    }


def create_egg(kid):
    """Create a new un-hatched pet from a fresh random blueprint."""
    bp = petgen.new_pet_blueprint()
    return Pet.objects.create(
        kid=kid,
        name=bp["name"],
        traits_json=json.dumps(bp["traits"]),
        prompt=bp["prompt"],
        phrases_json=json.dumps(bp["phrases"]),
        voice_json=json.dumps(bp["voice"]),
    )


def pet_media_allowed(request, kid, pet):
    """May this request view a pet's image/voice? Owner classmates or teacher."""
    return bool(
        (kid and kid.classroom_id == pet.kid.classroom_id)
        or (request.user.is_authenticated
            and pet.kid.classroom.teacher_id == request.user.pk)
    )


def deepai_generate(prompt):
    """Call DeepAI text2img; return raw image bytes.  Raises on any failure."""
    import requests as rq

    api_key = os.environ.get("DEEPAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("no_api_key")
    resp = rq.post(
        "https://api.deepai.org/api/text2img",
        data={"text": prompt, "image_generator_version": "standard",
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
    """Start the async hatch via Celery, falling back to a local thread."""
    try:
        from game.tasks import hatch_pet_task
        result = hatch_pet_task.apply_async(args=[pet.pk])
        pet.hatch_task_id = result.id
        pet.save(update_fields=["hatch_task_id"])
        logger.info(f"Started Celery hatch task {result.id} for pet {pet.pk}")
    except Exception as e:
        # Celery not available - use thread fallback
        logger.warning(
            f"Celery unavailable, using thread fallback for pet {pet.pk}: {e}")

        def _thread_hatch():
            from game.tasks import hatch_pet_task
            hatch_pet_task(pet.pk)

        threading.Thread(target=_thread_hatch, daemon=True).start()
