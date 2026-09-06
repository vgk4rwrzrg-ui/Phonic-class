"""Pet egg system: 42-trait creature generator, kid-safe image prompts,
creature names, and Google-TTS "creature voice" phrases.

Every pet is defined by exactly 42 randomly chosen traits.  The trait pools
below contain ONLY gentle, kid-friendly options; the image prompt adds strict
grounding rules on top (G-rated, no scary/dark/occult content, fixed size).
"""

import json
import random
import secrets

# ---------------------------------------------------------------------------
# 42 trait categories.  Keys are stable identifiers; values are option pools.
# ---------------------------------------------------------------------------
TRAITS = {
    "species": ["puppy dragon", "bunny", "kitten", "duckling", "baby owl",
                 "fox cub", "lamb", "turtle", "hamster", "penguin chick",
                 "koala", "axolotl", "hedgehog", "otter pup", "chick"],
    "body_color": ["sky blue", "mint green", "sunny yellow", "peach", "lavender",
                    "bubblegum pink", "seafoam", "cream", "coral", "periwinkle"],
    "secondary_color": ["white", "pale yellow", "light pink", "baby blue",
                         "soft lilac", "pastel orange", "pearl"],
    "belly_color": ["white", "cream", "pale pink", "light yellow", "mint"],
    "pattern": ["polka dots", "soft stripes", "heart-shaped spots", "star speckles",
                 "cloud patches", "flower marks", "no pattern"],
    "pattern_color": ["white", "gold", "pink", "pale blue", "lilac"],
    "eye_color": ["big brown", "sparkly blue", "emerald green", "honey gold",
                   "violet", "rainbow-flecked"],
    "eye_shape": ["huge round", "sleepy half-closed", "twinkling starry",
                   "wide curious"],
    "ear_type": ["floppy", "tiny round", "pointy tufted", "long bunny-like",
                  "small folded"],
    "tail_type": ["fluffy pom-pom", "curly", "short stubby", "long swishy",
                   "heart-tipped"],
    "wing_type": ["tiny stubby wings", "butterfly wings", "feathery little wings",
                   "no wings"],
    "head_feature": ["single curl of hair", "tiny leaf sprout", "fluffy tuft",
                      "flower bud", "small bow"],
    "cheek_feature": ["rosy pink cheeks", "peach blush", "freckled cheeks",
                       "sparkle cheeks"],
    "nose_type": ["tiny button nose", "heart-shaped nose", "small round snout"],
    "mouth_style": ["big happy smile", "tiny open grin", "sweet closed smile"],
    "tooth_style": ["one tiny front tooth", "no teeth showing"],
    "whiskers": ["short whiskers", "curly whiskers", "no whiskers"],
    "paw_type": ["round mitten paws", "tiny toe-bean paws", "webbed feet",
                  "fluffy socks paws"],
    "size": ["palm-sized", "teapot-sized", "pillow-sized"],
    "body_shape": ["round and chubby", "egg-shaped", "bean-shaped", "fluffy ball"],
    "fur_texture": ["cotton-soft fur", "velvety fur", "fluffy wool", "smooth shiny",
                     "downy feathers"],
    "glow_feature": ["softly glowing tummy", "glowing tail tip", "twinkling freckles",
                      "no glow"],
    "sparkle_level": ["a few sparkles", "shimmery all over", "no sparkles"],
    "marking": ["star on forehead", "heart on chest", "moon-crescent on back",
                 "flower on cheek", "no special marking"],
    "accessory": ["tiny scarf", "little bell collar", "flower crown", "small bowtie",
                   "acorn cap hat", "no accessory"],
    "accessory_color": ["red", "sunshine yellow", "teal", "pink", "purple"],
    "element_theme": ["sunshine", "rainbows", "fluffy clouds", "spring flowers",
                       "gentle bubbles", "twinkly stars", "autumn leaves",
                       "snowflakes"],
    "habitat": ["meadow", "treehouse", "cozy burrow", "lily pond", "cloud castle",
                 "garden", "beach"],
    "temperament": ["giggly", "shy and sweet", "bouncy", "sleepy and cuddly",
                     "brave and curious", "silly"],
    "energy_level": ["zoomy", "calm", "playful bursts", "slow and cozy"],
    "favorite_food": ["strawberries", "pancakes", "honey", "blueberries",
                       "carrots", "cookies", "watermelon"],
    "favorite_activity": ["chasing butterflies", "splashing in puddles",
                           "napping in sunbeams", "collecting shiny pebbles",
                           "dancing", "blowing bubbles"],
    "special_talent": ["super jumps", "singing hums", "finding lost things",
                        "making friends", "tiny happy dances"],
    "lucky_charm": ["four-leaf clover", "smooth river stone", "golden acorn",
                     "tiny seashell", "shiny button"],
    "best_friend_type": ["ladybug", "butterfly", "snail", "little bird", "bumblebee"],
    "dream_job": ["cloud fluffer", "cookie taster", "flower gardener",
                   "puddle inspector", "star counter"],
    "sleep_style": ["curled in a ball", "flopped on its back", "tucked in a leaf",
                     "hugging its tail"],
    "walk_style": ["happy hops", "tiny waddles", "bouncy trots", "slow toddles"],
    "laugh_sound": ["squeaky giggle", "bubbly chirp", "soft snorty laugh",
                     "musical trill"],
    "weather_love": ["sunny days", "gentle rain", "snowy mornings", "breezy afternoons"],
    "bedtime": ["sunset", "right after snacks", "when the stars come out"],
    "birthday_season": ["spring", "summer", "autumn", "winter"],
}

