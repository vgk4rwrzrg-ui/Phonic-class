"""Audio cleanup via ffmpeg: trim silence + reduce background noise."""

import os
import subprocess
import tempfile

FILTERS = (
    "silenceremove=start_periods=1:start_threshold=-40dB:"
    "stop_periods=-1:stop_threshold=-40dB:stop_silence=0.2,"
    "highpass=f=80,afftdn=nf=-25,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


def _ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _ffmpeg_available(ff):
    try:
        subprocess.run(
            [ff, "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=True, timeout=10,
        )
        return True
    except Exception:
        return False


def clean_audio(raw_bytes, src_name="audio.webm"):
    """Trim silence and reduce noise, returning (cleaned_bytes, "mp3").

    Falls back to the raw bytes (original extension) if ffmpeg is missing or
    processing fails.
    """
    src_ext = os.path.splitext(src_name or "")[1].lower() or ".webm"
    if not raw_bytes:
        return raw_bytes, src_ext.lstrip(".")

    ff = _ffmpeg_path()
    if not _ffmpeg_available(ff):
        return raw_bytes, src_ext.lstrip(".")

    try:
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "in" + src_ext)
            dst = os.path.join(td, "out.mp3")
            with open(src, "wb") as fh:
                fh.write(raw_bytes)
            cmd = [
                ff, "-y", "-hide_banner", "-loglevel", "error",
                "-i", src,
                "-af", FILTERS,
                "-ar", "44100", "-ac", "1",
                "-c:a", "libmp3lame", "-b:a", "128k",
                dst,
            ]
            subprocess.run(cmd, check=True, timeout=60)
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                with open(dst, "rb") as fh:
                    return fh.read(), "mp3"
    except Exception:
        pass
    return raw_bytes, src_ext.lstrip(".")
