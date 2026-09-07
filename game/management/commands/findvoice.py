"""Scan Google TTS voices to find ones that actually HONOR IPA phoneme tags.

Each candidate costs two tiny synthesis calls: the same text once with a
deliberately wrong phoneme ("mmm") and once plain.  Identical audio bytes
mean the voice ignores <phoneme>; different bytes mean it honors IPA and
will produce true phonic sounds.
"""
from django.core.management.base import BaseCommand

from game import tts

DEFAULT_CANDIDATES = [
    "en-US-Wavenet-A", "en-US-Wavenet-B", "en-US-Wavenet-C", "en-US-Wavenet-D",
    "en-US-Wavenet-E", "en-US-Wavenet-F", "en-US-Wavenet-G", "en-US-Wavenet-H",
    "en-US-Standard-C", "en-US-Standard-E",
    "en-GB-Wavenet-A", "en-GB-Wavenet-C", "en-GB-Wavenet-F",
    "en-AU-Wavenet-A", "en-AU-Wavenet-C",
]

PROBE_TAGGED = '<speak><phoneme alphabet="ipa" ph="m\u02d0">s</phoneme></speak>'
PROBE_PLAIN = "<speak>s</speak>"


def voice_honors_phonemes(name):
    """True if this voice renders IPA instead of reading the fallback text."""
    return (tts._synth_ssml(PROBE_TAGGED, voice_name=name)
            != tts._synth_ssml(PROBE_PLAIN, voice_name=name))


class Command(BaseCommand):
    help = "Probe Google TTS voices for real SSML <phoneme> (IPA) support."

    def add_arguments(self, parser):
        parser.add_argument(
            "--voices",
            help="Comma-separated voice names to probe instead of the default list.",
        )

    def handle(self, *args, **opts):
        names = ([v.strip() for v in opts["voices"].split(",") if v.strip()]
                 if opts.get("voices") else DEFAULT_CANDIDATES)
        honored = []
        for name in names:
            try:
                ok = voice_honors_phonemes(name)
            except Exception as exc:
                self.stderr.write(f"{name:<24} ERROR: {exc}")
                continue
            if ok:
                honored.append(name)
                self.stdout.write(self.style.SUCCESS(f"{name:<24} HONORS IPA"))
            else:
                self.stdout.write(f"{name:<24} ignores <phoneme>")
        self.stdout.write("")
        if honored:
            self.stdout.write(self.style.SUCCESS(
                f"Pick one, e.g.: GOOGLE_TTS_VOICE={honored[0]}\n"
                "Add it to your systemd [Service] Environment=, daemon-reload, "
                "restart, then run: python manage.py makevoices --force"))
        else:
            self.stdout.write(self.style.WARNING(
                "No probed voice honors IPA. Your respellings still give correct "
                "phonics; teacher recordings remain the gold standard."))