assert len(TRAITS) == 42, f"expected 42 trait categories, got {len(TRAITS)}"

# Traits that describe how the pet LOOKS (used in the image prompt).
VISUAL_TRAITS = [
    "species", "body_color", "secondary_color", "belly_color", "pattern",
    "pattern_color", "eye_color", "eye_shape", "ear_type", "tail_type",
    "wing_type", "head_feature", "cheek_feature", "nose_type", "mouth_style",
    "tooth_style", "whiskers", "paw_type", "size", "body_shape", "fur_texture",
    "glow_feature", "sparkle_level", "marking", "accessory", "accessory_color",
    "element_theme",
]

IMAGE_SIZE = 512  # pets are always exactly 512x512

PROMPT_RULES = (
    "Adorable kid-friendly cartoon baby pet for a children's phonics game, "
    "sticker style, thick clean outlines, bright cheerful pastel colors, "
    "simple soft background, big cute eyes, smiling and happy. "
    "STRICT RULES: G-rated and safe for young children; absolutely NO scary, "
    "dark, occult, satanic, demonic, violent, sad, or frightening elements; "
    "no weapons, no blood, no skulls, no text, no humans. "
    "Single centered creature, square composition."
)


def roll_traits(rng=None):
    """Pick one option from each of the 42 categories."""
    rng = rng or random.Random(secrets.randbits(64))
    return {key: rng.choice(pool) for key, pool in TRAITS.items()}


def build_prompt(traits):
    """Compose the DeepAI image prompt: visual traits + grounding rules."""
    parts = []
    t = traits
    parts.append(f"a {t['size']}, {t['body_shape']} baby {t['species']}")
    parts.append(f"{t['body_color']} with {t['secondary_color']} accents and a "
                 f"{t['belly_color']} belly")
    if t["pattern"] != "no pattern":
        parts.append(f"{t['pattern_color']} {t['pattern']}")
    parts.append(f"{t['eye_shape']} {t['eye_color']} eyes")
    parts.append(f"{t['ear_type']} ears, {t['tail_type']} tail")
    if t["wing_type"] != "no wings":
        parts.append(t["wing_type"])
    parts.append(f"{t['head_feature']} on its head, {t['cheek_feature']}")
    parts.append(f"{t['nose_type']}, {t['mouth_style']}")
    if t["tooth_style"] != "no teeth showing":
        parts.append(t["tooth_style"])
    if t["whiskers"] != "no whiskers":
        parts.append(t["whiskers"])
    parts.append(f"{t['paw_type']}, {t['fur_texture']}")
    if t["glow_feature"] != "no glow":
        parts.append(t["glow_feature"])
    if t["sparkle_level"] != "no sparkles":
        parts.append(t["sparkle_level"])
    if t["marking"] != "no special marking":
        parts.append(f"a {t['marking']}")
    if t["accessory"] != "no accessory":
        parts.append(f"wearing a {t['accessory_color']} {t['accessory']}")
    parts.append(f"surrounded by a hint of {t['element_theme']}")
    return PROMPT_RULES + " The pet: " + "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# Creature names and voices
