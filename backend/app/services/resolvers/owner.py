"""F007: deterministic owner resolution against a participant directory.

Non-negotiable: this module never guesses. A mention resolves to exactly
one participant, or it resolves to nothing (``unresolved``). It is the only
place in the pipeline allowed to set ``owner_participant_id`` -- the safety
gate (F010) trusts this output rather than re-deriving it.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from app.domain.models import OwnerResolutionMethod, Participant

FUZZY_THRESHOLD = 85.0


def _candidate_names(p: Participant) -> list[str]:
    return [p.name, *p.aliases]


def resolve_owner(
    mention: str | None, participants: list[Participant]
) -> tuple[str | None, OwnerResolutionMethod]:
    if not mention or not mention.strip():
        return None, OwnerResolutionMethod.unresolved

    needle = mention.strip().casefold()

    # 1. exact match (case-insensitive) against name or any alias.
    exact_hits = [
        p for p in participants if needle in {n.casefold() for n in _candidate_names(p)}
    ]
    if len(exact_hits) == 1:
        return exact_hits[0].participant_id, OwnerResolutionMethod.exact_match
    if len(exact_hits) > 1:
        # Same mention exactly matches more than one real participant
        # (e.g. two people both go by "Priya") -- fail closed.
        return None, OwnerResolutionMethod.unresolved

    # 2. fuzzy match: score against every candidate name/alias, keep the
    #    best score per participant, then require a single, clear winner
    #    at or above the threshold.
    scored: list[tuple[float, Participant]] = []
    for p in participants:
        best = max((fuzz.WRatio(needle, n.casefold()) for n in _candidate_names(p)), default=0.0)
        if best >= FUZZY_THRESHOLD:
            scored.append((best, p))

    if len(scored) == 1:
        return scored[0][1].participant_id, OwnerResolutionMethod.fuzzy_match

    if len(scored) > 1:
        scored.sort(key=lambda t: t[0], reverse=True)
        top_score, _ = scored[0]
        runner_up_score, _ = scored[1]
        # Only accept if the top match is unambiguously better than the
        # runner-up; otherwise two similarly-named participants are
        # indistinguishable from this mention and we must not guess.
        if top_score - runner_up_score >= 10.0:
            return scored[0][1].participant_id, OwnerResolutionMethod.fuzzy_match
        return None, OwnerResolutionMethod.unresolved

    return None, OwnerResolutionMethod.unresolved
