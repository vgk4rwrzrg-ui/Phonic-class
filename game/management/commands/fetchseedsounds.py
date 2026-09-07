"""Download + process the Wikimedia Commons phoneme recordings into
game/seed_audio/ as classroom-ready MP3s, then write ATTRIBUTION.md.

Run once (network + ffmpeg), then: python manage.py seedsounds
X and QU are built by concatenating K+S and K+W.
"""
import os
import re
import subprocess
import tempfile

import requests
from django.core.management.base import BaseCommand

from game.audio import _ffmpeg_path  # bundled imageio-ffmpeg binary

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_audio")

GRAPHEME_FILES = {
 "A": "Near-open front unrounded vowel.ogg",
 "B": "Voiced bilabial plosive.ogg",
 "C": "Voiceless velar plosive.ogg",
 "D": "Voiced alveolar plosive.ogg",
 "E": "Open-mid front unrounded vowel.ogg",
 "F": "Voiceless labiodental fricative.ogg",
 "G": "Voiced velar plosive.ogg",
 "H": "Voiceless glottal fricative.ogg",
 "I": "Near-close near-front unrounded vowel.ogg",
 "J": "Voiced postalveolar affricate.ogg",
 "K": "Voiceless velar plosive.ogg",
 "L": "Alveolar lateral approximant.ogg",
 "M": "Bilabial nasal.ogg",
 "N": "Alveolar nasal.ogg",
 "O": "Open back rounded vowel.ogg",
 "P": "Voiceless bilabial plosive.ogg",
 "R": "Alveolar approximant.ogg",
 "S": "Voiceless alveolar sibilant.ogg",
 "T": "Voiceless alveolar plosive.ogg",
 "U": "Open-mid back unrounded vowel.ogg",
 "V": "Voiced labiodental fricative.ogg",
 "W": "Voiced labio-velar approximant.ogg",
 "Y": "Palatal approximant.ogg",
 "Z": "Voiced alveolar sibilant.ogg",
 "SH": "Voiceless postalveolar fricative.ogg",
 "CH": "Voiceless palato-alveolar affricate.ogg",
 "TH": "Voiceless dental fricative.ogg",
 "NG": "Velar nasal.ogg",
 "ZH": "Voiced postalveolar fricative.ogg"
}

FILE_SOURCES = {
 "Voiceless bilabial plosive.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/5/51/Voiceless_bilabial_plosive.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Velar nasal.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/3/39/Velar_nasal.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Alveolar nasal.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/2/29/Alveolar_nasal.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Alveolar lateral approximant.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/b/bc/Alveolar_lateral_approximant.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiced labio-velar approximant.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/f/f2/Voiced_labio-velar_approximant.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiced postalveolar fricative.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/3/30/Voiced_palato-alveolar_sibilant.ogg",
  "artist": "<a href=\"//commons.wikimedia.org/wiki/User:Peter_Isotalo\" title=\"User:Peter Isotalo\">Peter Isotalo</a>",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless glottal fricative.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/d/da/Voiceless_glottal_fricative.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiced labiodental fricative.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/8/85/Voiced_labiodental_fricative.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless palato-alveolar affricate.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/9/97/Voiceless_palato-alveolar_affricate.ogg",
  "artist": "<a href=\"//commons.wikimedia.org/wiki/User:Peter_Isotalo\" title=\"User:Peter Isotalo\">Peter Isotalo</a>",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless alveolar plosive.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/0/02/Voiceless_alveolar_plosive.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless postalveolar fricative.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/c/cc/Voiceless_palato-alveolar_sibilant.ogg",
  "artist": "<a href=\"//commons.wikimedia.org/wiki/User:Peter_Isotalo\" title=\"User:Peter Isotalo\">Peter Isotalo</a>",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless labiodental fricative.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/3/33/Voiceless_labiodental_fricative.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless dental fricative.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/8/80/Voiceless_dental_fricative.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiced alveolar plosive.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/0/01/Voiced_alveolar_plosive.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Palatal approximant.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/e/e8/Palatal_approximant.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiced alveolar sibilant.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/c/c0/Voiced_alveolar_sibilant.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Alveolar approximant.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/1/1f/Alveolar_approximant.ogg",
  "artist": "<a href=\"//commons.wikimedia.org/wiki/User:Erutuon\" title=\"User:Erutuon\">Erutuon</a>",
  "license": "CC BY-SA 3.0"
 },
 "Bilabial nasal.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Bilabial_nasal.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiced bilabial plosive.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/2/2c/Voiced_bilabial_plosive.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiced postalveolar affricate.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/e/e6/Voiced_palato-alveolar_affricate.ogg",
  "artist": "The original uploader was <a href=\"https://en.wikipedia.org/wiki/User:Octane\" class=\"extiw\" title=\"wikipedia:User:Octane\">Octane</a> at <a href=\"https://en.wikipedia.org/wiki/\" class=\"extiw\" title=\"wikipedia:\">English Wikipedia</a>.",
  "license": "Public domain"
 },
 "Open-mid back unrounded vowel.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/9/92/Open-mid_back_unrounded_vowel.ogg",
  "artist": "No machine-readable author provided. <a href=\"//commons.wikimedia.org/wiki/User:Denelson83\" title=\"User:Denelson83\">Denelson83</a> assumed (based on copyright claims).",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless velar plosive.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/e/e3/Voiceless_velar_plosive.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Voiceless alveolar sibilant.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/a/ac/Voiceless_alveolar_sibilant.ogg",
  "artist": "<a href=\"//commons.wikimedia.org/wiki/User:Peter_Isotalo\" title=\"User:Peter Isotalo\">Peter Isotalo</a>",
  "license": "CC BY-SA 3.0"
 },
 "Open-mid front unrounded vowel.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/7/71/Open-mid_front_unrounded_vowel.ogg",
  "artist": "No machine-readable author provided. <a href=\"//commons.wikimedia.org/wiki/User:Denelson83\" title=\"User:Denelson83\">Denelson83</a> assumed (based on copyright claims).",
  "license": "CC BY-SA 3.0"
 },
 "Near-open front unrounded vowel.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/c/c9/Near-open_front_unrounded_vowel.ogg",
  "artist": "No machine-readable author provided. <a href=\"//commons.wikimedia.org/wiki/User:Denelson83\" title=\"User:Denelson83\">Denelson83</a> assumed (based on copyright claims).",
  "license": "CC BY-SA 3.0"
 },
 "Open back rounded vowel.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/0/0a/Open_back_rounded_vowel.ogg",
  "artist": "No machine-readable author provided. <a href=\"//commons.wikimedia.org/wiki/User:Denelson83\" title=\"User:Denelson83\">Denelson83</a> assumed (based on copyright claims).",
  "license": "CC BY-SA 3.0"
 },
 "Voiced velar plosive.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/b/b4/Voiced_velar_plosive.ogg",
  "artist": "?",
  "license": "CC BY-SA 3.0"
 },
 "Near-close near-front unrounded vowel.ogg": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/4/4c/Near-close_near-front_unrounded_vowel.ogg",
  "artist": "No machine-readable author provided. <a href=\"//commons.wikimedia.org/wiki/User:Denelson83\" title=\"User:Denelson83\">Denelson83</a> assumed (based on copyright claims).",
  "license": "CC BY-SA 3.0"
 }
}

