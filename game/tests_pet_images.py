"""Pet image backend + creature variety tests (all HTTP fully mocked).

Run with: python manage.py test game.tests_pet_images
"""
import base64
import random
from unittest.mock import patch

from django.test import SimpleTestCase

from game import pet_services, pets as petgen


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


class BackendDispatchTests(SimpleTestCase):
    def test_explicit_imagen_backend(self):
        img = b"PNGBYTES"
        payload = {"predictions": [{"bytesBase64Encoded":
                                    base64.b64encode(img).decode()}]}
        with patch.dict("os.environ", {"PET_IMAGE_BACKEND": "imagen",
                                       "GEMINI_API_KEY": "k"}), \
                patch("requests.post", return_value=_FakeResp(payload)) as m:
            out = pet_services.generate_pet_image("a cute baby bunny")
        self.assertEqual(out, img)
        url = m.call_args[0][0]
        self.assertIn("generativelanguage.googleapis.com", url)
        self.assertIn(pet_services.DEFAULT_IMAGEN_MODEL, url)
        self.assertEqual(m.call_args.kwargs["headers"]["x-goog-api-key"], "k")

    def test_imagen_model_env_override(self):
        payload = {"predictions": [{"bytesBase64Encoded":
                                    base64.b64encode(b"x").decode()}]}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "k",
                                       "IMAGEN_MODEL": "imagen-3.0-generate-002"}), \
                patch("requests.post", return_value=_FakeResp(payload)) as m:
            pet_services.imagen_generate("p")
        self.assertIn("imagen-3.0-generate-002:predict", m.call_args[0][0])

    def test_auto_prefers_deepai_when_its_key_is_set(self):
        """A DeepAI subscription wins in auto mode, even with a Gemini key."""
        with patch.dict("os.environ", {"DEEPAI_API_KEY": "dk",
                                       "GEMINI_API_KEY": "k",
                                       "PET_IMAGE_BACKEND": ""}), \
                patch("requests.post") as m:
            m.return_value = _FakeResp({"output_url": "http://img"})
            with patch("requests.get") as g:
                g.return_value.content = b"deepai-bytes"
                g.return_value.raise_for_status = lambda: None
                out = pet_services.generate_pet_image("p")
        self.assertEqual(out, b"deepai-bytes")
        self.assertIn("api.deepai.org", m.call_args[0][0])

    def test_auto_uses_imagen_only_without_deepai_key(self):
        payload = {"predictions": [{"bytesBase64Encoded":
                                    base64.b64encode(b"i").decode()}]}
        with patch.dict("os.environ", {"DEEPAI_API_KEY": "",
                                       "GEMINI_API_KEY": "k",
                                       "PET_IMAGE_BACKEND": ""}), \
                patch("requests.post", return_value=_FakeResp(payload)) as m:
            out = pet_services.generate_pet_image("p")
        self.assertEqual(out, b"i")
        self.assertIn("googleapis.com", m.call_args[0][0])

    def test_deepai_version_defaults_to_standard_tier(self):
        with patch.dict("os.environ", {"DEEPAI_API_KEY": "dk"}), \
                patch("requests.post") as m:
            m.return_value = _FakeResp({"output_url": "http://img"})
            with patch("requests.get") as g:
                g.return_value.content = b"x"
                g.return_value.raise_for_status = lambda: None
                pet_services.deepai_text2img("p")
        sent = m.call_args.kwargs["data"]
        self.assertEqual(sent["image_generator_version"], "standard")

    def test_deepai_version_env_override(self):
        with patch.dict("os.environ", {"DEEPAI_API_KEY": "dk",
                                       "DEEPAI_IMAGE_VERSION": "hd"}), \
                patch("requests.post") as m:
            m.return_value = _FakeResp({"output_url": "http://img"})
            with patch("requests.get") as g:
                g.return_value.content = b"x"
                g.return_value.raise_for_status = lambda: None
                pet_services.deepai_text2img("p")
        self.assertEqual(m.call_args.kwargs["data"]["image_generator_version"],
                         "hd")

    def test_auto_falls_back_to_deepai_without_gemini_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "",
                                       "PET_IMAGE_BACKEND": "",
                                       "DEEPAI_API_KEY": ""}):
            with self.assertRaises(RuntimeError) as ctx:
                pet_services.generate_pet_image("p")
        self.assertEqual(str(ctx.exception), "no_api_key")  # DeepAI path

    def test_explicit_deepai_backend_ignores_gemini_key(self):
        with patch.dict("os.environ", {"PET_IMAGE_BACKEND": "deepai",
                                       "GEMINI_API_KEY": "k",
                                       "DEEPAI_API_KEY": ""}), \
                patch("requests.post") as m:
            with self.assertRaises(RuntimeError):
                pet_services.generate_pet_image("p")
        m.assert_not_called()

    def test_imagen_requires_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaises(RuntimeError) as ctx:
                pet_services.imagen_generate("p")
        self.assertEqual(str(ctx.exception), "no_api_key")

    def test_imagen_empty_predictions(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                patch("requests.post", return_value=_FakeResp({"predictions": []})):
            with self.assertRaises(RuntimeError) as ctx:
                pet_services.imagen_generate("p")
        self.assertEqual(str(ctx.exception), "no_image_data")

    def test_views_alias_is_the_dispatcher(self):
        """tasks + tests patch game.views._deepai_generate: keep it wired."""
        from game import views
        self.assertIs(views._deepai_generate, pet_services.generate_pet_image)


class CreatureVarietyTests(SimpleTestCase):
    def test_species_vary_across_rolls(self):
        seen = {petgen.roll_traits(random.Random(seed))["species"]
                for seed in range(60)}
        self.assertGreaterEqual(len(seen), 10)

    def test_wings_are_rare_on_non_dragons(self):
        rolls = [petgen.roll_traits(random.Random(seed)) for seed in range(400)]
        winged = [t for t in rolls if "dragon" not in t["species"]
                  and t["wing_type"] != "no wings"]
        non_dragons = [t for t in rolls if "dragon" not in t["species"]]
        self.assertLess(len(winged) / len(non_dragons), 0.35)

    def test_prompt_leads_with_species_and_forbids_dragon(self):
        t = petgen.roll_traits(random.Random(1))
        t["species"] = "bunny"
        prompt = petgen.build_prompt(t)
        self.assertTrue(prompt.startswith("A cute cartoon baby bunny"))
        self.assertIn("must clearly be a bunny", prompt)
        self.assertIn("NOT a dragon", prompt)

    def test_dragon_prompt_has_no_contradiction(self):
        t = petgen.roll_traits(random.Random(1))
        t["species"] = "puppy dragon"
        prompt = petgen.build_prompt(t)
        self.assertIn("must clearly be a puppy dragon", prompt)
        self.assertNotIn("NOT a dragon", prompt)

    def test_prompt_still_grounded(self):
        prompt = petgen.build_prompt(petgen.roll_traits(random.Random(2)))
        for token in ("G-rated", "satanic", "no weapons", "kid-friendly"):
            self.assertIn(token, prompt)
        self.assertIn("in a cozy", prompt)  # habitat adds background variety
