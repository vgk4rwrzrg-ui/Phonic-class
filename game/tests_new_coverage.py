"""
Additional tests covering: dispatch_hatch thread fallback, build_audio_zip
streaming, PIN throttle, HD egg purchase, and correct pet_services patch paths.

Run with: python manage.py test game.tests_new_coverage
"""
import io
import json
import zipfile
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase

from game.models import Class, Kid, Pet, GraphemeSound, WordSound


# ---------------------------------------------------------------------------
# Helpers shared across suites
# ---------------------------------------------------------------------------

def _setup(points=200, pets_enabled=True, egg_cost=50, hd_cost=200):
    teacher = User.objects.create_user("teach", password="pw")
    cr = Class.objects.create(
        teacher=teacher, name="C1",
        pets_enabled=pets_enabled, egg_cost=egg_cost, hd_cost=hd_cost,
    )
    kid = Kid.objects.create(classroom=cr, name="Alice", pin="1234",
                             points_total=points)
    return teacher, cr, kid


def _login(client, kid):
    s = client.session
    s["classroom_id"] = kid.classroom.pk
    s["kid_id"] = kid.pk
    s.save()


def _post(client, url, data=None):
    return client.post(url, data=json.dumps(data or {}),
                       content_type="application/json")


def _png_bytes(size=(100, 100)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, (200, 150, 255))
    d = ImageDraw.Draw(im)
    d.ellipse([10, 10, 90, 90], fill=(40, 90, 200))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# dispatch_hatch thread fallback
# ---------------------------------------------------------------------------

class DispatchHatchFallbackTests(TestCase):
    """When Celery is unavailable, dispatch_hatch falls back to a thread that
    calls game.tasks._do_hatch directly.  We test the thread target function
    in isolation (synchronously) to avoid patch-teardown-before-thread races."""

    def _make_pet(self, points=500):
        _, cr, kid = _setup(points=points)
        return Pet.objects.create(
            kid=kid, name="Fluffik",
            traits_json="{}", prompt="cute pet",
            phrases_json="[]", voice_json="{}",
        )

    def test_thread_target_calls_do_hatch(self):
        """The inner _thread_hatch closure must call _do_hatch with the Pet."""
        import threading
        import unittest.mock as mock
        pet = self._make_pet()
        spawned_threads = []
        calls = []

        def fake_do_hatch(p):
            calls.append(p.pk)
            p.set_hatch_status("complete", hatched=True, image_path="pets/x.png")

        class SyncThread:
            """Runs the target inline instead of in a real thread."""
            def __init__(self, target, daemon=False):
                self._target = target
            def start(self):
                self._target()

        with mock.patch("game.tasks.hatch_pet_task.apply_async",
                        side_effect=Exception("no broker")):
            with mock.patch("game.tasks._do_hatch", side_effect=fake_do_hatch):
                with mock.patch("game.pet_services.threading.Thread",
                                side_effect=SyncThread):
                    from game.pet_services import dispatch_hatch
                    dispatch_hatch(pet)

        self.assertEqual(calls, [pet.pk])

    def test_thread_target_marks_failed_on_crash(self):
        """If _do_hatch raises, the catch block in _thread_hatch sets 'failed'."""
        import unittest.mock as mock
        pet = self._make_pet()

        class SyncThread:
            def __init__(self, target, daemon=False):
                self._target = target
            def start(self):
                self._target()

        with mock.patch("game.tasks.hatch_pet_task.apply_async",
                        side_effect=Exception("no broker")):
            with mock.patch("game.tasks._do_hatch",
                            side_effect=RuntimeError("boom")):
                with mock.patch("game.pet_services.threading.Thread",
                                side_effect=SyncThread):
                    from game.pet_services import dispatch_hatch
                    dispatch_hatch(pet)

        pet.refresh_from_db()
        self.assertEqual(pet.hatch_status, "failed")

    def test_dispatch_uses_celery_when_available(self):
        """When apply_async succeeds, no thread is started."""
        import unittest.mock as mock
        pet = self._make_pet()
        fake_result = mock.MagicMock()
        fake_result.id = "task-abc"

        with mock.patch("game.tasks.hatch_pet_task.apply_async",
                        return_value=fake_result) as mock_async:
            with mock.patch("game.pet_services.threading.Thread") as mock_thread:
                from game.pet_services import dispatch_hatch
                dispatch_hatch(pet)

        mock_async.assert_called_once_with(args=[pet.pk])
        mock_thread.assert_not_called()


