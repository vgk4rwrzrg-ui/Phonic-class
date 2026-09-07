"""Install the bundled human phoneme recordings as the shared letter sounds.

The MP3s in game/seed_audio/ are processed Wikimedia Commons IPA recordings
(see ATTRIBUTION.md there).  They become the shared sound every classroom
hears; per-classroom teacher recordings still override them.
"""
import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from game.models import GraphemeSound

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_audio")


def install_bundled_sound(grapheme, mp3_bytes):
    """Make mp3_bytes the shared (classroom=None) sound for a grapheme."""
    existing = GraphemeSound.objects.filter(
        classroom__isnull=True, grapheme=grapheme).first()
    if existing:
        existing.audio.delete(save=False)
        existing.delete()
    obj = GraphemeSound(classroom=None, grapheme=grapheme, source="bundled")
    obj.audio.save(f"{grapheme}_bundled.mp3", ContentFile(mp3_bytes), save=True)
    return obj


class Command(BaseCommand):
    help = "Install bundled phoneme recordings as the shared letter sounds."

    def add_arguments(self, parser):
        parser.add_argument("--graphemes",
                            help="Comma-separated subset, e.g. S,Z,X")

    def handle(self, *args, **opts):
        seed_dir = os.path.abspath(SEED_DIR)
        wanted = ([g.strip().upper() for g in opts["graphemes"].split(",")]
                  if opts.get("graphemes") else None)
        installed = 0
        for fname in sorted(os.listdir(seed_dir)):
            if not fname.endswith(".mp3"):
                continue
            g = fname[:-4].upper()
            if wanted and g not in wanted:
                continue
            with open(os.path.join(seed_dir, fname), "rb") as fh:
                install_bundled_sound(g, fh.read())
            installed += 1
            self.stdout.write(f"  {g}: installed bundled recording")
        self.stdout.write(self.style.SUCCESS(f"{installed} sounds installed. "
            "Teacher recordings (if any) still take priority."))
