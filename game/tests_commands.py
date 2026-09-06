"""Management command tests (filesystem + ffmpeg mocked where needed).

Run with: python manage.py test game.tests_commands
"""
import io
import os
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from game.models import Class, GraphemeSound, Word

TEMP_MEDIA = tempfile.mkdtemp(prefix="phonics_test_media_c_")


def _classroom(name="C1", username="teach"):
    teacher = User.objects.create_user(username, password="pw")
    return Class.objects.create(teacher=teacher, name=name)


class SeedWordsTests(TestCase):
    def test_seeds_starter_list(self):
        cr = _classroom()
        out = io.StringIO()
        call_command("seedwords", stdout=out)
        self.assertEqual(cr.words.count(), 28)
        self.assertEqual(cr.words.get(text="SHIP").level, 3)
        self.assertIn("Seeded 28 words", out.getvalue())

    def test_idempotent(self):
        cr = _classroom()
        call_command("seedwords", stdout=io.StringIO())
        out = io.StringIO()
        call_command("seedwords", stdout=out)
        self.assertIn("Seeded 0 words", out.getvalue())
        self.assertEqual(cr.words.count(), 28)

    def test_class_code_selection(self):
        cr1 = _classroom("C1", "t1")
        cr2 = Class.objects.create(teacher=cr1.teacher, name="C2")
        call_command("seedwords", **{"code": cr2.code.lower()},
                     stdout=io.StringIO())
        self.assertEqual(cr1.words.count(), 0)
        self.assertEqual(cr2.words.count(), 28)

    def test_no_class(self):
        err = io.StringIO()
        call_command("seedwords", stderr=err)
        self.assertIn("No class found", err.getvalue())


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ImportSoundsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.cr = _classroom()
        self.folder = tempfile.mkdtemp(prefix="phonics_import_")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def _touch(self, name, data=b"AUDIO"):
        with open(os.path.join(self.folder, name), "wb") as fh:
            fh.write(data)

    def test_imports_files_as_custom_sounds(self):
        self._touch("sh.mp3")
        self._touch("A.wav")
        out = io.StringIO()
        with patch("game.audio.clean_audio",
                   return_value=(b"CLEAN", "mp3")) as m:
            call_command("importsounds", self.folder, stdout=out)
        self.assertEqual(m.call_count, 2)
        self.assertEqual(
            set(GraphemeSound.objects.filter(classroom=self.cr)
                .values_list("grapheme", flat=True)), {"SH", "A"})
        for gs in GraphemeSound.objects.all():
            self.assertEqual(gs.source, "custom")
        self.assertIn("imported 2 files", out.getvalue())

    def test_subdirectories_are_skipped(self):
        os.mkdir(os.path.join(self.folder, "nested"))
        self._touch("b.mp3")
        with patch("game.audio.clean_audio", return_value=(b"C", "mp3")):
            call_command("importsounds", self.folder, stdout=io.StringIO())
        self.assertEqual(GraphemeSound.objects.count(), 1)

    def test_bad_folder(self):
        err = io.StringIO()
        call_command("importsounds", "/no/such/dir", stderr=err)
        self.assertIn("not a folder", err.getvalue())

    def test_no_class(self):
        Class.objects.all().delete()
        err = io.StringIO()
        call_command("importsounds", self.folder, stderr=err)
        self.assertIn("No class found", err.getvalue())
