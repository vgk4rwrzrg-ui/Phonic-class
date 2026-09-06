"""AJAX endpoint tests: scoring, misses, balloon, and sound serving.

External TTS and ffmpeg are always mocked.
Run with: python manage.py test game.tests_ajax_game
"""
import json
import shutil
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from game.models import Class, GraphemeSound, Kid, SoundMiss, Word, WordSound

TEMP_MEDIA = tempfile.mkdtemp(prefix="phonics_test_media_")


def _setup(**class_kw):
    teacher = User.objects.create_user("teach", password="pw")
    cr = Class.objects.create(teacher=teacher, name="C1", **class_kw)
    kid = Kid.objects.create(classroom=cr, name="Alice", pin="1234")
    return teacher, cr, kid


def _login(client, kid):
    s = client.session
    s["classroom_id"] = kid.classroom.pk
    s["kid_id"] = kid.pk
    s.save()


def _post(client, url, data=None):
    return client.post(url, data=json.dumps(data or {}),
                       content_type="application/json")


class ScoreApiTests(TestCase):
    def setUp(self):
        _, self.cr, self.kid = _setup()

    def test_requires_login(self):
        resp = _post(self.client, "/api/score/", {"points": 5})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()["ok"])

    def test_requires_post(self):
        _login(self.client, self.kid)
        self.assertEqual(self.client.get("/api/score/").status_code, 405)

    def test_awards_points_and_payload_shape(self):
        _login(self.client, self.kid)
        d = _post(self.client, "/api/score/", {"points": 7}).json()
        self.assertEqual(d, {"ok": True, "points_week": 7,
                             "points_total": 7, "streak": 1})

    def test_clamps_high_and_negative(self):
        _login(self.client, self.kid)
        self.assertEqual(_post(self.client, "/api/score/",
                               {"points": 9999}).json()["points_total"], 50)
        d = _post(self.client, "/api/score/", {"points": -20}).json()
        self.assertEqual(d["points_total"], 50)  # unchanged

    def test_garbage_points_count_zero(self):
        _login(self.client, self.kid)
        d = _post(self.client, "/api/score/", {"points": "banana"}).json()
        self.assertEqual(d["points_total"], 0)
        self.assertEqual(d["streak"], 1)  # still counts as playing today

    def test_streak_continues_from_yesterday(self):
        self.kid.streak = 4
        self.kid.last_played = date.today() - timedelta(days=1)
        self.kid.save()
        _login(self.client, self.kid)
        d = _post(self.client, "/api/score/", {"points": 1}).json()
        self.assertEqual(d["streak"], 5)


class MissApiTests(TestCase):
    def setUp(self):
        _, self.cr, self.kid = _setup()

    def test_requires_login(self):
        self.assertEqual(_post(self.client, "/api/miss/",
                               {"sound": "SH"}).status_code, 403)

    def test_records_and_increments(self):
        _login(self.client, self.kid)
        _post(self.client, "/api/miss/", {"sound": "sh"})
        _post(self.client, "/api/miss/", {"sound": "SH"})
        miss = SoundMiss.objects.get(kid=self.kid)
        self.assertEqual((miss.sound, miss.count), ("SH", 2))

    def test_blank_sound_ignored(self):
        _login(self.client, self.kid)
        d = _post(self.client, "/api/miss/", {"sound": "  "}).json()
        self.assertTrue(d["ok"])
        self.assertEqual(SoundMiss.objects.count(), 0)

    def test_sound_truncated_to_12(self):
        _login(self.client, self.kid)
        _post(self.client, "/api/miss/", {"sound": "abcdefghijklmnop"})
        self.assertEqual(SoundMiss.objects.get(kid=self.kid).sound,
                         "ABCDEFGHIJKL")


