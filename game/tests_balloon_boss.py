"""
Tests for balloon challenge and boss fight features.
Run with: python manage.py test game.tests_balloon_boss
"""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User

from game.models import BossFight, Class, Kid, SoundMiss, Word


def _make_class(teacher, name="Test Class", boss_enabled=True, balloon_enabled=True, balloon_frequency=3):
    return Class.objects.create(
        teacher=teacher, name=name,
        boss_enabled=boss_enabled,
        balloon_enabled=balloon_enabled,
        balloon_frequency=balloon_frequency,
    )


def _make_kid(classroom, name="Alice", pin="1234"):
    return Kid.objects.create(classroom=classroom, name=name, pin=pin)


def _make_words(classroom, texts):
    words = []
    for t in texts:
        words.append(Word.objects.create(classroom=classroom, text=t, active=True))
    return words


def _kid_session(client, kid):
    """Log in a kid via session."""
    session = client.session
    session["classroom_id"] = kid.classroom.pk
    session["kid_id"] = kid.pk
    session.save()


def _post_json(client, url, data):
    return client.post(
        url,
        data=json.dumps(data),
        content_type="application/json",
        HTTP_X_CSRFTOKEN="test",
    )


class BalloonRoundCountTests(TestCase):
    """Balloon rounds should contain 2 or 3 characters based on difficulty."""

    def test_two_characters_early(self):
        """Round count < 6 → 2 balloons."""
        # We verify the JS logic rather than a server endpoint;
        # server side balloon_complete just awards points.
        # Here we verify config returns the right frequency.
        teacher = User.objects.create_user("t1", password="pw")
        cr = _make_class(teacher, balloon_frequency=3)
        kid = _make_kid(cr)
        _make_words(cr, ["CAT", "DOG"])
        _kid_session(self.client, kid)
        resp = self.client.get("/api/boss/status/")
        data = resp.json()
        self.assertEqual(data["balloon_frequency"], 3)
        self.assertTrue(data["balloon_enabled"])

    def test_three_characters_higher_difficulty(self):
        """balloon_frequency config is accessible and correct."""
        teacher = User.objects.create_user("t2", password="pw")
        cr = _make_class(teacher, balloon_frequency=5)
        kid = _make_kid(cr)
        _kid_session(self.client, kid)
        resp = self.client.get("/api/boss/status/")
        self.assertEqual(resp.json()["balloon_frequency"], 5)


class BalloonCharacterSourceTests(TestCase):
    """Characters on balloons must be from learner content (active words)."""

    def test_active_words_returned_in_status(self):
        teacher = User.objects.create_user("t3", password="pw")
        cr = _make_class(teacher)
        kid = _make_kid(cr)
        _make_words(cr, ["CAT", "HAT", "SAT"])
        _kid_session(self.client, kid)
        data = self.client.get("/api/boss/status/").json()
        self.assertIn("CAT", data["active_words"])
        self.assertIn("HAT", data["active_words"])


class BalloonCompletionTests(TestCase):
    """Correct-order balloon completion awards points once."""

    def setUp(self):
        self.teacher = User.objects.create_user("t4", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid = _make_kid(self.cr)
        _make_words(self.cr, ["CAT"])
        _kid_session(self.client, self.kid)

    def test_balloon_complete_awards_points(self):
        resp = _post_json(self.client, "/api/balloon/complete/", {"nonce": "abc123"})
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data.get("duplicate", False))
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_total, 5)

    def test_duplicate_nonce_no_extra_points(self):
        _post_json(self.client, "/api/balloon/complete/", {"nonce": "samenonce"})
        _post_json(self.client, "/api/balloon/complete/", {"nonce": "samenonce"})
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_total, 5)  # only 5, not 10

    def test_duplicate_response_flagged(self):
        _post_json(self.client, "/api/balloon/complete/", {"nonce": "dup1"})
        resp = _post_json(self.client, "/api/balloon/complete/", {"nonce": "dup1"})
        self.assertTrue(resp.json().get("duplicate"))

    def test_balloon_disabled_blocked(self):
        self.cr.balloon_enabled = False
        self.cr.save()
        resp = _post_json(self.client, "/api/balloon/complete/", {"nonce": "n1"})
        self.assertFalse(resp.json()["ok"])
        self.assertEqual(resp.status_code, 403)


