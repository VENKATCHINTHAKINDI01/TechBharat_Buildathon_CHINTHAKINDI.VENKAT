"""Why a live meeting produced nothing.

A real live meeting captured a transcript and then reported "No
candidates were extracted from this transcript" — with no warning, no log
line and no audit entry. The extraction step swallowed ``ExtractionError``
and fell through to the pattern-based extractor, which finds almost
nothing in natural speech.

The bug was not the fallback. Falling back is correct. The bug was that
it was *invisible*, so a broken LLM key, a paraphrasing model and a quiet
meeting all looked identical from the UI.

These tests pin the rule: **a live session that produces zero candidates
must always be able to say why.**
"""
from datetime import date

import pytest

from app.core.config import Settings
from app.domain.models import (
    CandidateKind,
    Classification,
    EvidenceQuote,
    Participant,
    TranscriptSegment,
    ValidatedItem,
)
from app.services.extraction.base import ExtractionError
from app.services.live import LiveSession

PARTICIPANTS = [
    Participant(participant_id="p-rohit", name="Rohit"),
    Participant(participant_id="p-arjun", name="Arjun"),
]


class BrokenExtractor:
    """Stands in for a bad API key, a shut-down model, a rate limit."""

    name = "groq"

    def __init__(self, message="model `llama-3.3-70b-versatile` has been decommissioned"):
        self.message = message

    def extract(self, segments, meeting_id):
        raise ExtractionError(self.message)


class SilentExtractor:
    name = "reference"

    def extract(self, segments, meeting_id):
        return []


class ParaphrasingExtractor:
    """A model that finds the commitment but retypes the quote."""

    name = "groq"

    def extract(self, segments, meeting_id):
        return [
            ValidatedItem(
                candidate_id=f"{meeting_id}-c000",
                meeting_id=meeting_id,
                kind=CandidateKind.action_item,
                raw_text="Rohit will finish the API migration by Friday",
                evidence_quotes=[
                    EvidenceQuote(
                        segment_id="s1",
                        quote="Rohit agreed to complete the migration",  # never said
                    )
                ],
                classification=Classification.confirmed,
                confidence=0.9,
            )
        ]


def _session(extractor, fallback=None) -> LiveSession:
    return LiveSession(
        meeting_id="m-live",
        meeting_date=date(2026, 8, 6),
        participants=PARTICIPANTS,
        settings=Settings(confidence_threshold=0.75),
        extractor=extractor,
        fallback_extractor=fallback or SilentExtractor(),
        transcriber=None,
    )


def _speak(session: LiveSession, lines: list[tuple[str, str]]) -> None:
    session.acknowledge_consent()
    for speaker, text in lines:
        session.add_text_segment(speaker, text)


LINES = [
    ("Arjun", "Rohit, can you finish the API migration by Friday?"),
    ("Rohit", "Yes, I will finish the API migration by Friday."),
    ("Arjun", "Great, thanks."),
]


# --- the failure that was silent -------------------------------------------


async def test_a_failing_extractor_warns_instead_of_going_quiet():
    session = _session(BrokenExtractor())
    _speak(session, LINES)
    await session.reprocess_all()

    assert session.extractor_used == "reference"
    assert "decommissioned" in session.extraction_error
    joined = " ".join(session.warnings)
    assert "AI extractor failed" in joined
    assert "decommissioned" in joined, "the actual cause must reach the operator"


async def test_the_failure_reason_reaches_the_snapshot():
    """The websocket payload is what the UI renders, so the reason has to
    survive into it."""
    session = _session(BrokenExtractor("401 invalid api key"))
    _speak(session, LINES)
    await session.reprocess_all()

    snapshot = session.snapshot()
    assert snapshot["extractor"] == "reference"
    assert "invalid api key" in snapshot["extraction_error"]
    assert any("AI extractor failed" in w for w in snapshot["warnings"])


async def test_both_extractors_failing_does_not_crash_the_meeting():
    """Losing extraction must not lose the transcript."""
    session = _session(BrokenExtractor(), fallback=BrokenExtractor("fallback exploded"))
    _speak(session, LINES)
    items = await session.reprocess_all()

    assert items == []
    assert len(session.segments) == 3, "the transcript survives"
    assert any("Both extractors failed" in w for w in session.warnings)


# --- a paraphrasing model -------------------------------------------------


async def test_a_paraphrasing_model_says_the_quotes_were_unsupported():
    session = _session(ParaphrasingExtractor())
    _speak(session, LINES)
    items = await session.reprocess_all()

    assert items == []
    joined = " ".join(session.warnings)
    assert "Evidence check" in joined
    assert "not in the transcript" in joined
    assert session.evidence_report.dropped_items


# --- a genuinely quiet meeting --------------------------------------------


async def test_a_quiet_meeting_is_distinguishable_from_a_broken_one():
    """Silence is a legitimate answer. It just has to be labelled as one,
    and must not claim the extractor failed."""
    session = _session(SilentExtractor(), fallback=SilentExtractor())
    _speak(session, [("Arjun", "Morning."), ("Rohit", "Morning."), ("Arjun", "Nice weather.")])
    items = await session.reprocess_all()

    assert items == []
    assert session.extraction_error is None
    joined = " ".join(session.warnings)
    assert "No commitments were found" in joined
    assert "failed" not in joined


async def test_a_successful_pass_adds_no_warnings():
    from app.services.extraction.reference import ReferenceExtractor

    session = _session(ReferenceExtractor(), fallback=ReferenceExtractor())
    _speak(session, LINES)
    items = await session.reprocess_all()

    assert items, "the reference extractor should find this scripted phrasing"
    assert session.warnings == []
    assert session.extraction_error is None


async def test_warnings_are_not_repeated_across_passes():
    """process() runs every few seconds; the same warning must not stack
    up into an unreadable wall."""
    session = _session(BrokenExtractor())
    _speak(session, LINES)
    for _ in range(4):
        await session.reprocess_all()

    assert len(session.warnings) == len(set(session.warnings))
