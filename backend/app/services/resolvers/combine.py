"""Glue between the extraction output and the individual resolvers.

Produces the ``ResolvedItem`` that the safety gate, the review API and
the meeting record all consume. Two responsibilities beyond plumbing:

1. It preserves the extractor's own confidence in ``extraction_confidence``
   and writes the **composite** score into ``confidence``, because the
   gate's threshold rule should account for resolution quality, not just
   the model's self-assessment.
2. It is the only place that decides what "the date was claimed" means,
   so the confidence scorer never has to guess.
"""
from __future__ import annotations

from datetime import date

from app.domain.models import Participant, ResolvedItem, ValidatedItem
from app.services.confidence import compute_confidence, compute_field_confidence
from app.services.resolvers.date import resolve_date
from app.services.resolvers.owner import resolve_owner


def resolve_validated_item(
    item: ValidatedItem, participants: list[Participant], meeting_date: date
) -> ResolvedItem:
    owner_id, owner_method = resolve_owner(item.raw_owner_mention, participants)
    due_date, date_method = resolve_date(item.raw_date_mention, meeting_date)

    composite = compute_confidence(
        extraction_confidence=item.confidence,
        owner_method=owner_method,
        date_method=date_method,
        date_was_claimed=bool(item.raw_date_mention),
    )

    fields = compute_field_confidence(
        extraction_confidence=item.confidence,
        owner_method=owner_method,
        date_method=date_method,
        date_was_claimed=bool(item.raw_date_mention),
        state_settled=item.current_state in (None, "accepted", "rejected", "cancelled"),
    )

    payload = item.model_dump()
    payload["extraction_confidence"] = item.confidence
    payload["confidence"] = composite
    payload["field_confidence"] = fields.as_dict()

    return ResolvedItem(
        **payload,
        owner_participant_id=owner_id,
        owner_resolution_method=owner_method,
        due_date=due_date,
        date_resolution_method=date_method,
    )


def resolve_validated_items(
    items: list[ValidatedItem], participants: list[Participant], meeting_date: date
) -> list[ResolvedItem]:
    return [resolve_validated_item(i, participants, meeting_date) for i in items]


def recompute_confidence(item: ResolvedItem) -> ResolvedItem:
    """Recompute the composite score after a reviewer edits owner or date.

    Without this, a human fixing an unresolvable owner would clear the
    owner rule but stay blocked by a stale low confidence score -- the
    gate would be punishing the item for a problem the reviewer just fixed.
    """
    extraction = (
        item.extraction_confidence if item.extraction_confidence is not None else item.confidence
    )
    composite = compute_confidence(
        extraction_confidence=extraction,
        owner_method=item.owner_resolution_method,
        date_method=item.date_resolution_method,
        # A human-set date counts as claimed even if nobody spoke one.
        date_was_claimed=bool(item.raw_date_mention) or item.due_date is not None,
        human_confirmed=item.human_confirmed,
    )
    fields = compute_field_confidence(
        extraction_confidence=extraction,
        owner_method=item.owner_resolution_method,
        date_method=item.date_resolution_method,
        date_was_claimed=bool(item.raw_date_mention) or item.due_date is not None,
        state_settled=item.current_state in (None, "accepted", "rejected", "cancelled"),
        human_confirmed=item.human_confirmed,
    )
    return item.model_copy(
        update={"confidence": composite, "field_confidence": fields.as_dict()}
    )
