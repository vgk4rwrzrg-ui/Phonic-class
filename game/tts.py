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

# Spoken respelling for each grapheme — kept in sync with the JS
# LETTER_SOUNDS / DIGRAPH_SOUNDS / TRIGRAPH_SOUNDS fallback maps in game.html.
# This text goes INSIDE the SSML <phoneme> tag: voices that honor the tag use
# the IPA above, and any voice that ignores the tag reads this respelling —
# so the worst case is "suh", never the letter name "ess".
GRAPHEME_SAY = {
    "A": "ah", "B": "buh", "C": "kuh", "D": "duh", "E": "eh", "F": "fuh",
    "G": "guh", "H": "huh", "I": "ih", "J": "juh", "K": "kuh", "L": "luh",
    "M": "muh", "N": "nuh", "O": "ah", "P": "puh", "Q": "kwuh", "R": "ruh",
    "S": "suh", "T": "tuh", "U": "uh", "V": "vuh", "W": "wuh", "X": "ks",
    "Y": "yuh", "Z": "zuh",
    "SH": "shh", "CH": "chuh", "TH": "thuh", "CK": "kuh", "NG": "ing",
    "QU": "kwuh", "WH": "wuh", "PH": "fuh",
    "EE": "ee", "OO": "oo", "AI": "ay", "AY": "ay", "EA": "ee", "OA": "oh",
    "IE": "eye", "OI": "oy", "OY": "oy", "OU": "ow", "OW": "ow",
    "AU": "aw", "AW": "aw", "AR": "ar", "ER": "ur", "IR": "ur", "UR": "ur",
    "OR": "or",
    "IGH": "eye", "TCH": "chuh", "DGE": "juh", "EAR": "eer", "AIR": "air",
}

# Default voice MUST honor the SSML <phoneme> tag. WaveNet and Standard
# voices do; Neural2 / Studio / Journey / Chirp voices IGNORE it and read
# the letter name instead ("S" -> "ess"), which is exactly wrong for
# phonics. Override with GOOGLE_TTS_VOICE only if the voice supports IPA.
VOICE_NAME = os.environ.get("GOOGLE_TTS_VOICE", "en-US-Wavenet-F")

# Voice families known to ignore <phoneme>; ttscheck warns about these.
PHONEME_UNSUPPORTED_FAMILIES = ("Neural2", "Studio", "Journey", "Chirp",
                                "Polyglot", "News", "Casual")


def voice_supports_phonemes(voice_name=None):
    """Best-effort check that a voice honors SSML <phoneme> IPA hints."""
    name = voice_name or VOICE_NAME
    return not any(f in name for f in PHONEME_UNSUPPORTED_FAMILIES)


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


def _synth_ssml(ssml):
    from google.cloud import texttospeech

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


def synthesize(grapheme):
    """Return MP3 audio bytes for a single grapheme via Google Cloud TTS.

    Continuants use a length mark (e.g. "sː" -> "sss").  Some voices reject
    length marks on consonants with INVALID_ARGUMENT; if that happens we
    retry with a slowed-down plain phoneme so the sound still generates.
    """
    g = (grapheme or "").strip().upper()
    ipa = GRAPHEME_IPA.get(g)
    say = GRAPHEME_SAY.get(g, g.lower())
    if not ipa:
        return _synth_ssml(f"<speak>{say}</speak>")
    try:
        return _synth_ssml(
            f'<speak><phoneme alphabet="ipa" ph="{ipa}">{say}</phoneme></speak>')
    except Exception:
        if "\u02d0" not in ipa:  # no length mark -> nothing to strip, re-raise
            raise
        # Retry: strip the length mark, stretch with prosody instead.
        plain = ipa.replace("\u02d0", "")
        return _synth_ssml(
            f'<speak><prosody rate="60%">'
            f'<phoneme alphabet="ipa" ph="{plain}">{say}</phoneme>'
            f"</prosody></speak>")


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


def synthesize_creature(text, language_code, voice_name, pitch, rate):
    """Return MP3 bytes of a gibberish creature phrase in a squeaky voice."""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=(text or "").strip())
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code, name=voice_name
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        pitch=float(pitch),          # semitones up = small-creature squeak
        speaking_rate=float(rate),
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    return response.audio_content
