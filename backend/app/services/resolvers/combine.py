"""Glue between F006's ValidatedItem output and F007+F008's individual
resolvers, producing the ResolvedItem the safety gate (F010) and meeting
record synthesis (F011b) both consume. Not itself a new resolution rule --
it only calls resolve_owner and resolve_date and assembles the result.
"""
from __future__ import annotations

from datetime import date

from app.domain.models import Participant, ResolvedItem, ValidatedItem
from app.services.resolvers.date import resolve_date
from app.services.resolvers.owner import resolve_owner


def resolve_validated_item(
    item: ValidatedItem, participants: list[Participant], meeting_date: date
) -> ResolvedItem:
    owner_id, owner_method = resolve_owner(item.raw_owner_mention, participants)
    due_date, date_method = resolve_date(item.raw_date_mention, meeting_date)
    return ResolvedItem(
        **item.model_dump(),
        owner_participant_id=owner_id,
        owner_resolution_method=owner_method,
        due_date=due_date,
        date_resolution_method=date_method,
    )


def resolve_validated_items(
    items: list[ValidatedItem], participants: list[Participant], meeting_date: date
) -> list[ResolvedItem]:
    return [resolve_validated_item(i, participants, meeting_date) for i in items]
