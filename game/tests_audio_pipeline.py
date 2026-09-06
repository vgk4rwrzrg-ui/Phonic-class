"""Tests for the ffmpeg cleanup pipeline — subprocess fully mocked.

Run with: python manage.py test game.tests_audio_pipeline
"""
import os
from unittest.mock import patch

from django.test import SimpleTestCase

from game import audio


class CleanAudioTests(SimpleTestCase):
    def test_empty_bytes_short_circuits(self):
        self.assertEqual(audio.clean_audio(b"", "in.webm"), (b"", "webm"))

    def test_missing_ffmpeg_falls_back_to_raw(self):
        with patch("game.audio._ffmpeg_available", return_value=False):
            out, ext = audio.clean_audio(b"RAW", "voice.wav")
        self.assertEqual((out, ext), (b"RAW", "wav"))

    def test_default_extension_is_webm(self):
        with patch("game.audio._ffmpeg_available", return_value=False):
            self.assertEqual(audio.clean_audio(b"RAW", None), (b"RAW", "webm"))

    def test_success_returns_cleaned_mp3(self):
        calls = {}

        def fake_run(cmd, check=True, timeout=None, **kw):
            calls["cmd"] = cmd
            with open(cmd[-1], "wb") as fh:  # ffmpeg output path is last arg
                fh.write(b"CLEANED")

        with patch("game.audio._ffmpeg_path", return_value="ffmpeg"), \
                patch("game.audio._ffmpeg_available", return_value=True), \
                patch("game.audio.subprocess.run", side_effect=fake_run):
            out, ext = audio.clean_audio(b"RAW", "take.webm")

        self.assertEqual((out, ext), (b"CLEANED", "mp3"))
        # The silence-trim / denoise / loudnorm filter chain must stay intact.
        self.assertIn("-af", calls["cmd"])
        self.assertEqual(calls["cmd"][calls["cmd"].index("-af") + 1],
                         audio.FILTERS)
        self.assertIn("silenceremove", audio.FILTERS)
        self.assertIn("loudnorm", audio.FILTERS)

    def test_ffmpeg_crash_falls_back_to_raw(self):
        with patch("game.audio._ffmpeg_path", return_value="ffmpeg"), \
                patch("game.audio._ffmpeg_available", return_value=True), \
                patch("game.audio.subprocess.run",
                      side_effect=RuntimeError("boom")):
            out, ext = audio.clean_audio(b"RAW", "take.m4a")
        self.assertEqual((out, ext), (b"RAW", "m4a"))

    def test_empty_output_file_falls_back_to_raw(self):
        def fake_run(cmd, check=True, timeout=None, **kw):
            open(cmd[-1], "wb").close()  # zero-byte output

        with patch("game.audio._ffmpeg_path", return_value="ffmpeg"), \
                patch("game.audio._ffmpeg_available", return_value=True), \
                patch("game.audio.subprocess.run", side_effect=fake_run):
            out, ext = audio.clean_audio(b"RAW", "take.webm")
        self.assertEqual((out, ext), (b"RAW", "webm"))