class BalloonApiTests(TestCase):
    def test_awards_five_points(self):
        _, cr, kid = _setup()
        _login(self.client, kid)
        d = _post(self.client, "/api/balloon/complete/", {"nonce": "n1"}).json()
        self.assertEqual(d["points_total"], 5)

    def test_duplicate_nonce_awards_once(self):
        _, cr, kid = _setup()
        _login(self.client, kid)
        _post(self.client, "/api/balloon/complete/", {"nonce": "same"})
        d = _post(self.client, "/api/balloon/complete/", {"nonce": "same"}).json()
        self.assertTrue(d["duplicate"])
        kid.refresh_from_db()
        self.assertEqual(kid.points_total, 5)

    def test_disabled_class(self):
        _, cr, kid = _setup(balloon_enabled=False)
        _login(self.client, kid)
        resp = _post(self.client, "/api/balloon/complete/", {"nonce": "x"})
        self.assertEqual(resp.status_code, 403)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class SoundEndpointTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        _, self.cr, self.kid = _setup()
        _login(self.client, self.kid)

    def test_requires_session(self):
        self.client.session.flush()
        c = self.client.__class__()
        self.assertEqual(c.get("/sound/S/").status_code, 403)

    def test_synthesizes_and_caches_shared_sound(self):
        with patch("game.tts.synthesize", return_value=b"MP3") as m:
            r1 = self.client.get("/sound/S/")
            r2 = self.client.get("/sound/S/")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(b"".join(r1.streaming_content), b"MP3")
        self.assertEqual(m.call_count, 1)  # second hit came from the cache
        row = GraphemeSound.objects.get(grapheme="S")
        self.assertIsNone(row.classroom)
        self.assertEqual(row.source, "google")

    def test_custom_recording_wins(self):
        from django.core.files.base import ContentFile
        obj = GraphemeSound(classroom=self.cr, grapheme="M", source="custom")
        obj.audio.save("m.mp3", ContentFile(b"TEACHER"), save=True)
        with patch("game.tts.synthesize", return_value=b"GOOGLE") as m:
            r = self.client.get("/sound/M/")
        self.assertEqual(b"".join(r.streaming_content), b"TEACHER")
        m.assert_not_called()

    def test_tts_failure_returns_503(self):
        with patch("game.tts.synthesize", side_effect=RuntimeError("no creds")):
            r = self.client.get("/sound/Q/")
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.json()["ok"])

    def test_word_sound_rejects_foreign_words(self):
        """Kids must not be able to spend TTS quota on arbitrary text."""
        with patch("game.tts.synthesize_word", return_value=b"X") as m:
            r = self.client.get("/wordsound/HACK/")
        self.assertEqual(r.status_code, 404)
        m.assert_not_called()

    def test_word_sound_synthesizes_class_word(self):
        Word.objects.create(classroom=self.cr, text="CAT")
        with patch("game.tts.synthesize_word", return_value=b"CATMP3") as m:
            r1 = self.client.get("/wordsound/CAT/")
            r2 = self.client.get("/wordsound/CAT/")
        self.assertEqual(b"".join(r1.streaming_content), b"CATMP3")
        self.assertEqual(m.call_count, 1)
        self.assertEqual(WordSound.objects.get(classroom=self.cr,
                                               word="CAT").source, "google")

    def test_word_sound_tts_failure_404s_for_browser_fallback(self):
        Word.objects.create(classroom=self.cr, text="DOG")
        with patch("game.tts.synthesize_word", side_effect=RuntimeError("x")):
            r = self.client.get("/wordsound/DOG/")
        self.assertEqual(r.status_code, 404)

    def test_phrase_unknown_slug_404(self):
        self.assertEqual(self.client.get("/phrase/not-a-thing/").status_code,
                         404)

    def test_phrase_generates_and_caches(self):
        with patch("game.tts.synthesize_phrase", return_value=b"YAY") as m:
            r1 = self.client.get("/phrase/great-job/")
            r2 = self.client.get("/phrase/great-job/")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(b"".join(r1.streaming_content), b"YAY")
        self.assertEqual(m.call_count, 1)

    def test_phrase_tts_failure_404s(self):
        with patch("game.tts.synthesize_phrase",
                   side_effect=RuntimeError("no creds")):
            r = self.client.get("/phrase/you-did-it/")
        self.assertEqual(r.status_code, 404)
