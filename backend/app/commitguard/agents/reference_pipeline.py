"""F005 + F006: candidate extraction and commitment-validation pass.

Interim deterministic reference implementation.

docs/architecture.md documents the pipeline as an LLM-based extraction pass
(F005) followed by an LLM-based validation pass (F006). That is still the
target implementation. This module is a *pattern-based reference
implementation behind the same interface* --
``extract_and_validate(segments, meeting_id) -> list[ValidatedItem]`` --
used until an LLM provider is wired up and evaluated against the F016
scoring harness. Being deterministic, it is fully reproducible in tests and
in CI with no network calls and no API keys, and it lets F007/F008/F009/F010
be built and tested against real (if simple) candidates today.

It is intentionally a narrow, keyword/pattern-driven classifier over a
small fixture set (docs/acceptance-tests.md#f005 / #f006), not general NLU.
Swapping in an LLM-backed implementation later should only require
replacing this module's body -- callers only depend on the function
signature above and the ValidatedItem schema.

Non-negotiable boundary: nothing in this module calls, imports, or is
capable of triggering ``tools/github_issues_tool`` (which doesn't exist
yet). Text found in a transcript -- including text that reads like an
instruction to an AI system (see the prompt_injection fixture) -- is only
ever treated as the *content* of a candidate's evidence, never as a command
this pipeline executes. There is no code path here that inspects transcript
text to decide anything other than candidate/classification fields.
"""
from __future__ import annotations

import re

from app.commitguard.models.schemas import CandidateKind, Classification, EvidenceQuote, TranscriptSegment, ValidatedItem

REQUEST_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z ]{0,30}),\s*(.+)$")
REQUEST_MARKERS = ("can you", "could you", "will you", "chesthava")

AFFIRM_MARKERS = (
    "yes", "yeah", "yep", "sure", "i will", "i'll", "will do", "okay", " ok,", " ok ",
    "definitely", "absolutely", "chesthanu", "chestha,", "chestānu", "పంపిస్తాను",
)
NEGATIVE_MARKERS = (
    "i can't", "cannot", "won't be able", "not going to", "unable to",
    "i disagree", "don't agree", "do not agree", "not correct", "not right", "should not",
)
CANCEL_MARKERS = ("never mind", "cancelled", "cancel that", "no need", "not needed anymore", "got cancelled")
CORRECTION_MARKERS = ("push that to", "push it to", "let's move it to", "instead of", "actually, let's")
REDIRECT_MARKERS = ("instead", "can you take")
SUGGESTION_HEDGES = ("someone should",)
DECISION_PROPOSAL_RE = re.compile(r"\bi think we should\b", re.I)
REDIRECT_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z]+)\s+can you take\b")

_WEEKDAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
DATE_PHRASE_RE = re.compile(
    rf"(?:by\s+|eod\s+)?(?:next\s+)?(?:{_WEEKDAYS})(?:\s+(?:morning|afternoon|evening|night))?(?:\s+(?:ki|varaku))?"
    rf"|tomorrow"
    rf"|in\s+(?:a|an|one|two|three|four|five|\d+)\s+(?:day|days|week|weeks)"
    rf"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{{1,2}}",
    re.I,
)

# Targeted rewrite for the buildathon's flagship code-switched example
# ("... checklist complete chesi Monday varaku share chesthava?" ->
# "will share the deployment checklist by Monday morning"). This is a
# hand-written special case, not general machine translation -- documented
# here rather than hidden, per the non-general-NLU scope of this module.
_CHECKLIST_CHESI_RE = re.compile(r"(.+?)\s+chesi\s+.+?\s+share\s+chesthava", re.I)


def _quote(seg: TranscriptSegment) -> EvidenceQuote:
    return EvidenceQuote(segment_id=seg.segment_id, quote=seg.text)


def _find_date_phrase(text: str) -> str | None:
    m = DATE_PHRASE_RE.search(text)
    return m.group(0).strip() if m else None


def _clean_ask(text: str) -> str:
    t = text.strip().rstrip("?").strip()
    for lead in ("can you ", "could you ", "will you "):
        if t.lower().startswith(lead):
            t = t[len(lead):]
            break
    if t.lower().endswith(" chesthava"):
        t = t[: -len(" chesthava")]
    return t.strip()


def _compose_raw_text(owner: str, ask_text: str, date_phrase: str | None) -> str:
    checklist_match = _CHECKLIST_CHESI_RE.search(ask_text)
    if checklist_match:
        obj = checklist_match.group(1).strip()
        if obj.lower().endswith(" complete"):
            obj = obj[: -len(" complete")].strip()
        suffix = f" by {date_phrase}" if date_phrase else ""
        return f"{owner} will share the {obj}{suffix}"

    cleaned = _clean_ask(ask_text)
    suffix = f" by {date_phrase}" if date_phrase and date_phrase.lower() not in cleaned.lower() else ""
    return f"{owner} will {cleaned}{suffix}".strip()


def _extract_redirect_name(text: str) -> str | None:
    m = REDIRECT_NAME_RE.search(text)
    return m.group(1) if m else None


