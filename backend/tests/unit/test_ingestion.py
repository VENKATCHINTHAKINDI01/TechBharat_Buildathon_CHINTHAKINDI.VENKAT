"""F002/F003 acceptance tests -- see docs/acceptance-tests.md#f002 and #f003."""
from pathlib import Path

import pytest

from app.services.ingestion.normalization import normalize
from app.services.ingestion.parser import (
    RawUtterance,
    TranscriptParseError,
    parse_srt,
    parse_transcript,
    parse_txt,
    parse_vtt,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"

ALL_TXT_FIXTURES = [
    "confirmed_commitment.txt",
    "vague_suggestion.txt",
    "owner_reassignment.txt",
    "deadline_change.txt",
    "disagreement.txt",
    "cancelled_commitment.txt",
    "ambiguous_owner.txt",
    "prompt_injection.txt",
    "code_switched.txt",
]


def test_fixtures_directory_has_all_nine_named_fixtures():
    for name in ALL_TXT_FIXTURES:
        assert (FIXTURES / name).is_file(), f"missing fixture: {name}"


@pytest.mark.parametrize("name", ALL_TXT_FIXTURES)
def test_parse_txt_on_each_fixture_does_not_raise(name):
    content = (FIXTURES / name).read_text(encoding="utf-8")
    utterances = parse_txt(content)
    assert len(utterances) >= 1
    assert all(isinstance(u, RawUtterance) for u in utterances)
    assert all(u.speaker and u.text for u in utterances)


def test_parse_txt_malformed_raises_typed_error_not_a_crash():
    content = (FIXTURES / "malformed.txt").read_text(encoding="utf-8")
    with pytest.raises(TranscriptParseError):
        parse_txt(content)


def test_code_switched_fixture_preserves_telugu_text_verbatim():
    content = (FIXTURES / "code_switched.txt").read_text(encoding="utf-8")
    utterances = parse_txt(content)
    assert utterances[0].speaker == "Arjun"
    assert "chesthava?" in utterances[0].text
    assert utterances[1].speaker == "Priya"
    assert "పంపిస్తాను" in utterances[1].text


def test_parse_vtt_sample():
    content = (FIXTURES / "sample.vtt").read_text(encoding="utf-8")
    utterances = parse_vtt(content)
    assert len(utterances) == 2
    assert utterances[0].speaker == "Arjun"
    assert utterances[0].start_ms == 0
    assert utterances[0].end_ms == 2000
    assert utterances[1].speaker == "Rohit"
    assert utterances[1].start_ms == 2500


def test_parse_vtt_missing_header_raises():
    with pytest.raises(TranscriptParseError):
        parse_vtt("00:00:00.000 --> 00:00:02.000\nArjun: hi\n")


def test_parse_srt_sample():
    content = (FIXTURES / "sample.srt").read_text(encoding="utf-8")
    utterances = parse_srt(content)
    assert len(utterances) == 2
    assert utterances[0].speaker == "Arjun"
    assert utterances[0].start_ms == 0
    assert utterances[1].speaker == "Rohit"
    assert utterances[1].end_ms == 4000


def test_parse_srt_missing_index_raises():
    with pytest.raises(TranscriptParseError):
        parse_srt("00:00:00,000 --> 00:00:02,000\nArjun: hi\n")


def test_parse_transcript_dispatches_on_extension():
    txt_content = (FIXTURES / "confirmed_commitment.txt").read_text(encoding="utf-8")
    assert len(parse_transcript("confirmed_commitment.txt", txt_content)) == 2

    vtt_content = (FIXTURES / "sample.vtt").read_text(encoding="utf-8")
    assert len(parse_transcript("sample.vtt", vtt_content)) == 2


def test_parse_transcript_unsupported_extension_raises():
    with pytest.raises(TranscriptParseError):
        parse_transcript("meeting.docx", "irrelevant")


def test_normalize_assigns_stable_ordered_segment_ids():
    content = (FIXTURES / "confirmed_commitment.txt").read_text(encoding="utf-8")
    utterances = parse_txt(content)
    segments = normalize(utterances, meeting_id="m1")
    assert [s.segment_id for s in segments] == ["m1-000", "m1-001"]
    assert segments[0].speaker == "Arjun"
    assert segments[1].speaker == "Rohit"
    # re-running normalize on the same input is deterministic
    segments_again = normalize(utterances, meeting_id="m1")
    assert segments == segments_again