# ---------------------------------------------------------------------------
# HD egg purchase
# ---------------------------------------------------------------------------

class HdEggPurchaseTests(TestCase):
    def test_buy_hd_egg_charges_hd_cost(self):
        _, cr, kid = _setup(points=500, egg_cost=50, hd_cost=200)
        _login(self.client, kid)
        resp = _post(self.client, "/api/pet/buy/",
                     {"tier": "hd", "nonce": "hd1"})
        d = resp.json()
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["spendable"], 300)  # 500 - 200
        pet = Pet.objects.get(kid=kid)
        self.assertEqual(pet.tier, "hd")

    def test_buy_basic_egg_charges_egg_cost(self):
        _, cr, kid = _setup(points=500, egg_cost=50, hd_cost=200)
        _login(self.client, kid)
        resp = _post(self.client, "/api/pet/buy/",
                     {"tier": "basic", "nonce": "b1"})
        d = resp.json()
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["spendable"], 450)  # 500 - 50
        pet = Pet.objects.get(kid=kid)
        self.assertEqual(pet.tier, "basic")

    def test_hd_egg_insufficient_points(self):
        _, cr, kid = _setup(points=100, egg_cost=50, hd_cost=200)
        _login(self.client, kid)
        resp = _post(self.client, "/api/pet/buy/",
                     {"tier": "hd", "nonce": "hd2"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "not_enough_points")
        self.assertEqual(Pet.objects.count(), 0)

    def test_hd_blueprint_has_human_sayings(self):
        from game.pets import new_pet_blueprint
        bp = new_pet_blueprint(is_hd=True)
        self.assertEqual(len(bp["human_sayings"]), 5)
        self.assertTrue(all(isinstance(s, str) for s in bp["human_sayings"]))

    def test_basic_blueprint_has_no_human_sayings(self):
        from game.pets import new_pet_blueprint
        bp = new_pet_blueprint(is_hd=False)
        self.assertEqual(bp["human_sayings"], [])

    def test_pet_dict_exposes_tier_and_human_sayings(self):
        _, cr, kid = _setup(points=500, hd_cost=200)
        _login(self.client, kid)
        _post(self.client, "/api/pet/buy/", {"tier": "hd", "nonce": "hd3"})
        pet = Pet.objects.get(kid=kid)
        from game.pet_services import pet_dict
        d = pet_dict(pet)
        self.assertEqual(d["tier"], "hd")
        self.assertIsInstance(d["human_sayings"], list)


# ---------------------------------------------------------------------------
# build_audio_zip streaming
# ---------------------------------------------------------------------------

class AudioZipTests(TestCase):
    def _make_class_with_sounds(self):
        teacher = User.objects.create_user("zteach", password="pw")
        cr = Class.objects.create(teacher=teacher, name="ZC")
        # Add a shared grapheme sound
        gs = GraphemeSound(classroom=None, grapheme="SH", source="google")
        gs.audio.save("shared_sh.mp3", ContentFile(b"SH_AUDIO"), save=True)
        # Add a custom word sound
        ws = WordSound(classroom=cr, word="SHIP", source="custom")
        ws.audio.save("ship.mp3", ContentFile(b"SHIP_AUDIO"), save=True)
        return cr

    def test_zip_contains_expected_entries(self):
        cr = self._make_class_with_sounds()
        from game.sound_services import build_audio_zip
        buf = build_audio_zip(cr)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        self.assertTrue(any("SH" in n for n in names), names)
        self.assertTrue(any("SHIP" in n for n in names), names)

    def test_zip_is_valid_and_contains_correct_bytes(self):
        cr = self._make_class_with_sounds()
        from game.sound_services import build_audio_zip
        buf = build_audio_zip(cr)
        with zipfile.ZipFile(buf) as zf:
            for name in zf.namelist():
                if "SH" in name and "SHIP" not in name:
                    self.assertEqual(zf.read(name), b"SH_AUDIO")
                if "SHIP" in name:
                    self.assertEqual(zf.read(name), b"SHIP_AUDIO")

    def test_zip_skips_missing_files_gracefully(self):
        """A missing audio file on disk must not crash the zip build."""
        teacher = User.objects.create_user("zteach2", password="pw")
        cr = Class.objects.create(teacher=teacher, name="ZC2")
        # Create a DB row pointing to a file that doesn't exist
        ws = WordSound.objects.create(
            classroom=cr, word="GHOST", source="google",
            audio="word_sounds/nonexistent.mp3"
        )
        from game.sound_services import build_audio_zip
        buf = build_audio_zip(cr)  # should not raise
        self.assertIsNotNone(buf)


# ---------------------------------------------------------------------------
# PIN throttle
# ---------------------------------------------------------------------------

class PinThrottleTests(TestCase):
    def setUp(self):
        teacher = User.objects.create_user("pteach", password="pw")
        self.cr = Class.objects.create(teacher=teacher, name="PC")
        self.kid = Kid.objects.create(
            classroom=self.cr, name="Bob", pin="9999")
        s = self.client.session
        s["classroom_id"] = self.cr.pk
        s.save()

    def _attempt_pin(self, pin):
        return self.client.post("/picker/", {
            "kid_id": self.kid.pk,
            "pin": pin,
        })

    def test_correct_pin_succeeds(self):
        resp = self._attempt_pin("9999")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("kid_id", self.client.session)

    def test_wrong_pin_returns_error(self):
        resp = self._attempt_pin("0000")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "wrong PIN")

    def test_lockout_after_max_attempts(self):
        from game.views.kids import _MAX_PIN_ATTEMPTS
        for _ in range(_MAX_PIN_ATTEMPTS):
            self._attempt_pin("0000")
        # Next attempt (even with correct PIN) should be locked out
        resp = self._attempt_pin("9999")
        self.assertContains(resp, "Too many")

    def test_lockout_clears_on_success(self):
        """A successful login clears the failure counter."""
        from game.views.kids import _MAX_PIN_ATTEMPTS
        for _ in range(_MAX_PIN_ATTEMPTS - 1):
            self._attempt_pin("0000")
        # Correct PIN should succeed and reset the counter
        resp = self._attempt_pin("9999")
        self.assertEqual(resp.status_code, 302)
        # One more wrong attempt should NOT be locked out
        self.client.get("/bye/")  # log out
        resp2 = self._attempt_pin("0000")
        self.assertNotContains(resp2, "Too many")


# ---------------------------------------------------------------------------
# Patch path integrity: tasks import from pet_services, not game.views
# ---------------------------------------------------------------------------

class PatchPathIntegrityTests(TestCase):
    def test_tasks_import_generate_pet_image_from_pet_services(self):
        """The task must resolve generate_pet_image from pet_services so tests
        can patch game.pet_services.generate_pet_image without going through
        game.views."""
        import game.tasks as tasks_mod
        import inspect
        src = inspect.getsource(tasks_mod._generate_image)
        self.assertIn("from game.pet_services import generate_pet_image", src)
        self.assertNotIn("game.views", src)

    def test_tasks_import_looks_blank_from_pet_services(self):
        import game.tasks as tasks_mod
        import inspect
        src = inspect.getsource(tasks_mod._do_hatch)
        self.assertIn("from game.pet_services import looks_blank", src)
        self.assertNotIn("game.views", src)