# ---------------------------------------------------------------------------
_NAME_STARTS = ["Bi", "Mo", "Zu", "Pip", "Ta", "Ki", "Lu", "No", "Fi", "Wob",
                "Dax", "Yum", "Peb", "Sni", "Tof"]
_NAME_ENDS = ["bble", "ki", "lo", "pin", "zoo", "mo", "bee", "dle", "nk", "py",
              "sy", "boo", "chi", "ff", "let"]

# Syllables used to build 5-character creature phrases (gibberish "pet talk").
_SYLLABLES = ["ba", "bi", "bo", "bu", "da", "di", "du", "ka", "ki", "ko", "ku",
              "la", "li", "lo", "lu", "ma", "mi", "mo", "mu", "na", "ni", "no",
              "nu", "pa", "pi", "po", "pu", "ta", "ti", "to", "tu", "wa", "wi",
              "wo", "ya", "yo", "yu", "za", "zi", "zo", "zu"]

# Curated Google TTS voices across languages -> variety of creature timbres.
# (language_code, voice_name)
CREATURE_VOICES = [
    ("ja-JP", "ja-JP-Standard-A"),
    ("ja-JP", "ja-JP-Standard-B"),
    ("ko-KR", "ko-KR-Standard-A"),
    ("tr-TR", "tr-TR-Standard-A"),
    ("sv-SE", "sv-SE-Standard-A"),
    ("it-IT", "it-IT-Standard-A"),
    ("fi-FI", "fi-FI-Standard-A"),
    ("pt-BR", "pt-BR-Standard-A"),
    ("fr-FR", "fr-FR-Standard-A"),
    ("hi-IN", "hi-IN-Standard-A"),
]


def make_name(rng=None):
    rng = rng or random.Random(secrets.randbits(64))
    return rng.choice(_NAME_STARTS) + rng.choice(_NAME_ENDS)


def make_phrases(rng=None, count=5):
    """Build `count` short gibberish phrases of about 5 characters each."""
    rng = rng or random.Random(secrets.randbits(64))
    phrases = []
    while len(phrases) < count:
        # two syllables + optional exclamation ~= 4-5 chars of pet talk
        p = rng.choice(_SYLLABLES) + rng.choice(_SYLLABLES)
        p = p.capitalize() + "!"
        if p not in phrases:
            phrases.append(p)
    return phrases


def make_voice(rng=None):
    """Pick a consistent creature voice: language, voice name, pitch, rate."""
    rng = rng or random.Random(secrets.randbits(64))
    lang, name = rng.choice(CREATURE_VOICES)
    pitch = round(rng.uniform(4.0, 11.0), 1)     # squeaky, semitones up
    rate = round(rng.uniform(1.1, 1.35), 2)      # a bit fast = chittery
    return {"language_code": lang, "voice_name": name, "pitch": pitch, "rate": rate}


def new_pet_blueprint():
    """Everything random about a new pet, JSON-serializable."""
    rng = random.Random(secrets.randbits(64))
    traits = roll_traits(rng)
    return {
        "traits": traits,
        "prompt": build_prompt(traits),
        "name": make_name(rng),
        "phrases": make_phrases(rng),
        "voice": make_voice(rng),
    }
