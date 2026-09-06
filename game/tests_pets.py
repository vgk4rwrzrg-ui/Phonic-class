"""
Tests for the pet egg shop.
Run with: python manage.py test game.tests_pets
"""
import io
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from game import pets as petgen
from game.models import Class, Kid, Pet


def _setup(points=100, pets_enabled=True, egg_cost=50):
    teacher = User.objects.create_user("teach", password="pw")
    cr = Class.objects.create(teacher=teacher, name="C1",
                              pets_enabled=pets_enabled, egg_cost=egg_cost)
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


def _png_bytes(size=(300, 300)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 150, 255)).save(buf, "PNG")
    return buf.getvalue()


class BlueprintTests(TestCase):
    def test_42_traits(self):
        bp = petgen.new_pet_blueprint()
        self.assertEqual(len(bp["traits"]), 42)

    def test_prompt_grounding(self):
        bp = petgen.new_pet_blueprint()
        for phrase in ("G-rated", "satanic", "no weapons", "kid-friendly"):
            self.assertIn(phrase, bp["prompt"])

    def test_five_short_phrases(self):
        bp = petgen.new_pet_blueprint()
        self.assertEqual(len(bp["phrases"]), 5)
        for p in bp["phrases"]:
            self.assertLessEqual(len(p), 6)

    def test_voice_shape(self):
        v = petgen.new_pet_blueprint()["voice"]
        self.assertIn("voice_name", v)
        self.assertGreaterEqual(v["pitch"], 4.0)


