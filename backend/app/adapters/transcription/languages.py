"""Sarvam language codes, validated before they reach the API.

A wrong ``language_code`` is rejected by Sarvam with a 400, and the place
that surfaced was the *diarization pass at the end of a meeting* — the
worst possible moment, after the audio has already been captured and the
call has already ended.

So the code is normalised and validated here instead. Common ways of
writing "detect it for me" (``auto``, ``auto-detect``, ``autodetect``,
empty) all mean ``unknown`` to Sarvam, and bare language names or
two-letter codes are expanded to the ``xx-IN`` form the API expects.
Anything genuinely unrecognised falls back to ``unknown`` with a warning
rather than being forwarded to fail later.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("nexvi_meets.transcription")

AUTO_DETECT = "unknown"

# Exactly the set Sarvam accepts, from its own 400 response.
SARVAM_LANGUAGE_CODES: frozenset[str] = frozenset(
    {
        AUTO_DETECT,
        "hi-IN", "bn-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN",
        "ta-IN", "te-IN", "en-IN", "gu-IN", "as-IN", "ur-IN", "ne-IN",
        "kok-IN", "ks-IN", "sd-IN", "sa-IN", "sat-IN", "mni-IN",
        "brx-IN", "mai-IN", "doi-IN",
    }
)

# Ways people write "let the model figure it out".
_AUTO_ALIASES = {"", "auto", "auto-detect", "autodetect", "auto_detect", "detect", "none", "null"}

# Bare ISO-639-1 codes and English names -> Sarvam's regional form.
_BARE_TO_SARVAM = {
    "hi": "hi-IN", "bn": "bn-IN", "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN",
    "od": "od-IN", "or": "od-IN", "pa": "pa-IN", "ta": "ta-IN", "te": "te-IN",
    "en": "en-IN", "gu": "gu-IN", "as": "as-IN", "ur": "ur-IN", "ne": "ne-IN",
    "sa": "sa-IN", "ks": "ks-IN", "sd": "sd-IN",
    "hindi": "hi-IN", "bengali": "bn-IN", "kannada": "kn-IN",
    "malayalam": "ml-IN", "marathi": "mr-IN", "odia": "od-IN",
    "punjabi": "pa-IN", "tamil": "ta-IN", "telugu": "te-IN",
    "english": "en-IN", "gujarati": "gu-IN", "assamese": "as-IN",
    "urdu": "ur-IN", "nepali": "ne-IN", "sanskrit": "sa-IN",
}


def normalize_language_code(value: str | None) -> str:
    """Coerce a configured language code into something Sarvam accepts.

    Never raises. A misconfigured code degrades to auto-detect — which is
    what a user asking for "auto-detect" wanted anyway — rather than
    failing a request after the meeting is over.
    """
    raw = (value or "").strip()
    lowered = raw.lower()

    if lowered in _AUTO_ALIASES:
        return AUTO_DETECT
    if raw in SARVAM_LANGUAGE_CODES:
        return raw

    # Case-insensitive match against the real set ("TE-IN" -> "te-IN").
    for code in SARVAM_LANGUAGE_CODES:
        if code.lower() == lowered:
            return code

    if lowered in _BARE_TO_SARVAM:
        return _BARE_TO_SARVAM[lowered]

    logger.warning(
        "SARVAM_LANGUAGE_CODE=%r is not a value Sarvam accepts; using %r (auto-detect). "
        "Valid values: %s",
        raw,
        AUTO_DETECT,
        ", ".join(sorted(SARVAM_LANGUAGE_CODES)),
    )
    return AUTO_DETECT
