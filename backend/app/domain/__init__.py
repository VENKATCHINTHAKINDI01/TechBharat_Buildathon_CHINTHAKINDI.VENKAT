"""Domain layer: pure data shapes and the deterministic safety gate.

Nothing in this package performs I/O -- no database, no network, no LLM.
That is what makes the safety gate auditable: it can only ever see
structured data that a caller assembled, never a raw transcript or a
model response. See docs/architecture.md.
"""
from app.domain.models import (
    AuditEvent,
    AuditStage,
    CandidateItem,
    CandidateKind,
    Classification,
    DateResolutionMethod,
    EvidenceQuote,
    GateDecision,
    GitHubIssueRecord,
    MeetingRecord,
    OwnerResolutionMethod,
    Participant,
    Priority,
    ResolvedItem,
    ReviewDecision,
    ReviewDecisionValue,
    TranscriptSegment,
    ValidatedItem,
)
from app.domain.safety.gate import check_gate

__all__ = [
    "AuditEvent", "AuditStage", "CandidateItem", "CandidateKind", "Classification",
    "DateResolutionMethod", "EvidenceQuote", "GateDecision", "GitHubIssueRecord",
    "MeetingRecord", "OwnerResolutionMethod", "Participant", "Priority",
    "ResolvedItem", "ReviewDecision", "ReviewDecisionValue", "TranscriptSegment",
    "ValidatedItem", "check_gate",
]
