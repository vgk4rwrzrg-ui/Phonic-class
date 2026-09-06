"""Diagnose Google TTS setup: credentials, permissions, and a live test call."""

import getpass
import os
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand

from game import tts


class Command(BaseCommand):
    help = ("Check Google TTS credentials and do one live synthesis. "
            "Run this as the SAME user the web app runs as, e.g.: "
            "sudo -u www-data venv/bin/python manage.py ttscheck")

    def handle(self, *args, **opts):
        w = self.stdout.write
        w(f"Running as user : {getpass.getuser()}")
        cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        w(f"GOOGLE_APPLICATION_CREDENTIALS = {cred or '(NOT SET)'}")
        if cred:
            if not os.path.exists(cred):
                self.stderr.write("  -> file DOES NOT EXIST at that path")
            elif not os.access(cred, os.R_OK):
                self.stderr.write("  -> file exists but is NOT READABLE by this user")
            else:
                head = open(cred, "rb").read(200)
                looks_json = head.lstrip().startswith(b"{")
                w(f"  -> file exists, readable, "
                  f"{'looks like a JSON key' if looks_json else 'does NOT look like JSON!'}")
        w(f"Voice           : {tts.VOICE_NAME}")

        w("\nTest 1: letter sound S (IPA phoneme)...")
        try:
            raw = tts.synthesize("S")
            path = os.path.join(settings.MEDIA_ROOT, "tts_check_S.mp3")
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(raw)
            w(self.style.SUCCESS(f"  OK ({len(raw)} bytes) -> {path}  (listen to it!)"))
        except Exception:
            self.stderr.write("  FAILED:")
            self.stderr.write(traceback.format_exc())

        w("\nTest 2: whole word 'sun'...")
        try:
            raw = tts.synthesize_word("sun")
            w(self.style.SUCCESS(f"  OK ({len(raw)} bytes)"))
        except Exception:
            self.stderr.write("  FAILED:")
            self.stderr.write(traceback.format_exc())

        w("\nIf both tests pass here but the web app still says TTS is "
          "unavailable, the service is not getting this environment. Check:\n"
          "  1. The line is inside [Service]:  Environment=\"GOOGLE_APPLICATION_CREDENTIALS=/path/key.json\"\n"
          "  2. sudo systemctl daemon-reload   (required after editing the .service file)\n"
          "  3. sudo systemctl restart <service>\n"
          "  4. The service user can read the key file (permissions!)\n"
          "  5. Verify with: sudo systemctl show <service> -p Environment")
