"""Celery tasks for async pet hatching."""
from __future__ import absolute_import, unicode_literals
import logging
import os
import time
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def hatch_pet_task(self, pet_id):
    """Generate a pet image in the background with progress updates.
    
    Stages: unhatched → cracking → halfway → hatching → complete/failed
    """
    from game.models import Pet
    from game import views  # for _deepai_generate, _looks_blank, _save_pet_image
    
    try:
        pet = Pet.objects.get(pk=pet_id)
    except Pet.DoesNotExist:
        logger.error(f"Pet {pet_id} not found for hatching")
        return {"status": "failed", "error": "Pet not found"}
    
    # Stage 1: cracking (10% - starting)
    pet.hatch_status = 'cracking'
    pet.save(update_fields=['hatch_status'])
    time.sleep(0.5)  # Brief pause for visual feedback
    
    # Stage 2: halfway (40% - calling DeepAI)
    pet.hatch_status = 'halfway'
    pet.save(update_fields=['hatch_status'])
    
    try:
        raw = views._deepai_generate(pet.prompt)
    except RuntimeError as e:
        if str(e) == "no_api_key":
            logger.error(f"Pet hatch failed (pet {pet.pk}): DEEPAI_API_KEY is not set")
            pet.hatch_status = 'failed'
            pet.save(update_fields=['hatch_status'])
            return {"status": "failed", "error": "no_api_key"}
        logger.exception(f"Pet hatch failed (pet {pet.pk})")
        pet.hatch_status = 'failed'
        pet.save(update_fields=['hatch_status'])
        return {"status": "failed", "error": str(e)}
    except Exception as e:
        logger.exception(f"Pet hatch failed (pet {pet.pk})")
        pet.hatch_status = 'failed'
        pet.save(update_fields=['hatch_status'])
        return {"status": "failed", "error": str(e)}
    
    # Stage 3: hatching (70% - processing image)
    pet.hatch_status = 'hatching'
    pet.save(update_fields=['hatch_status'])
    
    if views._looks_blank(raw):
        logger.error(f"Pet hatch (pet {pet.pk}): DeepAI returned a blank/flat image")
        pet.hatch_status = 'failed'
        pet.save(update_fields=['hatch_status'])
        return {"status": "failed", "error": "blank_image"}
    
    # Stage 4: complete (100%)
    try:
        pet.image_path = views._save_pet_image(pet, raw)
        pet.hatched = True
        pet.hatch_status = 'complete'
        pet.save(update_fields=['image_path', 'hatched', 'hatch_status'])
        logger.info(f"Pet {pet.pk} ({pet.name}) hatched successfully")
        return {"status": "complete", "pet_id": pet.pk, "name": pet.name}
    except Exception as e:
        logger.exception(f"Pet hatch image save failed (pet {pet.pk})")
        pet.hatch_status = 'failed'
        pet.save(update_fields=['hatch_status'])
        return {"status": "failed", "error": str(e)}
