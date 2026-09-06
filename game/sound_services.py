"""Audio storage & synthesis services.

Single home for the repeated pattern "clean/synthesize audio, then attach it
to the right sound row with the right filename".  Views and management
commands stay thin; the sound-priority rules live in the model managers.
"""

import io
import mimetypes
import os
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import FileResponse

from . import audio, phrases, tts
from .models import GraphemeSound, WordSound

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/webm", ".webm")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/mp4", ".mp4")


def content_type(name):
    """Best-effort audio MIME type for a stored filename."""
    mime, _ = mimetypes.guess_type(name or "")
    return mime or "audio/mpeg"


def audio_response(filefield):
    """Stream a stored audio FileField back to the browser."""
    return FileResponse(filefield.open("rb"),
                        content_type=content_type(filefield.name))


# ---------------------------------------------------------------------------
# Google TTS caching (shared graphemes, per-class words)
# ---------------------------------------------------------------------------

def store_google_grapheme(grapheme, raw, existing=None):
    """Attach synthesized audio to the shared (classroom=None) grapheme row."""
    obj = existing or GraphemeSound(classroom=None, grapheme=grapheme,
                                    source="google")
    obj.source = "google"
    obj.audio.save(f"shared_{grapheme.lower()}.mp3", ContentFile(raw), save=True)
    return obj


def store_google_word(classroom, word, raw, existing=None):
    """Attach synthesized audio to a per-class word row."""
    obj = existing or WordSound(classroom=classroom, word=word)
    obj.source = "google"
    obj.audio.save(f"{classroom.pk}_{word.lower()}.mp3", ContentFile(raw),
                   save=True)
    return obj


def synthesize_shared_grapheme(grapheme):
    """Synthesize + cache the shared Google sound for a grapheme.

    Raises whatever the TTS client raises (no credentials / quota / network);
    callers translate that into their endpoint's failure response.
    """
    raw = tts.synthesize(grapheme)
    return store_google_grapheme(grapheme, raw)


def synthesize_class_word(classroom, word, existing=None):
    """Synthesize + cache Google audio for one of this class's words."""
    raw = tts.synthesize_word(word)
    return store_google_word(classroom, word, raw, existing=existing)


# ---------------------------------------------------------------------------
# Teacher recordings (ffmpeg-cleaned custom audio)
# ---------------------------------------------------------------------------

def _store_custom(obj, classroom, key, raw, src_name):
    """Run the ffmpeg cleanup pipeline and store the result as custom audio."""
    cleaned, ext = audio.clean_audio(raw, src_name)
    obj.source = "custom"
    obj.audio.save(f"{classroom.pk}_{key.lower()}.{ext}", ContentFile(cleaned),
                   save=True)
    return obj


def save_custom_grapheme(classroom, grapheme, raw, src_name):
    """Store a teacher grapheme recording (silence-trimmed via ffmpeg)."""
    obj, _ = GraphemeSound.objects.get_or_create(classroom=classroom,
                                                 grapheme=grapheme)
    return _store_custom(obj, classroom, grapheme, raw, src_name)


def save_custom_word(classroom, word, raw, src_name):
    """Store a teacher whole-word recording (silence-trimmed via ffmpeg)."""
    obj, _ = WordSound.objects.get_or_create(classroom=classroom, word=word)
    return _store_custom(obj, classroom, word, raw, src_name)


# ---------------------------------------------------------------------------
# Spoken phrases (praise / hints / boss lines) cached on disk
# ---------------------------------------------------------------------------

def phrase_media_dir():
    return os.path.join(settings.MEDIA_ROOT, "phrases")


def phrase_audio_path(slug):
    """Absolute path of a phrase mp3, generating + caching it on first use.

    Returns None for unknown slugs.  Raises on TTS failure (caller decides
    the fallback, usually browser speechSynthesis).
    """
    text = phrases.all_phrases().get(slug)
    if not text:
        return None
    path = os.path.join(phrase_media_dir(), f"{slug}.mp3")
    if not os.path.exists(path):
        raw = tts.synthesize_phrase(text)
        os.makedirs(phrase_media_dir(), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(raw)
    return path


# ---------------------------------------------------------------------------
# Bulk export
# ---------------------------------------------------------------------------

def _zip_letter_sounds(zf, classroom):
    for gs in GraphemeSound.objects.filter(
            Q(classroom__isnull=True) | Q(classroom=classroom)):
        if not gs.audio:
            continue
        try:
            tag = "custom" if gs.source == "custom" else "google"
            zf.writestr(f"letters/{gs.grapheme}_{tag}.mp3", gs.audio.read())
        except FileNotFoundError:
            continue


def _zip_word_sounds(zf, classroom):
    for ws in classroom.word_sounds.all():
        if not ws.audio:
            continue
        try:
            zf.writestr(f"words/{ws.word}_{ws.source}.mp3", ws.audio.read())
        except FileNotFoundError:
            continue


def _zip_phrases(zf):
    pdir = phrase_media_dir()
    if not os.path.isdir(pdir):
        return
    for name in sorted(os.listdir(pdir)):
        if name.endswith(".mp3"):
            zf.write(os.path.join(pdir, name), f"phrases/{name}")


def build_audio_zip(classroom):
    """Zip every letter/word/phrase audio file this class can hear."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _zip_letter_sounds(zf, classroom)
        _zip_word_sounds(zf, classroom)
        _zip_phrases(zf)
    buf.seek(0)
    return buf