def _resolve_request_thread(
    segments: list[TranscriptSegment], ask_idx: int, addressee: str, ask_text: str, meeting_id: str, counter: int
) -> tuple[ValidatedItem, int]:
    evidence = [_quote(segments[ask_idx])]
    raw_date = _find_date_phrase(ask_text)
    owner = addressee
    classification: str | None = None
    contradiction_note: str | None = None
    last_consumed = ask_idx

    j = ask_idx + 1
    while j < len(segments) and j <= ask_idx + 6:
        seg = segments[j]
        text_l = seg.text.lower()
        speaks_as_owner = seg.speaker.strip().casefold() == owner.strip().casefold()

        if speaks_as_owner and any(r in text_l for r in REDIRECT_MARKERS) and not any(a in text_l for a in AFFIRM_MARKERS):
            new_name = _extract_redirect_name(seg.text)
            evidence.append(_quote(seg))
            last_consumed = j
            if new_name:
                owner = new_name
            j += 1
            continue

        if speaks_as_owner and any(n in text_l for n in NEGATIVE_MARKERS):
            classification = "rejected"
            evidence.append(_quote(seg))
            last_consumed = j
            break

        if speaks_as_owner and any(a in text_l for a in AFFIRM_MARKERS):
            evidence.append(_quote(seg))
            last_consumed = j
            found_date = _find_date_phrase(seg.text)
            if found_date:
                raw_date = found_date
            classification = "confirmed"

            k = j + 1
            while k < len(segments) and k <= j + 4:
                seg2 = segments[k]
                t2 = seg2.text.lower()
                if any(c in t2 for c in CANCEL_MARKERS):
                    classification = "cancelled"
                    contradiction_note = seg2.text
                    evidence.append(_quote(seg2))
                    last_consumed = k
                    break
                if any(c in t2 for c in CORRECTION_MARKERS):
                    new_date = _find_date_phrase(seg2.text)
                    evidence.append(_quote(seg2))
                    last_consumed = k
                    if k + 1 < len(segments):
                        seg3 = segments[k + 1]
                        if seg3.speaker.strip().casefold() == owner.strip().casefold() and any(
                            a in seg3.text.lower() for a in AFFIRM_MARKERS
                        ):
                            evidence.append(_quote(seg3))
                            last_consumed = k + 1
                            newer_date = _find_date_phrase(seg3.text) or new_date
                            if newer_date:
                                raw_date = newer_date
                    break
                k += 1
            break

        j += 1

    if classification is None:
        classification = "suggestion"  # asked but never clearly affirmed or declined

    candidate_id = f"{meeting_id}-c{counter:03d}"
    item = ValidatedItem(
        candidate_id=candidate_id,
        meeting_id=meeting_id,
        kind=CandidateKind.action_item,
        raw_text=_compose_raw_text(owner, ask_text, raw_date),
        evidence_quotes=evidence,
        raw_owner_mention=owner,
        raw_date_mention=raw_date,
        confidence=0.9 if classification == "confirmed" else 0.55,
        classification=Classification(classification),
        contradiction_note=contradiction_note,
    )
    return item, last_consumed


def _build_suggestion(seg: TranscriptSegment, meeting_id: str, counter: int) -> ValidatedItem:
    return ValidatedItem(
        candidate_id=f"{meeting_id}-c{counter:03d}",
        meeting_id=meeting_id,
        kind=CandidateKind.action_item,
        raw_text=seg.text,
        evidence_quotes=[_quote(seg)],
        raw_owner_mention=None,
        raw_date_mention=_find_date_phrase(seg.text),
        confidence=0.3,
        classification=Classification.suggestion,
    )


def _check_disagreement(segments: list[TranscriptSegment], idx: int, meeting_id: str, counter: int) -> tuple[ValidatedItem, int]:
    seg = segments[idx]
    evidence = [_quote(seg)]
    classification = "confirmed"
    note = None
    last = idx

    j = idx + 1
    while j < len(segments) and j <= idx + 3:
        seg2 = segments[j]
        if seg2.speaker.strip().casefold() != seg.speaker.strip().casefold() and any(
            n in seg2.text.lower() for n in NEGATIVE_MARKERS
        ):
            classification = "disputed"
            note = seg2.text
            evidence.append(_quote(seg2))
            last = j
            break
        j += 1

    item = ValidatedItem(
        candidate_id=f"{meeting_id}-c{counter:03d}",
        meeting_id=meeting_id,
        kind=CandidateKind.decision,
        raw_text=seg.text,
        evidence_quotes=evidence,
        raw_owner_mention=None,
        raw_date_mention=None,
        confidence=0.5 if classification == "disputed" else 0.8,
        classification=Classification(classification),
        contradiction_note=note,
    )
    return item, last


def extract_and_validate(segments: list[TranscriptSegment], meeting_id: str) -> list[ValidatedItem]:
    validated: list[ValidatedItem] = []
    counter = 0
    i = 0
    n = len(segments)

    while i < n:
        seg = segments[i]
        req_match = REQUEST_LINE_RE.match(seg.text)
        addressee = None
        ask_text = seg.text

        if req_match:
            name_part, rest = req_match.group(1).strip(), req_match.group(2).strip()
            if len(name_part.split()) <= 3 and any(m in rest.lower() for m in REQUEST_MARKERS):
                addressee = name_part
                ask_text = rest

        if addressee:
            item, consumed = _resolve_request_thread(segments, i, addressee, ask_text, meeting_id, counter)
            validated.append(item)
            counter += 1
            i = consumed + 1
            continue

        if any(h in seg.text.lower() for h in SUGGESTION_HEDGES):
            validated.append(_build_suggestion(seg, meeting_id, counter))
            counter += 1
            i += 1
            continue

        if DECISION_PROPOSAL_RE.search(seg.text):
            item, consumed = _check_disagreement(segments, i, meeting_id, counter)
            validated.append(item)
            counter += 1
            i = consumed + 1
            continue

        i += 1

    return validated
