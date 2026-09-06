from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor

from game import phrases, tts
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

    def _generate_shared_graphemes(self, graphemes, opts):
        """Google letter sounds are shared by every classroom (classroom=None)."""
        for g in sorted(graphemes):
            existing = GraphemeSound.objects.filter(
                classroom__isnull=True, grapheme=g).first()
            if existing and not opts["force"]:
                self.stdout.write(f"already have  {g}")
                continue
            try:
                audio = tts.synthesize(g)
            except Exception as exc:  # no credentials / network / quota
                self.stderr.write(f"FAILED {g}: {exc}")
                continue
            obj = existing or GraphemeSound(classroom=None, grapheme=g, source="google")
            obj.source = "google"
            obj.audio.save(f"shared_{g.lower()}.mp3", ContentFile(audio), save=True)
            self.stdout.write(self.style.SUCCESS(f"generated {g}"))

    def _generate_for(self, classroom, opts):
        self.stdout.write(f"Generating sounds for {classroom.name} ({classroom.code})...")
        graphemes = set(tts.GRAPHEME_IPA)
        for word in classroom.words.filter(active=True):
            graphemes.update(tts.split_graphemes(word.text))
        self._generate_shared_graphemes(graphemes, opts)

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

    def _generate_phrases(self, opts):
        """Praise / hint / boss-line audio shared by every classroom."""
        import os

        from django.conf import settings

        pdir = os.path.join(settings.MEDIA_ROOT, "phrases")
        os.makedirs(pdir, exist_ok=True)
        for slug, text in sorted(phrases.all_phrases().items()):
            path = os.path.join(pdir, f"{slug}.mp3")
            if os.path.exists(path) and not opts["force"]:
                self.stdout.write(f"already have  {slug}")
                continue
            try:
                raw = tts.synthesize_phrase(text)
            except Exception as exc:
                self.stderr.write(f"FAILED {slug}: {exc}")
                continue
            with open(path, "wb") as fh:
                fh.write(raw)
            self.stdout.write(self.style.SUCCESS(f"generated phrase {slug}"))

    def handle(self, *args, **opts):
        # Refuse to run against an out-of-date database: writing shared
        # sounds (classroom=NULL) or word sources needs migrations 0011-0013.
        executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            missing = ", ".join(f"{mig.app_label}.{mig.name}" for mig, _ in plan)
            raise CommandError(
                "Your database is missing migrations: " + missing +
                "\nRun this first, then re-run makevoices:\n"
                "    python manage.py migrate"
            )
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
        self._generate_phrases(opts)
        self.stdout.write(self.style.SUCCESS("done"))
