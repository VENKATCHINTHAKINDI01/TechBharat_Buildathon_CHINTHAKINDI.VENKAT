"""
Parses uploaded txt/vtt/srt into a list of raw transcript segments.
Returns plain dicts (not TranscriptChunk models yet -- meeting_id isn't
known until the Meeting doc exists, which happens in the ingestion agent).

VTT/SRT are timestamped and may carry "Speaker: text" lines.
Plain txt has no timing -- treated as one block per non-empty line,
speaker "Unknown" unless a "Name: text" prefix is present.
"""
import re

TIMESTAMP_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})"
)
SPEAKER_RE = re.compile(r"^([A-Za-z][\w .]{0,40}):\s*(.+)$")


def _ts_to_seconds(ts: str) -> float:
    ts = ts.replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_vtt_or_srt(raw_text: str) -> list[dict]:
    """Handles both formats -- the --> timestamp line is the only structural
    difference that matters, cue numbering / WEBVTT header are ignored."""
    segments: list[dict] = []
    blocks = re.split(r"\n\s*\n", raw_text.strip())
    idx = 0
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        ts_line = next((l for l in lines if TIMESTAMP_RE.search(l)), None)
        if not ts_line:
            continue
        start, end = TIMESTAMP_RE.search(ts_line).groups()
        text_lines = [l for l in lines if l != ts_line and not l.strip().isdigit()]
        text = " ".join(text_lines).strip()
        if not text:
            continue

        speaker = "Unknown"
        m = SPEAKER_RE.match(text)
        if m:
            speaker, text = m.group(1).strip(), m.group(2).strip()

        segments.append({
            "chunk_index": idx,
            "speaker_label": speaker,
            "raw_text": text,
            "start_ts": _ts_to_seconds(start),
            "end_ts": _ts_to_seconds(end),
        })
        idx += 1
    return segments


def parse_plain_txt(raw_text: str) -> list[dict]:
    segments: list[dict] = []
    for idx, line in enumerate(l for l in raw_text.splitlines() if l.strip()):
        speaker, text = "Unknown", line.strip()
        m = SPEAKER_RE.match(line.strip())
        if m:
            speaker, text = m.group(1).strip(), m.group(2).strip()
        segments.append({
            "chunk_index": idx,
            "speaker_label": speaker,
            "raw_text": text,
            "start_ts": None,
            "end_ts": None,
        })
    return segments


def parse_transcript_file(filename: str, raw_text: str) -> list[dict]:
    lower = filename.lower()
    if lower.endswith(".vtt") or lower.endswith(".srt"):
        return parse_vtt_or_srt(raw_text)
    return parse_plain_txt(raw_text)