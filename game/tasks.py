"""Celery tasks for async pet hatching."""
from __future__ import absolute_import, unicode_literals
import logging
import time

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def hatch_pet_task(self, pet_id):
    """Generate a pet image in the background with progress updates.

    Stages: unhatched -> cracking -> halfway -> hatching -> complete/failed.
    ANY unexpected exception marks the pet 'failed' so the kid can retry --
    the pet must never be left stuck in an in-flight status.
    """
    from game.models import Pet

    try:
        pet = Pet.objects.get(pk=pet_id)
    except Pet.DoesNotExist:
        logger.error(f"Pet {pet_id} not found for hatching")
        return {"status": "failed", "error": "Pet not found"}

    try:
        return _do_hatch(pet)
    except Exception as e:
        # Catch-all safety net: without this, a crash leaves hatch_status
        # stuck at 'cracking'/'halfway'/'hatching' and the hatch endpoint
        # refuses to ever retry (the bug that froze eggs in production).
        logger.exception(f"Pet hatch crashed unexpectedly (pet {pet.pk})")
        pet.set_hatch_status("failed")
        return {"status": "failed", "error": str(e)}


def _fail(pet, error):
    """Mark the hatch failed and build the task result."""
    pet.set_hatch_status("failed")
    return {"status": "failed", "error": error}


def _generate_image(pet):
    """Call DeepAI (via the patchable game.views alias); (raw, error)."""
    # Resolved through game.views at call time so tests can patch
    # game.views._deepai_generate without touching the network.
    from game import views

    try:
        return views._deepai_generate(pet.prompt), None
    except RuntimeError as e:
        if str(e) == "no_api_key":
            logger.error(
                f"Pet hatch failed (pet {pet.pk}): DEEPAI_API_KEY is not set")
        else:
            logger.exception(f"Pet hatch failed (pet {pet.pk})")
        return None, str(e)
    except Exception as e:
        logger.exception(f"Pet hatch failed (pet {pet.pk})")
        return None, str(e)


def _do_hatch(pet):
    from game import views  # patchable aliases: _looks_blank, _save_pet_image

    # Stage 1: cracking (starting)
    pet.set_hatch_status("cracking")
    time.sleep(0.5)  # brief pause for visual feedback

    # Stage 2: halfway (calling DeepAI)
    pet.set_hatch_status("halfway")
    raw, error = _generate_image(pet)
    if error is not None:
        return _fail(pet, error)

    # Stage 3: hatching (processing image)
    pet.set_hatch_status("hatching")
    if views._looks_blank(raw):
        logger.error(
            f"Pet hatch (pet {pet.pk}): DeepAI returned a blank/flat image")
        return _fail(pet, "blank_image")

    # Stage 4: complete
    pet.set_hatch_status("complete",
                         image_path=views._save_pet_image(pet, raw),
                         hatched=True)
    logger.info(f"Pet {pet.pk} ({pet.name}) hatched successfully")
    return {"status": "complete", "pet_id": pet.pk, "name": pet.name}
