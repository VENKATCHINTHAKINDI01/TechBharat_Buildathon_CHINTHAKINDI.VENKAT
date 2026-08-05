"""F002: deterministic transcript ingestion for .txt / .vtt / .srt.

No LLM involved anywhere in this module -- parsing is pure format handling.
Malformed input raises ``TranscriptParseError`` (never a bare crash), per
docs/acceptance-tests.md#f002.

Supported line convention for speaker attribution, used by all three
formats: ``Speaker: utterance text``. In .vtt, the WebVTT voice tag
``<v Speaker>text`` is also accepted as an alternative to the colon
convention.
"""
from __future__ import annotations

import re
from pydantic import BaseModel


class TranscriptParseError(Exception):
    """Raised for any transcript input that cannot be parsed deterministically.

    Carries enough detail (line number + offending content) to show a human
    reviewer exactly what failed, instead of surfacing a raw traceback.
    """


class RawUtterance(BaseModel):
    speaker: str
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


_SPEAKER_LINE_RE = re.compile(r"^([^:]{1,80}):\s*(.+)$")
_VTT_VOICE_TAG_RE = re.compile(r"^<v\s+([^>]+)>(.*)$")
_VTT_TIMESTAMP_RE = re.compile(
    r"^(\d{2,}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2,}):(\d{2}):(\d{2})[.,](\d{3})"
)


def _timestamp_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 3600 + int(m) * 60 + int(s)) * 1000) + int(ms)


def _split_speaker_line(line: str, line_no: int) -> tuple[str, str]:
    match = _SPEAKER_LINE_RE.match(line)
    if not match:
        raise TranscriptParseError(
            f"line {line_no}: expected 'Speaker: text' format, got: {line!r}"
        )
    speaker, text = match.group(1).strip(), match.group(2).strip()
    if not speaker or not text:
        raise TranscriptParseError(f"line {line_no}: empty speaker or text in: {line!r}")
    return speaker, text


def parse_txt(content: str) -> list[RawUtterance]:
    """Plain-text transcript: one utterance per non-comment, non-blank line,
    as ``Speaker: text``. Lines starting with '#' are comments (used for
    fixture metadata) and are skipped."""
    utterances: list[RawUtterance] = []
    for i, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        speaker, text = _split_speaker_line(line, i)
        utterances.append(RawUtterance(speaker=speaker, text=text))
    if not utterances:
        raise TranscriptParseError("no utterances found in .txt transcript")
    return utterances


def parse_vtt(content: str) -> list[RawUtterance]:
    """WebVTT: cue blocks of [optional cue id] / timestamp line / text
    line(s). Text lines may use '<v Speaker>text' or 'Speaker: text'."""
    lines = content.splitlines()
    if not lines or not lines[0].strip().upper().startswith("WEBVTT"):
        raise TranscriptParseError("not a WEBVTT file: missing 'WEBVTT' header")

    utterances: list[RawUtterance] = []
    i = 1
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        ts_match = _VTT_TIMESTAMP_RE.match(line)
        if not ts_match:
            # could be a numeric/text cue id preceding the timestamp line
            if i < n and _VTT_TIMESTAMP_RE.match(lines[i].strip()):
                i += 1  # skip cue id, re-fetch the real timestamp line below
                ts_match = _VTT_TIMESTAMP_RE.match(lines[i - 1].strip())
            if not ts_match:
                raise TranscriptParseError(f"line {i}: expected a WebVTT timestamp, got: {line!r}")
        start_ms = _timestamp_to_ms(*ts_match.group(1, 2, 3, 4))
        end_ms = _timestamp_to_ms(*ts_match.group(5, 6, 7, 8))

        text_lines: list[str] = []
        while i < n and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        if not text_lines:
            raise TranscriptParseError(f"cue ending near line {i}: has a timestamp but no text")

        cue_text = " ".join(text_lines)
        voice_match = _VTT_VOICE_TAG_RE.match(cue_text)
        if voice_match:
            speaker, text = voice_match.group(1).strip(), voice_match.group(2).strip()
        else:
            speaker, text = _split_speaker_line(cue_text, i)
        utterances.append(RawUtterance(speaker=speaker, text=text, start_ms=start_ms, end_ms=end_ms))

    if not utterances:
        raise TranscriptParseError("no cues found in .vtt transcript")
    return utterances


def parse_srt(content: str) -> list[RawUtterance]:
    """SubRip: numeric index / timestamp line / text line(s) / blank line."""
    blocks = re.split(r"\n\s*\n", content.strip())
    utterances: list[RawUtterance] = []
    for block_no, block in enumerate(blocks, start=1):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            raise TranscriptParseError(f"block {block_no}: too few lines for a valid SRT cue")
        idx_line = lines[0].strip()
        if not idx_line.isdigit():
            raise TranscriptParseError(f"block {block_no}: expected a numeric index, got: {idx_line!r}")
        ts_match = _VTT_TIMESTAMP_RE.match(lines[1].strip())
        if not ts_match:
            raise TranscriptParseError(f"block {block_no}: expected an SRT timestamp, got: {lines[1]!r}")
        start_ms = _timestamp_to_ms(*ts_match.group(1, 2, 3, 4))
        end_ms = _timestamp_to_ms(*ts_match.group(5, 6, 7, 8))
        cue_text = " ".join(l.strip() for l in lines[2:])
        speaker, text = _split_speaker_line(cue_text, block_no)
        utterances.append(RawUtterance(speaker=speaker, text=text, start_ms=start_ms, end_ms=end_ms))

    if not utterances:
        raise TranscriptParseError("no cues found in .srt transcript")
    return utterances


_PARSERS = {"txt": parse_txt, "vtt": parse_vtt, "srt": parse_srt}


def parse_transcript(filename: str, content: str) -> list[RawUtterance]:
    """Dispatch on file extension. Raises TranscriptParseError for
    unsupported extensions or malformed content."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _PARSERS.get(ext)
    if parser is None:
        raise TranscriptParseError(f"unsupported transcript extension: {ext!r} (filename={filename!r})")
    return parser(content)