COMBOS = {"X": ["K", "S"], "QU": ["K", "W"]}

CLEAN_ARGS = ["-af",
    "silenceremove=start_periods=1:start_threshold=-40dB:"
    "stop_periods=1:stop_threshold=-40dB,loudnorm=I=-16:TP=-1.5",
    "-ac", "1", "-ar", "44100", "-b:a", "64k"]


def _run_ffmpeg(args):
    subprocess.run([_ffmpeg_path(), "-y", *args], check=True, timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def process_ogg_to_mp3(ogg_path, mp3_path):
    """Trim silence, normalise loudness, downmix to a small mono MP3."""
    _run_ffmpeg(["-i", ogg_path, *CLEAN_ARGS, mp3_path])


def concat_mp3s(parts, out_path):
    """Join part MP3s back-to-back (used to build X = K+S, QU = K+W)."""
    inputs = []
    for p in parts:
        inputs += ["-i", p]
    n = len(parts)
    filt = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1"
    _run_ffmpeg([*inputs, "-filter_complex", filt, "-ac", "1",
                 "-ar", "44100", "-b:a", "64k", out_path])


def write_attribution(path):
    lines = ["# Bundled phoneme recordings - attribution\n",
             "Source: Wikimedia Commons IPA phoneme recordings.",
             "X and QU are concatenations of the K/S and K/W recordings.\n"]
    for fname, m in sorted(FILE_SOURCES.items()):
        artist = re.sub(r"<[^>]+>", "", m["artist"]).strip()
        lines.append(f"- **{fname}** - {artist} - {m['license']} - {m['url']}")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


class Command(BaseCommand):
    help = "Fetch + process bundled phoneme recordings (network + ffmpeg)."

    def handle(self, *args, **opts):
        os.makedirs(SEED_DIR, exist_ok=True)
        sess = requests.Session()
        sess.headers["User-Agent"] = "PhonicClass/1.0 (classroom phonics app)"
        with tempfile.TemporaryDirectory() as tmp:
            raw = {}
            for fname, m in sorted(FILE_SOURCES.items()):
                r = sess.get(m["url"], timeout=20)
                r.raise_for_status()
                p = os.path.join(tmp, fname)
                open(p, "wb").write(r.content)
                raw[fname] = p
                self.stdout.write(f"downloaded {fname} ({len(r.content)} bytes)")
            for g, fname in sorted(GRAPHEME_FILES.items()):
                process_ogg_to_mp3(raw[fname], os.path.join(SEED_DIR, f"{g}.mp3"))
                self.stdout.write(f"processed  {g}.mp3")
            for g, parts in sorted(COMBOS.items()):
                concat_mp3s([os.path.join(SEED_DIR, f"{p}.mp3") for p in parts],
                            os.path.join(SEED_DIR, f"{g}.mp3"))
                self.stdout.write(f"combined   {g}.mp3 from {'+'.join(parts)}")
        write_attribution(os.path.join(SEED_DIR, "ATTRIBUTION.md"))
        self.stdout.write(self.style.SUCCESS(
            "seed_audio ready. Now run: python manage.py seedsounds"))