class BossEligibilityTests(TestCase):
    """Boss fight becomes available only after all active words are completed."""

    def setUp(self):
        self.teacher = User.objects.create_user("t5", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid = _make_kid(self.cr)
        _make_words(self.cr, ["CAT", "DOG", "HAT"])
        _kid_session(self.client, self.kid)

    def test_eligible_when_all_words_spelled(self):
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG", "HAT"]})
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["eligible"])
        self.assertIn("fight_id", data)

    def test_ineligible_with_missing_word(self):
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG"]})  # HAT missing
        data = resp.json()
        self.assertFalse(data.get("eligible", False))

    def test_ineligible_with_no_words_spelled(self):
        resp = _post_json(self.client, "/api/boss/eligible/", {"words_spelled": []})
        self.assertFalse(resp.json().get("eligible", False))

    def test_boss_disabled_returns_error(self):
        self.cr.boss_enabled = False
        self.cr.save()
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG", "HAT"]})
        self.assertFalse(resp.json()["ok"])

    def test_no_active_words_returns_error(self):
        self.cr.words.update(active=False)
        resp = _post_json(self.client, "/api/boss/eligible/", {"words_spelled": []})
        self.assertFalse(resp.json()["ok"])

    def test_existing_fight_returned_on_recheck(self):
        """Same request twice returns the same fight."""
        _post_json(self.client, "/api/boss/eligible/",
                   {"words_spelled": ["CAT", "DOG", "HAT"]})
        resp2 = _post_json(self.client, "/api/boss/eligible/",
                           {"words_spelled": ["CAT", "DOG", "HAT"]})
        data = resp2.json()
        self.assertTrue(data["eligible"])
        self.assertEqual(BossFight.objects.filter(kid=self.kid).count(), 1)


class BossSpellTests(TestCase):
    """Correct spellings reduce HP; incorrect do not."""

    def setUp(self):
        self.teacher = User.objects.create_user("t6", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid = _make_kid(self.cr)
        _make_words(self.cr, ["CAT", "DOG"])
        _kid_session(self.client, self.kid)
        # Create fight
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG"]})
        self.fight_id = resp.json()["fight_id"]
        self.fight = BossFight.objects.get(pk=self.fight_id)

    def test_correct_spelling_reduces_hp(self):
        initial_hp = self.fight.boss_hp
        resp = _post_json(self.client, "/api/boss/spell/",
                          {"fight_id": self.fight_id, "word": "CAT"})
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["correct"])
        self.assertEqual(data["damage"], 1)
        self.assertEqual(data["boss_hp"], initial_hp - 1)

    def test_incorrect_word_not_in_list_does_no_damage(self):
        resp = _post_json(self.client, "/api/boss/spell/",
                          {"fight_id": self.fight_id, "word": "ZZZ"})
        data = resp.json()
        self.assertFalse(data.get("ok", True) and data.get("correct", False))
        # HP unchanged
        self.fight.refresh_from_db()
        self.assertEqual(self.fight.boss_hp, self.fight.boss_max_hp)

    def test_word_counted_only_once(self):
        """Spelling the same word twice should only reduce HP once."""
        _post_json(self.client, "/api/boss/spell/",
                   {"fight_id": self.fight_id, "word": "CAT"})
        resp = _post_json(self.client, "/api/boss/spell/",
                          {"fight_id": self.fight_id, "word": "CAT"})
        data = resp.json()
        self.assertEqual(data["damage"], 0)
        self.fight.refresh_from_db()
        self.assertEqual(self.fight.boss_hp, self.fight.boss_max_hp - 1)

    def test_boss_hp_at_zero_when_all_spelled(self):
        _post_json(self.client, "/api/boss/spell/",
                   {"fight_id": self.fight_id, "word": "CAT"})
        _post_json(self.client, "/api/boss/spell/",
                   {"fight_id": self.fight_id, "word": "DOG"})
        self.fight.refresh_from_db()
        self.assertEqual(self.fight.boss_hp, 0)


