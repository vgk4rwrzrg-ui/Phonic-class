from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from game import tts
from game.models import GraphemeSound, Word


class Command(BaseCommand):
    help = "Pre-generate letter sounds with Google Cloud TTS (custom uploads are kept)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate Google sounds that already exist.",
        )

    def handle(self, *args, **opts):
        graphemes = set(tts.GRAPHEME_IPA)
        for word in Word.objects.filter(active=True):
            graphemes.update(tts.split_graphemes(word.text))

        for g in sorted(graphemes):
            existing = GraphemeSound.objects.filter(grapheme=g).first()
            if existing and existing.source == "custom":
                self.stdout.write(f"keeping custom  {g}")
                continue
            if existing and not opts["force"]:
                self.stdout.write(f"already have  {g}")
                continue
            try:
                audio = tts.synthesize(g)
            except Exception as exc:  # no credentials / network / quota
                self.stderr.write(f"FAILED {g}: {exc}")
                continue
            obj = existing or GraphemeSound(grapheme=g)
            obj.source = "google"
            obj.audio.save(f"{g.lower()}.mp3", ContentFile(audio), save=True)
            self.stdout.write(self.style.SUCCESS(f"generated {g}"))

        self.stdout.write(self.style.SUCCESS("done"))
