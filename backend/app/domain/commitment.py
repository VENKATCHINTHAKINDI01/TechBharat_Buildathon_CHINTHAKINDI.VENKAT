"""The commitment state engine.

A commitment is not a fact extracted once. It is something that *happens
over the course of a meeting*: someone proposes it, someone accepts it,
it gets handed to a different person, the deadline slips, somebody
objects, it gets called off. Treating it as a single classification
throws that history away — and the history is exactly what tells you
whether the thing is real.

So a commitment is a **thread of timestamped events**, each carrying the
verbatim line that caused it. The current owner, the current deadline and
the classification the safety gate reads are all *derived* from that
thread rather than stored independently, which means they cannot drift
out of sync with the evidence.

This replaces the earlier design where a renegotiated thread collapsed
into one candidate and the reason lived in a free-text
``contradiction_note``. That lost the sequence, and ``contradiction_of``
was specified but never populated. Now the sequence is the record.

## The rule that matters

**Any change to the terms requires fresh acceptance.**

If a task is reassigned, or its deadline moves, the thread does not stay
`accepted` — it returns to a pending state until the new owner agrees to
the new terms. Nobody is bound to a commitment they did not make. That is
a stricter reading than most tools take, and it is deliberate: this
product's claim is commitment integrity, and inheriting an acceptance
across changed terms would quietly break it.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CommitmentState(str, Enum):
    """Where a commitment stands right now."""

    proposed = "proposed"                    # asked, nobody has agreed yet
    accepted = "accepted"                    # the named owner said yes
    reassigned = "reassigned"                # handed to someone else, awaiting their yes
    deadline_changed = "deadline_changed"    # terms moved, awaiting re-acceptance
    disputed = "disputed"                    # the room did not reach consensus
    rejected = "rejected"                    # the named owner declined
    cancelled = "cancelled"                  # called off after being agreed


#: Which states may follow which. A transition outside this map is a bug
#: in the extractor, not a new kind of meeting, so it is rejected loudly
#: rather than silently recorded.
LEGAL_TRANSITIONS: dict[Optional[CommitmentState], set[CommitmentState]] = {
    None: {CommitmentState.proposed, CommitmentState.accepted, CommitmentState.disputed},
    CommitmentState.proposed: {
        CommitmentState.accepted,
        CommitmentState.rejected,
        CommitmentState.reassigned,
        CommitmentState.disputed,
        CommitmentState.cancelled,
    },
    CommitmentState.accepted: {
        CommitmentState.reassigned,
        CommitmentState.deadline_changed,
        CommitmentState.disputed,
        CommitmentState.cancelled,
    },
    CommitmentState.reassigned: {
        CommitmentState.accepted,
        CommitmentState.rejected,
        CommitmentState.reassigned,
        CommitmentState.disputed,
        CommitmentState.cancelled,
    },
    CommitmentState.deadline_changed: {
        CommitmentState.accepted,
        CommitmentState.rejected,
        CommitmentState.deadline_changed,
        CommitmentState.disputed,
        CommitmentState.cancelled,
    },
    CommitmentState.disputed: {
        CommitmentState.accepted,
        CommitmentState.rejected,
        CommitmentState.cancelled,
        CommitmentState.reassigned,
    },
    # A declined task can be picked up by someone else, or re-proposed.
    CommitmentState.rejected: {
        CommitmentState.proposed,
        CommitmentState.reassigned,
        CommitmentState.cancelled,
    },
    # Cancelling is not quite terminal -- teams do revive things.
    CommitmentState.cancelled: {CommitmentState.proposed, CommitmentState.reassigned},
}

#: Only ``accepted`` maps to a classification the safety gate will pass.
#: Everything else is a state in which nobody is currently on the hook.
STATE_TO_CLASSIFICATION: dict[CommitmentState, str] = {
    CommitmentState.proposed: "suggestion",
    CommitmentState.accepted: "confirmed",
    CommitmentState.reassigned: "suggestion",
    CommitmentState.deadline_changed: "suggestion",
    CommitmentState.disputed: "disputed",
    CommitmentState.rejected: "rejected",
    CommitmentState.cancelled: "cancelled",
}

#: Human-readable, used in timelines and reports.
STATE_LABELS: dict[CommitmentState, str] = {
    CommitmentState.proposed: "Proposed",
    CommitmentState.accepted: "Accepted",
    CommitmentState.reassigned: "Reassigned",
    CommitmentState.deadline_changed: "Deadline changed",
    CommitmentState.disputed: "Disputed",
    CommitmentState.rejected: "Declined",
    CommitmentState.cancelled: "Cancelled",
}


class IllegalTransition(ValueError):
    """An extractor proposed a state change the machine does not allow."""


class CommitmentEvent(BaseModel):
    """One thing that happened to a commitment, and the line that caused it.

    ``quote`` is verbatim from the transcript and is what makes the
    timeline auditable: every state change can be traced to words someone
    actually said.
    """

    state: CommitmentState
    at_ms: int = 0
    segment_id: Optional[str] = None
    quote: str = ""
    actor: Optional[str] = None          # who spoke the line
    # What this event changed, when it changed something.
    owner: Optional[str] = None          # participant_id after this event
    owner_mention: Optional[str] = None  # name as spoken
    due_date: Optional[date] = None
    date_mention: Optional[str] = None
    note: Optional[str] = None

    @property
    def label(self) -> str:
        return STATE_LABELS.get(self.state, self.state.value)


class FieldConfidence(BaseModel):
    """Confidence broken out per field.

    One blended number cannot tell a reviewer *what* to fix. Splitting it
    means the gate can say "the owner is the weak part" instead of
    "confidence 0.62", which is the difference between an actionable
    message and a shrug.
    """

    text: float = Field(default=0.0, ge=0.0, le=1.0)
    owner: float = Field(default=0.0, ge=0.0, le=1.0)
    date: float = Field(default=0.0, ge=0.0, le=1.0)
    state: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def weakest_field(self) -> str:
        return min(
            (("text", self.text), ("owner", self.owner), ("date", self.date), ("state", self.state)),
            key=lambda pair: pair[1],
        )[0]

    def as_dict(self) -> dict[str, float]:
        return {"text": self.text, "owner": self.owner, "date": self.date, "state": self.state}


class CommitmentThread(BaseModel):
    """The full life of one commitment within a meeting."""

    thread_id: str
    meeting_id: str
    summary: str = ""
    events: list[CommitmentEvent] = Field(default_factory=list)
    field_confidence: FieldConfidence = Field(default_factory=FieldConfidence)
    created_at: Optional[datetime] = None

    # --- derived state -----------------------------------------------

    @property
    def current_state(self) -> Optional[CommitmentState]:
        return self.events[-1].state if self.events else None

    @property
    def classification(self) -> str:
        state = self.current_state
        return STATE_TO_CLASSIFICATION.get(state, "suggestion") if state else "suggestion"

    @property
    def current_owner(self) -> Optional[str]:
        """The last owner anyone named, walking backwards.

        Backwards because a reassignment is the most recent word on who
        holds this, and a later deadline change does not un-name them.
        """
        for event in reversed(self.events):
            if event.owner:
                return event.owner
        return None

    @property
    def current_owner_mention(self) -> Optional[str]:
        for event in reversed(self.events):
            if event.owner_mention:
                return event.owner_mention
        return None

    @property
    def current_due_date(self) -> Optional[date]:
        for event in reversed(self.events):
            if event.due_date:
                return event.due_date
        return None

    @property
    def current_date_mention(self) -> Optional[str]:
        for event in reversed(self.events):
            if event.date_mention:
                return event.date_mention
        return None

    @property
    def was_renegotiated(self) -> bool:
        """True if the terms changed after someone had already agreed.

        Worth surfacing: a task that was reassigned or slipped mid-meeting
        is exactly the kind that gets forgotten afterwards.
        """
        return any(
            e.state in (CommitmentState.reassigned, CommitmentState.deadline_changed)
            for e in self.events
        )

    @property
    def is_settled(self) -> bool:
        """Nobody is waiting on anyone: accepted, declined or called off."""
        return self.current_state in (
            CommitmentState.accepted,
            CommitmentState.rejected,
            CommitmentState.cancelled,
        )

    @property
    def evidence_quotes(self) -> list[tuple[str, str]]:
        return [(e.segment_id or "", e.quote) for e in self.events if e.quote and e.segment_id]

    # --- mutation ----------------------------------------------------

    def can_transition_to(self, state: CommitmentState) -> bool:
        return state in LEGAL_TRANSITIONS.get(self.current_state, set())

    def add(self, event: CommitmentEvent, strict: bool = True) -> "CommitmentThread":
        """Append an event, enforcing the transition map.

        ``strict=False`` is for extractor output, where an impossible
        sequence means the model got confused: the event is dropped rather
        than corrupting the thread or crashing the meeting.
        """
        if not self.can_transition_to(event.state):
            if strict:
                raise IllegalTransition(
                    f"cannot go from {self.current_state} to {event.state} "
                    f"in thread {self.thread_id}"
                )
            return self
        self.events.append(event)
        return self

    def timeline(self) -> list[dict]:
        """Render for the UI and the report."""
        return [
            {
                "state": e.state.value,
                "label": e.label,
                "at_ms": e.at_ms,
                "at": f"{e.at_ms // 60000:02d}:{(e.at_ms // 1000) % 60:02d}",
                "actor": e.actor,
                "quote": e.quote,
                "segment_id": e.segment_id,
                "owner_mention": e.owner_mention,
                "date_mention": e.date_mention,
                "note": e.note,
            }
            for e in self.events
        ]
