"""The citation check, and why it silently emptied a live meeting.

A live meeting produced a transcript and then reported "No candidates
were extracted from this transcript" with nothing else. Three different
failures produce that identical symptom, and none of them said anything:

  1. the LLM call failed and the deterministic fallback found nothing;
  2. the LLM returned items but paraphrased its quotes, so every action
     item was dropped here;
  3. the meeting genuinely contained no commitments.

These tests pin the fix for (2) and the fact that (1) and (3) are now
distinguishable. The security property is unchanged throughout: evidence
shown to a reviewer is always a literal span of the transcript.
"""
from app.domain.models import (
    CandidateKind,
    Classification,
    EvidenceQuote,
    TranscriptSegment,
    ValidatedItem,
)
from app.services.extraction.base import (
    EvidenceReport,
    drop_unsupported_evidence,
    find_verbatim_span,
)

# Whisper output: curly apostrophe, em dash. Both are what a real ASR
# engine emits and neither is what a model tends to type back.
SPOKEN = "Yes, I’ll have the API migration done by Friday — no problem."
SEGMENTS = [TranscriptSegment(segment_id="s1", speaker="Rohit", text=SPOKEN)]


def _item(quote: str, kind=CandidateKind.action_item) -> ValidatedItem:
    return ValidatedItem(
        candidate_id="c1",
        meeting_id="m1",
        kind=kind,
        raw_text="Rohit will finish the API migration by Friday",
        evidence_quotes=[EvidenceQuote(segment_id="s1", quote=quote)],
        classification=Classification.confirmed,
        confidence=0.9,
    )


# --- what must still match -------------------------------------------------


def test_an_exact_quote_matches():
    assert find_verbatim_span("API migration done by Friday", SPOKEN) is not None


def test_a_straightened_apostrophe_still_matches():
    """The single most common real-world mismatch."""
    assert find_verbatim_span("I'll have the API migration done", SPOKEN) is not None


def test_a_hyphen_for_an_em_dash_still_matches():
    assert find_verbatim_span("by Friday - no problem", SPOKEN) is not None


def test_case_and_extra_whitespace_still_match():
    assert find_verbatim_span("i'll   have  the api migration", SPOKEN) is not None


# --- what must NOT match ---------------------------------------------------


def test_a_genuine_paraphrase_is_still_rejected():
    """This is the whole guarantee. Relaxing typography must not relax
    what counts as something the speaker actually said."""
    assert find_verbatim_span("I will have the API migration done", SPOKEN) is None
    assert find_verbatim_span("Rohit agreed to do the migration", SPOKEN) is None


def test_invented_words_are_still_rejected():
    assert find_verbatim_span("and I'll deploy it to production too", SPOKEN) is None


def test_an_empty_quote_matches_nothing():
    assert find_verbatim_span("", SPOKEN) is None
    assert find_verbatim_span("anything", "") is None


# --- the returned span belongs to the transcript, not the model ------------


def test_the_stored_quote_is_the_transcripts_wording_not_the_models():
    """A model that types a straight apostrophe must not thereby rewrite
    the transcript. What is shown to the reviewer is the segment's own
    text -- otherwise 'evidence' would be model output with extra steps.
    """
    span = find_verbatim_span("I'll have the API migration done", SPOKEN)
    assert span in SPOKEN
    assert "’" in span  # the curly one, as actually spoken


def test_a_repaired_quote_is_replaced_on_the_item():
    surviving = drop_unsupported_evidence([_item("I'll have the API migration done")], SEGMENTS)
    assert len(surviving) == 1
    stored = surviving[0].evidence_quotes[0].quote
    assert stored in SPOKEN


# --- the reporting that was missing ----------------------------------------


def test_a_paraphrasing_model_loses_its_action_items_and_says_so():
    report = EvidenceReport()
    surviving = drop_unsupported_evidence(
        [_item("Rohit committed to finishing the migration")], SEGMENTS, report
    )

    assert surviving == []
    assert report.dropped_items == ["Rohit will finish the API migration by Friday"]
    assert report.quotes_dropped == 1
    assert "1 action item(s) dropped" in report.summary
    assert "s1" in report.examples[0]


def test_a_clean_pass_reports_nothing_to_complain_about():
    report = EvidenceReport()
    drop_unsupported_evidence([_item("API migration done by Friday")], SEGMENTS, report)

    assert report.summary is None
    assert report.quotes_kept == 1
    assert report.quotes_dropped == 0


def test_repairs_are_counted_separately_from_clean_matches():
    report = EvidenceReport()
    drop_unsupported_evidence([_item("I'll have the API migration done")], SEGMENTS, report)

    assert report.quotes_repaired == 1
    assert report.quotes_kept == 1


def test_a_non_action_item_survives_without_evidence():
    """Decisions and risks are allowed to be evidence-free; only action
    items can create external work, so only they must be citable."""
    report = EvidenceReport()
    surviving = drop_unsupported_evidence(
        [_item("nothing like this was said", kind=CandidateKind.decision)], SEGMENTS, report
    )

    assert len(surviving) == 1
    assert surviving[0].evidence_quotes == []
    assert report.dropped_items == []


def test_a_quote_citing_an_unknown_segment_is_dropped():
    item = _item("Yes, I’ll have the API migration done")
    item.evidence_quotes[0].segment_id = "does-not-exist"
    report = EvidenceReport()

    assert drop_unsupported_evidence([item], SEGMENTS, report) == []
    assert report.quotes_dropped == 1
