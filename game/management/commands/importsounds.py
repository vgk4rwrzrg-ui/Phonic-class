import os

from django.core.files import File
from django.core.management.base import BaseCommand

from game.models import GraphemeSound


class Command(BaseCommand):
    help = "Import teacher audio files from a folder (name each file after its sound, e.g. SH.mp3, A.wav)."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Folder containing audio files to import")

    def handle(self, *args, **opts):
        folder = opts["folder"]
        if not os.path.isdir(folder):
            self.stderr.write(f"not a folder: {folder}")
            return

        count = 0
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            base, ext = os.path.splitext(name)
            grapheme = base.strip().upper()[:8]
            if not grapheme:
                continue
            obj, _ = GraphemeSound.objects.get_or_create(grapheme=grapheme)
            obj.source = "custom"
            with open(path, "rb") as fh:
                obj.audio.save(f"{grapheme.lower()}{ext.lower()}", File(fh), save=True)
            count += 1
            self.stdout.write(self.style.SUCCESS(f"imported {grapheme}"))

        self.stdout.write(self.style.SUCCESS(f"imported {count} files"))
