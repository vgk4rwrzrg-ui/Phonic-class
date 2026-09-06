import os

from django.core.management.base import BaseCommand

from game import sound_services
from game.models import Class


class Command(BaseCommand):
    help = "Import teacher audio files into a class (name each file after its sound, e.g. SH.mp3, A.wav)."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Folder containing audio files to import")
        parser.add_argument("--class", dest="code", help="Class code. Defaults to first class.")

    def _import_file(self, classroom, path, name):
        """Import one audio file; returns True if it became a grapheme sound."""
        grapheme = os.path.splitext(name)[0].strip().upper()[:8]
        if not grapheme:
            return False
        with open(path, "rb") as fh:
            raw = fh.read()
        sound_services.save_custom_grapheme(classroom, grapheme, raw, name)
        self.stdout.write(self.style.SUCCESS(f"imported {grapheme}"))
        return True

    def handle(self, *args, **opts):
        folder = opts["folder"]
        if not os.path.isdir(folder):
            self.stderr.write(f"not a folder: {folder}")
            return
        classroom = Class.objects.by_code_or_first(opts["code"])
        if not classroom:
            self.stderr.write("No class found. Sign up first or pass --class CODE.")
            return

        count = 0
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and self._import_file(classroom, path, name):
                count += 1
        self.stdout.write(self.style.SUCCESS(
            f"imported {count} files into {classroom.name} ({classroom.code})"))
