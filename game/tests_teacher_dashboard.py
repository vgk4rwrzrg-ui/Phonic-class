"""Teacher dashboard action + AJAX endpoint tests (ffmpeg/TTS mocked).

Run with: python manage.py test game.tests_teacher_dashboard
"""
import io
import json
import shutil
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from game.models import (Class, GraphemeSound, Kid, SoundMiss, Word,
                         WordSound)

TEMP_MEDIA = tempfile.mkdtemp(prefix="phonics_test_media_t_")


class DashboardBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.teacher = User.objects.create_user("teach", password="pw")
        self.cr = Class.objects.create(teacher=self.teacher, name="C1")
        self.client.force_login(self.teacher)

    def act(self, action, **data):
        return self.client.post("/teacher/", {"action": action, **data}).json()


class DashboardAuthTests(DashboardBase):
    def test_login_required(self):
        self.client.logout()
        resp = self.client.get("/teacher/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/teacher/login/", resp["Location"])

    def test_unknown_action(self):
        self.assertEqual(self.act("frobnicate")["message"], "Unknown action")


class KidRosterActionTests(DashboardBase):
    def test_add_kid_happy_path(self):
        d = self.act("add_kid", name="Zoe", pin="4321", icon="X")
        self.assertTrue(d["success"])
        kid = Kid.objects.get(classroom=self.cr, name="Zoe")
        self.assertEqual(kid.pin, "4321")  # plain text by design

    def test_add_kid_rejects_bad_pin(self):
        for pin in ("12", "abcd", ""):
            d = self.act("add_kid", name="Zoe", pin=pin)
            self.assertFalse(d["success"], pin)
        self.assertEqual(Kid.objects.count(), 0)

    def test_add_kid_duplicate(self):
        Kid.objects.create(classroom=self.cr, name="Zoe", pin="1111")
        d = self.act("add_kid", name="Zoe", pin="2222")
        self.assertEqual(d["message"], "Kid already exists")

    def test_set_pin(self):
        kid = Kid.objects.create(classroom=self.cr, name="Zoe", pin="1111")
        self.assertTrue(self.act("set_pin", kid_id=kid.pk, pin="9876")["success"])
        kid.refresh_from_db()
        self.assertEqual(kid.pin, "9876")
        self.assertFalse(self.act("set_pin", kid_id=kid.pk, pin="98a6")["success"])

    def test_del_kid(self):
        kid = Kid.objects.create(classroom=self.cr, name="Zoe", pin="1111")
        self.assertTrue(self.act("del_kid", kid_id=kid.pk)["success"])
        self.assertEqual(Kid.objects.count(), 0)
        self.assertFalse(self.act("del_kid", kid_id=999)["success"])


class WordActionTests(DashboardBase):
    def test_add_words_parses_levels_tabs_and_junk(self):
        d = self.act("add_words",
                     words="cat\nship, 3\nfrog\t2\nbad word!\n\nx, 9")
        self.assertTrue(d["success"])
        self.assertEqual(d["message"], "Added 4 words")
        self.assertEqual(Word.objects.get(text="SHIP").level, 3)
        self.assertEqual(Word.objects.get(text="FROG").level, 2)
        self.assertEqual(Word.objects.get(text="X").level, 3)  # clamped 9 -> 3
        self.assertFalse(Word.objects.filter(text__contains="BAD").exists())

    def test_add_words_updates_existing_without_counting(self):
        Word.objects.create(classroom=self.cr, text="CAT", level=1, active=False)
        d = self.act("add_words", words="cat, 2")
        self.assertEqual(d["message"], "Added 0 words")
        w = Word.objects.get(text="CAT")
        self.assertEqual((w.level, w.active), (2, True))

    def test_toggle_and_delete_word(self):
        w = Word.objects.create(classroom=self.cr, text="CAT")
        d = self.act("toggle_word", word_id=w.pk)
        self.assertFalse(d["active"])
        self.assertTrue(self.act("del_word", word_id=w.pk)["success"])
        self.assertEqual(Word.objects.count(), 0)

    def test_deactivate_all(self):
        for t in ("CAT", "DOG"):
            Word.objects.create(classroom=self.cr, text=t)
        d = self.act("deactivate_all")
        self.assertEqual(d["message"], "Deactivated 2 words")
        self.assertFalse(Word.objects.filter(active=True).exists())


