"""Audio playback endpoints: graphemes, words, and cached phrases.

Priority for every sound: teacher recording for the class, then cached Google
TTS, then on-the-fly Google TTS (cached for next time).  When TTS is
unavailable the JSON error tells the frontend to fall back to browser speech.
"""

import logging

from django.http import FileResponse

from ..context import playback_classroom
from ..jsonapi import json_fail, upper_param
from ..models import GraphemeSound, WordSound
from .. import sound_services

logger = logging.getLogger(__name__)


def sound(request, grapheme):
    """Serve the letter/grapheme sound for the requester's classroom."""
    g = upper_param(grapheme, 8)
    if not g:
        return json_fail("missing sound", status=400)
    cr = playback_classroom(request)
    if not cr:
        return json_fail("not signed in", status=403)

    obj = GraphemeSound.objects.playable(cr, g)
    if not (obj and obj.audio):
        try:
            obj = sound_services.synthesize_shared_grapheme(g)
        except Exception as exc:  # no credentials / network / quota
            logger.exception("Letter sound synthesis failed for %s", g)
            return json_fail(str(exc), status=503)
    return sound_services.audio_response(obj.audio)


def word_sound(request, word):
    """Serve whole-word audio, Google-synthesizing class words on demand."""
    w = upper_param(word, 20)
    cr = playback_classroom(request)
    if not cr:
        return json_fail("not signed in", status=403)

    obj = WordSound.objects.filter(classroom=cr, word=w).first()
    if obj and obj.audio:
        return sound_services.audio_response(obj.audio)
    # No recording: fall back to Google TTS for whole words (same as graphemes).
    # Only synthesize words that belong to this class, so kids can't spend the
    # teacher's TTS quota on arbitrary text.
    if not cr.words.filter(text=w).exists():
        return json_fail("no word sound", status=404)
    try:
        obj = sound_services.synthesize_class_word(cr, w, existing=obj)
    except Exception:  # no credentials / network / quota -> browser TTS fallback
        logger.exception("Word sound synthesis failed for %s", w)
        return json_fail("no word sound", status=404)
    return sound_services.audio_response(obj.audio)


def phrase_sound(request, slug):
    """Serve Google TTS audio for a registered game phrase, generating and
    caching it on first use. Unknown slugs 404 (browser TTS fallback)."""
    cr = playback_classroom(request)
    if not cr:
        return json_fail("not signed in", status=403)
    try:
        path = sound_services.phrase_audio_path(slug)
    except Exception:  # no credentials -> browser TTS fallback
        logger.exception("Phrase synthesis failed for %s", slug)
        return json_fail("tts unavailable", status=404)
    if not path:
        return json_fail("unknown phrase", status=404)
    return FileResponse(open(path, "rb"), content_type="audio/mpeg")