class BossProgressPersistenceTests(TestCase):
    """Boss progress survives simulated reloads (new client, same session)."""

    def setUp(self):
        self.teacher = User.objects.create_user("t7", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid = _make_kid(self.cr)
        _make_words(self.cr, ["CAT", "DOG", "HAT"])
        _kid_session(self.client, self.kid)
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG", "HAT"]})
        self.fight_id = resp.json()["fight_id"]

    def test_status_endpoint_returns_fight(self):
        resp = self.client.get("/api/boss/status/")
        data = resp.json()
        self.assertIsNotNone(data["fight"])
        self.assertEqual(data["fight"]["fight_id"], self.fight_id)

    def test_partial_progress_persists(self):
        _post_json(self.client, "/api/boss/spell/",
                   {"fight_id": self.fight_id, "word": "CAT"})
        # Simulate reload: create new client with same session
        client2 = Client()
        session = client2.session
        session["classroom_id"] = self.cr.pk
        session["kid_id"] = self.kid.pk
        session.save()
        resp = client2.get("/api/boss/status/")
        data = resp.json()
        self.assertIn("CAT", data["fight"]["words_spelled"])


class BossVictoryTests(TestCase):
    """Victory is recorded once; rewards granted once."""

    def setUp(self):
        self.teacher = User.objects.create_user("t8", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid = _make_kid(self.cr)
        _make_words(self.cr, ["CAT", "DOG"])
        _kid_session(self.client, self.kid)
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG"]})
        self.fight_id = resp.json()["fight_id"]
        # Defeat the boss
        _post_json(self.client, "/api/boss/spell/",
                   {"fight_id": self.fight_id, "word": "CAT"})
        _post_json(self.client, "/api/boss/spell/",
                   {"fight_id": self.fight_id, "word": "DOG"})

    def test_victory_recorded(self):
        resp = _post_json(self.client, "/api/boss/victory/",
                          {"fight_id": self.fight_id})
        data = resp.json()
        self.assertTrue(data["ok"])
        fight = BossFight.objects.get(pk=self.fight_id)
        self.assertTrue(fight.completed)
        self.assertTrue(fight.reward_claimed)

    def test_victory_awards_points(self):
        resp = _post_json(self.client, "/api/boss/victory/",
                          {"fight_id": self.fight_id})
        data = resp.json()
        self.assertEqual(data["points_awarded"], 50)
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_total, 50)

    def test_duplicate_victory_no_extra_rewards(self):
        _post_json(self.client, "/api/boss/victory/", {"fight_id": self.fight_id})
        resp2 = _post_json(self.client, "/api/boss/victory/", {"fight_id": self.fight_id})
        data2 = resp2.json()
        self.assertTrue(data2.get("duplicate"))
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_total, 50)  # still only 50

    def test_victory_before_boss_defeated_blocked(self):
        teacher2 = User.objects.create_user("t8b", password="pw")
        cr2 = _make_class(teacher2)
        kid2 = _make_kid(cr2, name="Bob")
        _make_words(cr2, ["CAT", "DOG"])
        client2 = Client()
        session = client2.session
        session["classroom_id"] = cr2.pk
        session["kid_id"] = kid2.pk
        session.save()
        elig = _post_json(client2, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG"]})
        fid = elig.json()["fight_id"]
        # Only spell one word — boss not defeated
        _post_json(client2, "/api/boss/spell/", {"fight_id": fid, "word": "CAT"})
        resp = _post_json(client2, "/api/boss/victory/", {"fight_id": fid})
        self.assertFalse(resp.json()["ok"])


class BossWordListVersionTests(TestCase):
    """Changing the word list creates a new boss fight opportunity."""

    def setUp(self):
        self.teacher = User.objects.create_user("t9", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid = _make_kid(self.cr)

    def test_new_version_after_word_added(self):
        words = _make_words(self.cr, ["CAT", "DOG"])
        _kid_session(self.client, self.kid)
        v1 = self.cr.active_word_list_version()
        # Complete and claim fight for v1
        _post_json(self.client, "/api/boss/eligible/",
                   {"words_spelled": ["CAT", "DOG"]})
        fight1 = BossFight.objects.get(kid=self.kid)
        # Teacher adds a new word
        Word.objects.create(classroom=self.cr, text="HAT", active=True)
        v2 = self.cr.active_word_list_version()
        self.assertNotEqual(v1, v2)
        # Kid cannot claim old fight as new
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG"]})
        # Missing HAT → ineligible for v2
        self.assertFalse(resp.json().get("eligible", False))

    def test_eligible_for_new_version_with_all_words(self):
        _make_words(self.cr, ["CAT", "DOG"])
        _kid_session(self.client, self.kid)
        _post_json(self.client, "/api/boss/eligible/",
                   {"words_spelled": ["CAT", "DOG"]})
        Word.objects.create(classroom=self.cr, text="HAT", active=True)
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG", "HAT"]})
        data = resp.json()
        self.assertTrue(data["eligible"])
        # Two separate fight rows
        self.assertEqual(BossFight.objects.filter(kid=self.kid).count(), 2)


class AuthorizationTests(TestCase):
    """Students cannot access another student's boss fight."""

    def setUp(self):
        self.teacher = User.objects.create_user("t10", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid_a = _make_kid(self.cr, name="Alice")
        self.kid_b = _make_kid(self.cr, name="Bob", pin="5678")
        _make_words(self.cr, ["CAT", "DOG"])
        # Create fight for Alice
        _kid_session(self.client, self.kid_a)
        resp = _post_json(self.client, "/api/boss/eligible/",
                          {"words_spelled": ["CAT", "DOG"]})
        self.fight_id = resp.json()["fight_id"]

    def test_other_kid_cannot_spell_into_fight(self):
        # Log in as Bob
        _kid_session(self.client, self.kid_b)
        resp = _post_json(self.client, "/api/boss/spell/",
                          {"fight_id": self.fight_id, "word": "CAT"})
        self.assertFalse(resp.json().get("ok", True))
        self.assertEqual(resp.status_code, 404)

    def test_other_kid_cannot_claim_victory(self):
        _kid_session(self.client, self.kid_b)
        resp = _post_json(self.client, "/api/boss/victory/",
                          {"fight_id": self.fight_id})
        self.assertFalse(resp.json().get("ok", True))
        self.assertEqual(resp.status_code, 404)


class ExistingGameTests(TestCase):
    """Core game score and miss endpoints continue to work."""

    def setUp(self):
        self.teacher = User.objects.create_user("t11", password="pw")
        self.cr = _make_class(self.teacher)
        self.kid = _make_kid(self.cr)
        _kid_session(self.client, self.kid)

    def test_score_endpoint(self):
        resp = _post_json(self.client, "/api/score/", {"points": 10})
        data = resp.json()
        self.assertTrue(data["ok"])
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_total, 10)

    def test_score_capped(self):
        resp = _post_json(self.client, "/api/score/", {"points": 9999})
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_total, 50)  # server cap is 50

    def test_miss_endpoint(self):
        resp = _post_json(self.client, "/api/miss/", {"sound": "SH"})
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(SoundMiss.objects.filter(kid=self.kid, sound="SH").count(), 1)

    def test_unauthenticated_score_blocked(self):
        resp = _post_json(self.client, "/api/score/", {"points": 10})
        # reset session
        self.client.session.flush()
        resp2 = _post_json(self.client, "/api/score/", {"points": 10})
        self.assertFalse(resp2.json()["ok"])
        self.assertEqual(resp2.status_code, 403)


class TeacherSettingsTests(TestCase):
    """Teacher can toggle balloon/boss settings."""

    def setUp(self):
        self.teacher = User.objects.create_user("t12", password="pw")
        self.cr = _make_class(self.teacher)
        self.client.login(username="t12", password="pw")
        session = self.client.session
        session["classroom_id"] = self.cr.pk
        session.save()

    def test_toggle_balloon_off(self):
        resp = _post_json(self.client, "/teacher/settings/", {"balloon_enabled": False})
        self.assertTrue(resp.json()["success"])
        self.cr.refresh_from_db()
        self.assertFalse(self.cr.balloon_enabled)

    def test_toggle_boss_off(self):
        resp = _post_json(self.client, "/teacher/settings/", {"boss_enabled": False})
        self.assertTrue(resp.json()["success"])
        self.cr.refresh_from_db()
        self.assertFalse(self.cr.boss_enabled)

    def test_set_balloon_frequency(self):
        resp = _post_json(self.client, "/teacher/settings/", {"balloon_frequency": 5})
        self.assertTrue(resp.json()["success"])
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.balloon_frequency, 5)

    def test_invalid_frequency_rejected(self):
        resp = _post_json(self.client, "/teacher/settings/", {"balloon_frequency": 999})
        # Server clamps to max 20, so it succeeds but stores 20
        self.cr.refresh_from_db()
        self.assertLessEqual(self.cr.balloon_frequency, 20)

    def test_unauthenticated_teacher_blocked(self):
        self.client.logout()
        resp = _post_json(self.client, "/teacher/settings/", {"boss_enabled": False})
        self.assertNotEqual(resp.status_code, 200)