class StatsAndClassActionTests(DashboardBase):
    def test_reset_week_and_all(self):
        kid = Kid.objects.create(classroom=self.cr, name="Z", pin="1111",
                                 points_total=90, points_week=40, streak=3)
        SoundMiss.objects.record(kid, "SH")
        self.act("reset_week")
        kid.refresh_from_db()
        self.assertEqual((kid.points_week, kid.points_total), (0, 90))
        self.act("reset_all")
        kid.refresh_from_db()
        self.assertEqual((kid.points_total, kid.streak), (0, 0))
        self.assertEqual(SoundMiss.objects.count(), 0)

    def test_set_goal(self):
        self.assertTrue(self.act("set_goal", goal="750")["success"])
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.class_goal, 750)
        self.assertFalse(self.act("set_goal", goal="lots")["success"])

    def test_add_switch_del_class(self):
        d = self.act("add_class", name="Room 2")
        self.assertTrue(d["success"])
        c2 = Class.objects.get(pk=d["id"])
        self.assertTrue(self.act("switch_class", class_id=self.cr.pk)["success"])
        self.assertTrue(self.act("del_class", class_id=c2.pk)["success"])
        d = self.act("del_class", class_id=self.cr.pk)
        self.assertEqual(d["message"], "Cannot delete last class")

    def test_switch_to_foreign_class_rejected(self):
        other = User.objects.create_user("other", password="pw")
        theirs = Class.objects.create(teacher=other, name="Not mine")
        self.assertFalse(self.act("switch_class", class_id=theirs.pk)["success"])


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class SoundManagementTests(DashboardBase):
    def _wav(self):
        return SimpleUploadedFile("take.wav", b"RIFFdata", "audio/wav")

    def test_upload_sound_runs_cleanup_pipeline(self):
        with patch("game.audio.clean_audio",
                   return_value=(b"CLEAN", "mp3")) as m:
            d = self.act("upload_sound", grapheme="sh", audio=self._wav())
        self.assertTrue(d["success"])
        m.assert_called_once()
        obj = GraphemeSound.objects.get(classroom=self.cr, grapheme="SH")
        self.assertEqual(obj.source, "custom")
        self.assertEqual(obj.audio.read(), b"CLEAN")

    def test_teacher_record_grapheme_and_word(self):
        with patch("game.audio.clean_audio", return_value=(b"C", "mp3")):
            d1 = self.client.post("/teacher/record/",
                                  {"grapheme": "th", "audio": self._wav()}).json()
            d2 = self.client.post("/teacher/record/",
                                  {"word": "cat", "audio": self._wav()}).json()
        self.assertEqual(d1, {"ok": True, "grapheme": "TH"})
        self.assertEqual(d2, {"ok": True, "word": "CAT"})
        self.assertEqual(WordSound.objects.get(word="CAT").source, "custom")

    def test_teacher_record_requires_audio_and_target(self):
        r = self.client.post("/teacher/record/", {"grapheme": "th"})
        self.assertEqual(r.status_code, 400)
        with patch("game.audio.clean_audio", return_value=(b"C", "mp3")):
            r = self.client.post("/teacher/record/", {"audio": self._wav()})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "need grapheme or word")

    def test_teacher_delete(self):
        obj = GraphemeSound(classroom=self.cr, grapheme="SH", source="custom")
        obj.audio.save("x.mp3", ContentFile(b"x"), save=True)
        d = self.client.post("/teacher/delete/", {"grapheme": "sh"}).json()
        self.assertTrue(d["ok"])
        self.assertEqual(
            GraphemeSound.objects.filter(classroom=self.cr).count(), 0)

    def test_google_word_generates(self):
        Word.objects.create(classroom=self.cr, text="CAT")
        with patch("game.tts.synthesize_word", return_value=b"MP3"):
            d = self.client.post("/teacher/googleword/", {"word": "cat"}).json()
        self.assertTrue(d["success"])
        self.assertEqual(WordSound.objects.get(word="CAT").source, "google")

    def test_google_word_refuses_to_clobber_custom(self):
        Word.objects.create(classroom=self.cr, text="CAT")
        ws = WordSound(classroom=self.cr, word="CAT", source="custom")
        ws.audio.save("c.mp3", ContentFile(b"x"), save=True)
        with patch("game.tts.synthesize_word", return_value=b"MP3") as m:
            d = self.client.post("/teacher/googleword/", {"word": "cat"}).json()
        self.assertFalse(d["success"])
        m.assert_not_called()

    def test_google_word_unavailable_tts(self):
        Word.objects.create(classroom=self.cr, text="CAT")
        with patch("game.tts.synthesize_word", side_effect=RuntimeError("no")):
            r = self.client.post("/teacher/googleword/", {"word": "cat"})
        self.assertEqual(r.status_code, 503)

    def test_audio_zip_contents(self):
        g = GraphemeSound(classroom=self.cr, grapheme="SH", source="custom")
        g.audio.save("g.mp3", ContentFile(b"g"), save=True)
        w = WordSound(classroom=self.cr, word="CAT", source="google")
        w.audio.save("w.mp3", ContentFile(b"w"), save=True)
        resp = self.client.get("/teacher/audio.zip")
        self.assertEqual(resp["Content-Type"], "application/zip")
        names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
        self.assertIn("letters/SH_custom.mp3", names)
        self.assertIn("words/CAT_google.mp3", names)


class SettingsApiTests(DashboardBase):
    def _post(self, data):
        return self.client.post("/teacher/settings/", json.dumps(data),
                                content_type="application/json").json()

    def test_saves_all_settings(self):
        d = self._post({"balloon_enabled": False, "balloon_frequency": 7,
                        "boss_enabled": False, "pets_enabled": False,
                        "egg_cost": 120})
        self.assertTrue(d["success"])
        self.cr.refresh_from_db()
        self.assertFalse(self.cr.balloon_enabled)
        self.assertEqual(self.cr.balloon_frequency, 7)
        self.assertFalse(self.cr.boss_enabled)
        self.assertFalse(self.cr.pets_enabled)
        self.assertEqual(self.cr.egg_cost, 120)

    def test_clamps_ranges(self):
        self._post({"balloon_frequency": 99, "egg_cost": 1})
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.balloon_frequency, 20)
        self.assertEqual(self.cr.egg_cost, 5)

    def test_invalid_values_rejected(self):
        self.assertFalse(self._post({"balloon_frequency": "x"})["success"])
        self.assertFalse(self._post({"egg_cost": "free"})["success"])