class BuyEggTests(TestCase):
    def test_buy_deducts_points(self):
        _, cr, kid = _setup(points=100, egg_cost=50)
        _login(self.client, kid)
        resp = _post(self.client, "/api/pet/buy/", {"nonce": "n1"})
        d = resp.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["spendable"], 50)
        self.assertEqual(Pet.objects.filter(kid=kid).count(), 1)
        self.assertFalse(Pet.objects.get(kid=kid).hatched)

    def test_not_enough_points(self):
        _, cr, kid = _setup(points=10, egg_cost=50)
        _login(self.client, kid)
        resp = _post(self.client, "/api/pet/buy/", {"nonce": "n1"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "not_enough_points")
        self.assertEqual(Pet.objects.count(), 0)

    def test_duplicate_nonce_buys_once(self):
        _, cr, kid = _setup(points=200, egg_cost=50)
        _login(self.client, kid)
        _post(self.client, "/api/pet/buy/", {"nonce": "same"})
        resp = _post(self.client, "/api/pet/buy/", {"nonce": "same"})
        self.assertTrue(resp.json().get("duplicate"))
        self.assertEqual(Pet.objects.filter(kid=kid).count(), 1)
        kid.refresh_from_db()
        self.assertEqual(kid.points_spent, 50)

    def test_disabled(self):
        _, cr, kid = _setup(pets_enabled=False)
        _login(self.client, kid)
        resp = _post(self.client, "/api/pet/buy/", {"nonce": "x"})
        self.assertEqual(resp.status_code, 403)

    def test_requires_login(self):
        resp = _post(self.client, "/api/pet/buy/", {"nonce": "x"})
        self.assertEqual(resp.status_code, 403)


class HatchTests(TestCase):
    def _egg(self, kid):
        bp = petgen.new_pet_blueprint()
        return Pet.objects.create(
            kid=kid, name=bp["name"], traits_json=json.dumps(bp["traits"]),
            prompt=bp["prompt"], phrases_json=json.dumps(bp["phrases"]),
            voice_json=json.dumps(bp["voice"]))

    def test_hatch_no_api_key(self):
        _, cr, kid = _setup()
        pet = self._egg(kid)
        _login(self.client, kid)
        with patch.dict("os.environ", {"DEEPAI_API_KEY": ""}):
            resp = _post(self.client, f"/api/pet/hatch/{pet.pk}/")
        self.assertEqual(resp.status_code, 503)
        pet.refresh_from_db()
        self.assertFalse(pet.hatched)

    def test_hatch_success_and_image_512(self):
        _, cr, kid = _setup()
        pet = self._egg(kid)
        _login(self.client, kid)
        with patch("game.views._deepai_generate", return_value=_png_bytes()):
            resp = _post(self.client, f"/api/pet/hatch/{pet.pk}/")
        d = resp.json()
        self.assertTrue(d["ok"])
        pet.refresh_from_db()
        self.assertTrue(pet.hatched)
        from django.conf import settings
        import os as _os
        from PIL import Image
        path = _os.path.join(settings.MEDIA_ROOT, pet.image_path)
        self.assertTrue(_os.path.exists(path))
        self.assertEqual(Image.open(path).size, (512, 512))

    def test_hatch_idempotent(self):
        _, cr, kid = _setup()
        pet = self._egg(kid)
        _login(self.client, kid)
        with patch("game.views._deepai_generate", return_value=_png_bytes()) as m:
            _post(self.client, f"/api/pet/hatch/{pet.pk}/")
            resp = _post(self.client, f"/api/pet/hatch/{pet.pk}/")
            self.assertEqual(m.call_count, 1)
        self.assertTrue(resp.json().get("duplicate"))

    def test_cannot_hatch_other_kids_egg(self):
        _, cr, kid = _setup()
        other = Kid.objects.create(classroom=cr, name="Bob", pin="0000")
        pet = self._egg(other)
        _login(self.client, kid)
        resp = _post(self.client, f"/api/pet/hatch/{pet.pk}/")
        self.assertEqual(resp.status_code, 404)


class CompanionTests(TestCase):
    def _hatched(self, kid, name="Bibi"):
        bp = petgen.new_pet_blueprint()
        return Pet.objects.create(
            kid=kid, name=name, traits_json=json.dumps(bp["traits"]),
            prompt=bp["prompt"], phrases_json=json.dumps(bp["phrases"]),
            voice_json=json.dumps(bp["voice"]), hatched=True,
            image_path="pets/x.png")

    def test_only_one_companion(self):
        _, cr, kid = _setup()
        p1, p2 = self._hatched(kid, "A"), self._hatched(kid, "B")
        _login(self.client, kid)
        _post(self.client, f"/api/pet/companion/{p1.pk}/")
        _post(self.client, f"/api/pet/companion/{p2.pk}/")
        self.assertEqual(kid.pets.filter(is_companion=True).count(), 1)
        self.assertTrue(Pet.objects.get(pk=p2.pk).is_companion)

    def test_egg_cannot_be_companion(self):
        _, cr, kid = _setup()
        bp = petgen.new_pet_blueprint()
        egg = Pet.objects.create(
            kid=kid, name="E", traits_json="{}", prompt="p",
            phrases_json="[]", voice_json="{}")
        _login(self.client, kid)
        resp = _post(self.client, f"/api/pet/companion/{egg.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_companion_in_game_config(self):
        _, cr, kid = _setup()
        p = self._hatched(kid, "Zumo")
        p.is_companion = True
        p.save()
        _login(self.client, kid)
        resp = self.client.get("/play/")
        self.assertContains(resp, "Zumo")


class SoundAndPageTests(TestCase):
    def test_pet_sound_bad_index(self):
        _, cr, kid = _setup()
        bp = petgen.new_pet_blueprint()
        pet = Pet.objects.create(
            kid=kid, name="X", traits_json=json.dumps(bp["traits"]),
            prompt="p", phrases_json=json.dumps(bp["phrases"]),
            voice_json=json.dumps(bp["voice"]))
        _login(self.client, kid)
        resp = self.client.get(f"/petsound/{pet.pk}/9/")
        self.assertEqual(resp.status_code, 404)

    def test_pet_sound_forbidden_other_class(self):
        _, cr, kid = _setup()
        t2 = User.objects.create_user("t2", password="pw")
        cr2 = Class.objects.create(teacher=t2, name="C2")
        stranger = Kid.objects.create(classroom=cr2, name="Eve", pin="9999")
        bp = petgen.new_pet_blueprint()
        pet = Pet.objects.create(
            kid=kid, name="X", traits_json=json.dumps(bp["traits"]),
            prompt="p", phrases_json=json.dumps(bp["phrases"]),
            voice_json=json.dumps(bp["voice"]))
        _login(self.client, stranger)
        resp = self.client.get(f"/petsound/{pet.pk}/0/")
        self.assertEqual(resp.status_code, 403)

    def test_pet_page_renders(self):
        _, cr, kid = _setup()
        _login(self.client, kid)
        resp = self.client.get("/pets/")
        self.assertContains(resp, "Buy egg")

    def test_teacher_settings_pets(self):
        teacher, cr, kid = _setup()
        self.client.force_login(teacher)
        resp = _post(self.client, "/teacher/settings/",
                     {"pets_enabled": False, "egg_cost": 75})
        self.assertTrue(resp.json()["success"])
        cr.refresh_from_db()
        self.assertFalse(cr.pets_enabled)
        self.assertEqual(cr.egg_cost, 75)
