"""Direct unit tests for the refactored helpers, managers and model methods.

Run with: python manage.py test game.tests_units
"""
import json
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase

from game import jsonapi, phrases, tts
from game.models import BossFight, Class, GraphemeSound, Kid, SoundMiss, Word


def _classroom(**kw):
    teacher = User.objects.create_user(kw.pop("username", "teach"), password="pw")
    return Class.objects.create(teacher=teacher, name=kw.pop("name", "C1"), **kw)


class JsonApiHelperTests(TestCase):
    rf = RequestFactory()

    def _req(self, body):
        return self.rf.post("/x/", data=body, content_type="application/json")

    def test_json_body_valid(self):
        req = self._req(json.dumps({"a": 1}))
        self.assertEqual(jsonapi.json_body(req), {"a": 1})

    def test_json_body_empty_and_malformed(self):
        self.assertEqual(jsonapi.json_body(self._req("")), {})
        self.assertEqual(jsonapi.json_body(self._req("{nope")), {})

    def test_parse_int(self):
        self.assertEqual(jsonapi.parse_int("7"), 7)
        self.assertIsNone(jsonapi.parse_int("x"))
        self.assertIsNone(jsonapi.parse_int(None))
        self.assertEqual(jsonapi.parse_int("x", default=3), 3)

    def test_clamp_int(self):
        self.assertEqual(jsonapi.clamp_int("100", 0, 50), 50)
        self.assertEqual(jsonapi.clamp_int(-5, 0, 50), 0)
        self.assertEqual(jsonapi.clamp_int("17", 0, 50), 17)
        self.assertEqual(jsonapi.clamp_int("junk", 0, 50, default=9), 9)

    def test_upper_param(self):
        self.assertEqual(jsonapi.upper_param("  sh ", 8), "SH")
        self.assertEqual(jsonapi.upper_param(None, 8), "")
        self.assertEqual(jsonapi.upper_param("abcdefghij", 4), "ABCD")

    def test_response_dialects(self):
        ok = json.loads(jsonapi.json_ok(x=1).content)
        self.assertEqual(ok, {"ok": True, "x": 1})
        fail = jsonapi.json_fail("bad", status=403)
        self.assertEqual(fail.status_code, 403)
        self.assertEqual(json.loads(fail.content), {"ok": False, "error": "bad"})
        t_ok = json.loads(jsonapi.teacher_ok("done", id=2).content)
        self.assertEqual(t_ok, {"success": True, "message": "done", "id": 2})
        t_fail = jsonapi.teacher_fail("nope")
        self.assertEqual(t_fail.status_code, 200)
        self.assertEqual(json.loads(t_fail.content),
                         {"success": False, "message": "nope"})

    def test_nonce_session_key_format_is_stable(self):
        """Session key format must not change: live sessions depend on it."""
        kid = Kid.objects.create(classroom=_classroom(), name="A", pin="1234")
        self.assertEqual(jsonapi.nonce_session_key("balloon", kid, "n1"),
                         f"balloon_nonce_{kid.pk}_n1")
        self.assertEqual(jsonapi.nonce_session_key("egg", kid, "n2"),
                         f"egg_nonce_{kid.pk}_n2")


class KidScoringTests(TestCase):
    def setUp(self):
        self.kid = Kid.objects.create(classroom=_classroom(), name="A", pin="1234")

    def test_award_points_totals(self):
        self.kid.award_points(10)
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_total, 10)
        self.assertEqual(self.kid.points_week, 10)

    def test_first_play_starts_streak(self):
        self.kid.award_points(5)
        self.assertEqual(self.kid.streak, 1)
        self.assertEqual(self.kid.last_played, date.today())

    def test_consecutive_day_increments_streak(self):
        self.kid.streak = 3
        self.kid.last_played = date.today() - timedelta(days=1)
        self.kid.award_points(5)
        self.assertEqual(self.kid.streak, 4)

    def test_gap_resets_streak(self):
        self.kid.streak = 9
        self.kid.last_played = date.today() - timedelta(days=3)
        self.kid.award_points(5)
        self.assertEqual(self.kid.streak, 1)

    def test_same_day_does_not_double_count(self):
        self.kid.award_points(5)
        self.kid.award_points(5)
        self.assertEqual(self.kid.streak, 1)

    def test_spendable_never_negative(self):
        self.kid.points_total, self.kid.points_spent = 30, 50
        self.assertEqual(self.kid.spendable, 0)
        self.kid.points_spent = 10
        self.assertEqual(self.kid.spendable, 20)

    def test_score_payload_shape(self):
        self.assertEqual(set(self.kid.score_payload()),
                         {"points_week", "points_total", "streak"})


