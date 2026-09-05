import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from game import audio
from game.models import Class, GraphemeSound


class Command(BaseCommand):
    help = "Import teacher audio files into a class (name each file after its sound, e.g. SH.mp3, A.wav)."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Folder containing audio files to import")
        parser.add_argument("--class", dest="code", help="Class code. Defaults to first class.")

    def handle(self, *args, **opts):
        folder = opts["folder"]
        if not os.path.isdir(folder):
            self.stderr.write(f"not a folder: {folder}")
            return

        if opts["code"]:
            classroom = Class.objects.filter(code=opts["code"].upper()).first()
        else:
            classroom = Class.objects.order_by("id").first()
        if not classroom:
            self.stderr.write("No class found. Sign up first or pass --class CODE.")
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
            obj, _ = GraphemeSound.objects.get_or_create(grapheme=grapheme, classroom=classroom)
            obj.source = "custom"
            with open(path, "rb") as fh:
                raw = fh.read()
            cleaned, out_ext = audio.clean_audio(raw, name)
            obj.audio.save(f"{classroom.pk}_{grapheme.lower()}.{out_ext}", ContentFile(cleaned), save=True)
            count += 1
            self.stdout.write(self.style.SUCCESS(f"imported {grapheme}"))

        self.stdout.write(self.style.SUCCESS(
            f"imported {count} files into {classroom.name} ({classroom.code})"))
