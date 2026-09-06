"""Google Cloud Text-to-Speech helpers for letter sounds.

Each grapheme is mapped to an English (US) IPA phoneme string that Google TTS
can pronounce. Stops get a trailing schwa ("bə") so the familiar "buh/duh"
letter sound comes out; continuants and vowels are left as pure phonemes.

See https://cloud.google.com/text-to-speech/docs/phonemes for the supported set.
"""

import os

# Grapheme -> IPA phoneme (alphabet="ipa", en-US).
GRAPHEME_IPA = {
    "A": "æ", "B": "bə", "C": "kə", "D": "də", "E": "ɛ", "F": "fː", "G": "ɡə",
    "H": "hə", "I": "ɪ", "J": "ʤə", "K": "kə", "L": "lː", "M": "mː", "N": "nː",
    "O": "ɑː", "P": "pə", "Q": "kwə", "R": "ɹː", "S": "sː", "T": "tə", "U": "ʌ",
    "V": "vː", "W": "wə", "X": "ks", "Y": "jə", "Z": "zː",
    "SH": "ʃː", "CH": "ʧə", "TH": "θː", "CK": "kə", "NG": "ŋː", "QU": "kwə",
    "WH": "wə", "PH": "fː",
    "EE": "iː", "OO": "uː", "AI": "eɪ", "AY": "eɪ", "EA": "iː", "OA": "oʊ",
    "IE": "aɪ", "OI": "ɔɪ", "OY": "ɔɪ", "OU": "aʊ", "OW": "aʊ",
    "AU": "ɔː", "AW": "ɔː", "AR": "ɑːɹ", "ER": "ɚ", "IR": "ɚ", "UR": "ɚ",
    "OR": "ɔːɹ",
    "IGH": "aɪ", "TCH": "ʧə", "DGE": "ʤə", "EAR": "ɪɹ", "AIR": "ɛɹ",
}

# These must stay in sync with the JS splitter in game.html.
DIGRAPHS = {
    "sh", "ch", "th", "ck", "ng", "qu", "wh", "ph", "ee", "oo", "ai", "ay",
    "ea", "oa", "ie", "oi", "oy", "ou", "ow", "au", "aw", "ar", "er", "ir",
    "ur", "or",
}
TRIGRAPHS = {"igh", "tch", "dge", "ear", "air"}

VOICE_NAME = os.environ.get("GOOGLE_TTS_VOICE", "en-US-Neural2-F")


def split_graphemes(text):
    """Split a word into grapheme units (same algorithm as the browser)."""
    units = []
    lower = (text or "").lower()
    i = 0
    while i < len(lower):
        if lower[i:i + 3] in TRIGRAPHS:
            units.append(lower[i:i + 3].upper())
            i += 3
        elif lower[i:i + 2] in DIGRAPHS:
            units.append(lower[i:i + 2].upper())
            i += 2
        else:
            units.append(lower[i].upper())
            i += 1
    return units


def synthesize(grapheme):
    """Return MP3 audio bytes for a single grapheme via Google Cloud TTS."""
    from google.cloud import texttospeech

    g = (grapheme or "").strip().upper()
    ipa = GRAPHEME_IPA.get(g)
    if ipa:
        ssml = f'<speak><phoneme alphabet="ipa" ph="{ipa}">{g}</phoneme></speak>'
    else:
        ssml = f"<speak>{g.lower()}</speak>"

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(ssml=ssml)
    voice = texttospeech.VoiceSelectionParams(language_code="en-US", name=VOICE_NAME)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    return response.audio_content


def synthesize_word(word):
    """Return MP3 audio bytes for a whole word via Google Cloud TTS."""
    from google.cloud import texttospeech

    w = (word or "").strip().lower()
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=w)
    voice = texttospeech.VoiceSelectionParams(language_code="en-US", name=VOICE_NAME)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.85,   # a touch slower for young learners
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    return response.audio_content


def synthesize_phrase(text):
    """Return MP3 audio bytes for a spoken game phrase via Google Cloud TTS."""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=(text or "").strip())
    voice = texttospeech.VoiceSelectionParams(language_code="en-US", name=VOICE_NAME)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    return response.audio_content