class ClassModelTests(TestCase):
    def setUp(self):
        self.cr = _classroom()

    def test_by_code_is_case_insensitive(self):
        self.assertEqual(Class.objects.by_code(self.cr.code.lower()), self.cr)
        self.assertIsNone(Class.objects.by_code("NOPE99"))

    def test_by_code_or_first(self):
        self.assertEqual(Class.objects.by_code_or_first(None), self.cr)
        self.assertEqual(Class.objects.by_code_or_first(self.cr.code), self.cr)

    def test_version_changes_when_word_list_changes(self):
        v0 = self.cr.active_word_list_version()
        w = Word.objects.create(classroom=self.cr, text="CAT")
        v1 = self.cr.active_word_list_version()
        self.assertNotEqual(v0, v1)
        w.active = False
        w.save()
        self.assertEqual(self.cr.active_word_list_version(), v0)

    def test_active_word_texts(self):
        Word.objects.create(classroom=self.cr, text="cat")
        Word.objects.create(classroom=self.cr, text="DOG", active=False)
        self.assertEqual(self.cr.active_word_texts(), ["CAT"])

    def test_word_saves_uppercased(self):
        w = Word.objects.create(classroom=self.cr, text="  ship ")
        self.assertEqual(w.text, "SHIP")


class SoundMissManagerTests(TestCase):
    def test_record_creates_then_increments(self):
        kid = Kid.objects.create(classroom=_classroom(), name="A", pin="1234")
        SoundMiss.objects.record(kid, "SH")
        miss = SoundMiss.objects.record(kid, "SH")
        self.assertEqual(miss.count, 2)
        self.assertEqual(SoundMiss.objects.count(), 1)

    def test_trouble_sounds_orders_by_total(self):
        cr = _classroom()
        a = Kid.objects.create(classroom=cr, name="A", pin="1234")
        b = Kid.objects.create(classroom=cr, name="B", pin="1234")
        for _ in range(3):
            SoundMiss.objects.record(a, "TH")
        SoundMiss.objects.record(b, "TH")
        SoundMiss.objects.record(b, "SH")
        rows = list(SoundMiss.objects.trouble_sounds(cr))
        self.assertEqual(rows[0], {"sound": "TH", "total": 4})


class GraphemeSoundManagerTests(TestCase):
    def _sound(self, classroom, g, source):
        obj = GraphemeSound(classroom=classroom, grapheme=g, source=source)
        obj.audio.save(f"t_{g}_{source}.mp3", ContentFile(b"x"), save=True)
        return obj

    def test_custom_beats_shared_google(self):
        cr = _classroom()
        shared = self._sound(None, "SH", "google")
        custom = self._sound(cr, "SH", "custom")
        self.assertEqual(GraphemeSound.objects.playable(cr, "SH"), custom)

    def test_falls_back_to_shared(self):
        cr = _classroom()
        shared = self._sound(None, "TH", "google")
        self.assertEqual(GraphemeSound.objects.playable(cr, "TH"), shared)

    def test_google_row_of_own_class_is_not_preferred(self):
        """Per-class google rows are legacy; only custom recordings win."""
        cr = _classroom()
        self._sound(cr, "EE", "google")
        shared = self._sound(None, "EE", "google")
        self.assertEqual(GraphemeSound.objects.playable(cr, "EE"), shared)

    def test_none_when_missing(self):
        self.assertIsNone(GraphemeSound.objects.playable(_classroom(), "ZZ"))

    def test_shared_graphemes(self):
        self._sound(None, "AI", "google")
        self.assertIn("AI", GraphemeSound.objects.shared_graphemes())


