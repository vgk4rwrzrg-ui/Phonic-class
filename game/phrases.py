"""Every fixed phrase the game speaks, so Google TTS audio can be
pre-generated and served instead of relying on browser speechSynthesis.

The JS in game.html computes the same slug from the same text, so the two
sides stay in sync: slugify("Great job!") == "great-job".
"""

import re

from game import tts


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


PRAISE = [
    "Great job!", "You did it!", "Amazing!", "Super spelling!", "Fantastic!",
    "Wow, brilliant!", "High five!", "You are a star!", "Awesome work!", "Hooray!",
]

HINTS = [
    "Almost!", "Try again!", "So close!", "You can do it!",
    "Good try — listen again!", "Not quite — try another spot!",
]

GAME_LINES = [
    "Pop the balloons in order!",
    "Pop the balloons to spell the word!",
    "Baron Blot has stolen the letters! Spell the words to win them back!",
    "Try again — listen to the word!",
    "Take that, Baron Blot!",
    "You beat Baron Blot! The letters are safe!",
]


def balloon_hints():
    """Per-grapheme 'Try the X balloon!' lines used in the balloon round."""
    return [f"Try the {g.lower()} balloon!" for g in sorted(tts.GRAPHEME_IPA)]


def all_phrases():
    """slug -> text for every phrase the game can say."""
    out = {}
    for text in PRAISE + HINTS + GAME_LINES + balloon_hints():
        out[slugify(text)] = text
    return out
