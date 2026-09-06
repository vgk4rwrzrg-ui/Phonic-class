from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from game import tts
from game.models import Class, GraphemeSound, Word, WordSound


class Command(BaseCommand):
    help = "Pre-generate letter AND word sounds with Google Cloud TTS for a class (custom uploads are kept)."

    def add_arguments(self, parser):
        parser.add_argument("--class", dest="code", help="Class code. Defaults to first class.")
        parser.add_argument("--all", action="store_true", help="Generate for ALL classes.")
        parser.add_argument(
            "--force", action="store_true",
            help="Regenerate Google sounds that already exist.",
        )

    def _generate_for(self, classroom, opts):
        self.stdout.write(f"Generating sounds for {classroom.name} ({classroom.code})...")
        graphemes = set(tts.GRAPHEME_IPA)
        for word in classroom.words.filter(active=True):
            graphemes.update(tts.split_graphemes(word.text))

        for g in sorted(graphemes):
            existing = classroom.grapheme_sounds.filter(grapheme=g).first()
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
            obj = existing or GraphemeSound(classroom=classroom, grapheme=g)
            obj.source = "google"
            obj.audio.save(f"{g.lower()}.mp3", ContentFile(audio), save=True)
            self.stdout.write(self.style.SUCCESS(f"generated {g}"))

        # Whole-word audio for the "HEAR FULL WORD" button
        for word in classroom.words.filter(active=True):
            w = word.text
            existing = classroom.word_sounds.filter(word=w).first()
            if existing and existing.source == "custom":
                self.stdout.write(f"keeping custom  {w}")
                continue
            if existing and not opts["force"]:
                self.stdout.write(f"already have  {w}")
                continue
            try:
                audio = tts.synthesize_word(w)
            except Exception as exc:
                self.stderr.write(f"FAILED {w}: {exc}")
                continue
            obj = existing or WordSound(classroom=classroom, word=w)
            obj.source = "google"
            obj.audio.save(f"{classroom.pk}_{w.lower()}.mp3", ContentFile(audio), save=True)
            self.stdout.write(self.style.SUCCESS(f"generated word {w}"))

    def handle(self, *args, **opts):
        if opts["all"]:
            classrooms = list(Class.objects.order_by("name"))
        elif opts["code"]:
            classrooms = list(Class.objects.filter(code=opts["code"].upper()))
        else:
            classrooms = list(Class.objects.order_by("id")[:1])
        if not classrooms:
            self.stderr.write("No class found.")
            return
        for cr in classrooms:
            self._generate_for(cr, opts)
        self.stdout.write(self.style.SUCCESS("done"))