class BossFightModelTests(TestCase):
    def setUp(self):
        self.kid = Kid.objects.create(classroom=_classroom(), name="A", pin="1234")
        self.fight = BossFight.objects.create(
            kid=self.kid, word_list_version="v1", boss_max_hp=3, boss_hp=3)

    def test_add_spelled_new_and_duplicate(self):
        self.assertTrue(self.fight.add_spelled("cat"))
        self.assertFalse(self.fight.add_spelled(" CAT "))
        self.assertEqual(self.fight.spelled_set(), {"CAT"})

    def test_spelled_set_empty(self):
        self.assertEqual(self.fight.spelled_set(), set())

    def test_summary_shape(self):
        self.fight.add_spelled("CAT")
        s = self.fight.summary()
        self.assertEqual(s["fight_id"], self.fight.pk)
        self.assertEqual(s["boss_hp"], 3)
        self.assertEqual(s["boss_max_hp"], 3)
        self.assertFalse(s["completed"])
        self.assertFalse(s["reward_claimed"])
        self.assertEqual(s["words_spelled"], ["CAT"])


class GraphemeSplitterTests(TestCase):
    def test_trigraphs_beat_digraphs(self):
        self.assertEqual(tts.split_graphemes("night"), ["N", "IGH", "T"])
        self.assertEqual(tts.split_graphemes("match"), ["M", "A", "TCH"])

    def test_digraphs(self):
        self.assertEqual(tts.split_graphemes("ship"), ["SH", "I", "P"])
        self.assertEqual(tts.split_graphemes("cat"), ["C", "A", "T"])

    def test_empty(self):
        self.assertEqual(tts.split_graphemes(""), [])
        self.assertEqual(tts.split_graphemes(None), [])


class PhraseRegistryTests(TestCase):
    def test_slugify_matches_frontend_contract(self):
        self.assertEqual(phrases.slugify("Great job!"), "great-job")
        self.assertEqual(phrases.slugify("Good try — listen again!"),
                         "good-try-listen-again")

    def test_all_phrases_covers_praise_and_balloon_hints(self):
        registry = phrases.all_phrases()
        self.assertEqual(registry["great-job"], "Great job!")
        self.assertIn("try-the-sh-balloon", registry)
        self.assertGreaterEqual(len(registry), len(phrases.PRAISE))


class PhonicSynthesisTests(TestCase):
    """The SSML sent to Google must produce phonic SOUNDS, not letter names."""

    def test_every_grapheme_has_a_respelling(self):
        missing = set(tts.GRAPHEME_IPA) - set(tts.GRAPHEME_SAY)
        self.assertEqual(missing, set())

    def test_no_respelling_is_a_bare_letter_name(self):
        # A single capital letter inside <phoneme> is what caused "ess"/"pee"
        for g, say in tts.GRAPHEME_SAY.items():
            self.assertNotEqual(say.upper(), g if len(g) == 1 else "",
                                f"{g} respelling must not be the letter itself")

    def test_synthesize_ssml_uses_ipa_and_respelling(self):
        from unittest.mock import patch
        with patch("game.tts._synth_ssml", return_value=b"MP3") as m:
            tts.synthesize("S")
        ssml = m.call_args[0][0]
        self.assertIn('ph="s\u02d0"', ssml)       # IPA "sss" phoneme
        self.assertIn(">suh<", ssml)               # tag-ignoring voices say this
        self.assertNotIn(">S<", ssml)              # never the bare letter -> "ess"

    def test_synthesize_retry_strips_length_mark_keeps_respelling(self):
        from unittest.mock import patch
        calls = []
        def fake(ssml):
            calls.append(ssml)
            if len(calls) == 1:
                raise RuntimeError("INVALID_ARGUMENT")
            return b"MP3"
        with patch("game.tts._synth_ssml", side_effect=fake):
            tts.synthesize("M")
        self.assertEqual(len(calls), 2)
        self.assertIn('ph="m"', calls[1])          # length mark stripped
        self.assertIn(">muh<", calls[1])
        self.assertIn('prosody rate="60%"', calls[1])

    def test_default_voice_supports_phonemes(self):
        self.assertTrue(tts.voice_supports_phonemes(tts.VOICE_NAME))
        for bad in ("en-US-Neural2-F", "en-US-Studio-O", "en-US-Journey-D"):
            self.assertFalse(tts.voice_supports_phonemes(bad), bad)
        for good in ("en-US-Wavenet-F", "en-GB-Standard-A"):
            self.assertTrue(tts.voice_supports_phonemes(good), good)
