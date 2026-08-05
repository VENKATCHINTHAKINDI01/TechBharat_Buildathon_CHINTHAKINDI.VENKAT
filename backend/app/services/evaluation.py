"""F016: evaluation harness.

Scores an extractor against the labelled dataset in
``tests/fixtures/labels.json`` on the metrics the TechBharat brief
actually judges:

- action item recall     (target >= 80%)
- action item precision  (target >= 75%)
- owner accuracy         (target >= 85%)
- date resolution        (target >= 90%)

Matching is intentionally lenient on wording and strict on the fields
that cause real-world harm. An extractor that phrases a commitment
differently but attributes it to the right person on the right date is
correct; one that gets the wording perfect and the owner wrong is not.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.domain.models import CandidateKind, Participant, ResolvedItem
from app.services.extraction.base import Extractor, drop_unsupported_evidence
from app.services.ingestion.normalization import normalize
from app.services.ingestion.parser import parse_txt
from app.services.resolvers.combine import resolve_validated_items

TARGETS = {
    "action_item_recall": 0.80,
    "action_item_precision": 0.75,
    "owner_accuracy": 0.85,
    "date_accuracy": 0.90,
}

_STOPWORDS = {"the", "a", "an", "to", "by", "for", "of", "and", "will", "up"}


def _keywords(text: str) -> set[str]:
    return {
        w.strip(".,!?;:").lower()
        for w in text.split()
        if w.strip(".,!?;:").lower() not in _STOPWORDS and len(w) > 2
    }


def matches(expected_summary: str, produced_text: str) -> bool:
    """A produced item matches a labelled one when it covers at least
    half the labelled summary's content words. Deliberately loose: we
    are scoring whether the commitment was *found*, not whether the
    phrasing was copied."""
    expected = _keywords(expected_summary)
    if not expected:
        return False
    overlap = expected & _keywords(produced_text)
    return len(overlap) / len(expected) >= 0.5


@dataclass
class TranscriptScore:
    fixture: str
    expected: int = 0
    found: int = 0
    produced: int = 0
    owner_correct: int = 0
    owner_scored: int = 0
    date_correct: int = 0
    date_scored: int = 0
    classification_correct: int = 0
    gate_correct: int = 0
    misses: list[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    extractor: str
    per_transcript: list[TranscriptScore]

    def _sum(self, attr: str) -> int:
        return sum(getattr(s, attr) for s in self.per_transcript)

    @property
    def recall(self) -> float:
        expected = self._sum("expected")
        return self._sum("found") / expected if expected else 0.0

    @property
    def precision(self) -> float:
        produced = self._sum("produced")
        return self._sum("found") / produced if produced else 0.0

    @property
    def owner_accuracy(self) -> float:
        scored = self._sum("owner_scored")
        return self._sum("owner_correct") / scored if scored else 0.0

    @property
    def date_accuracy(self) -> float:
        scored = self._sum("date_scored")
        return self._sum("date_correct") / scored if scored else 0.0

    @property
    def classification_accuracy(self) -> float:
        found = self._sum("found")
        return self._sum("classification_correct") / found if found else 0.0

    @property
    def gate_accuracy(self) -> float:
        found = self._sum("found")
        return self._sum("gate_correct") / found if found else 0.0

    def as_dict(self) -> dict:
        return {
            "extractor": self.extractor,
            "action_item_recall": round(self.recall, 4),
            "action_item_precision": round(self.precision, 4),
            "owner_accuracy": round(self.owner_accuracy, 4),
            "date_accuracy": round(self.date_accuracy, 4),
            "classification_accuracy": round(self.classification_accuracy, 4),
            "gate_accuracy": round(self.gate_accuracy, 4),
            "targets": TARGETS,
            "meets_targets": self.meets_targets(),
            "misses": {s.fixture: s.misses for s in self.per_transcript if s.misses},
        }

    def meets_targets(self) -> dict[str, bool]:
        return {
            "action_item_recall": self.recall >= TARGETS["action_item_recall"],
            "action_item_precision": self.precision >= TARGETS["action_item_precision"],
            "owner_accuracy": self.owner_accuracy >= TARGETS["owner_accuracy"],
            "date_accuracy": self.date_accuracy >= TARGETS["date_accuracy"],
        }


def load_dataset(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(extractor: Extractor, dataset_path: Path, fixtures_dir: Path) -> EvaluationReport:
    dataset = load_dataset(dataset_path)
    participants = [Participant.model_validate(p) for p in dataset["participants"]]
    meeting_date = date.fromisoformat(dataset["meeting_date"])

    scores: list[TranscriptScore] = []

    for entry in dataset["transcripts"]:
        fixture = entry["fixture"]
        score = TranscriptScore(fixture=fixture)

        content = (fixtures_dir / fixture).read_text(encoding="utf-8")
        segments = normalize(parse_txt(content), meeting_id="eval")
        validated = drop_unsupported_evidence(extractor.extract(segments, "eval"), segments)
        resolved: list[ResolvedItem] = resolve_validated_items(
            validated, participants, meeting_date
        )
        produced = [r for r in resolved if r.kind == CandidateKind.action_item]
        score.produced = len(produced)

        unmatched = list(produced)
        for expected in entry["expected_action_items"]:
            score.expected += 1
            hit = next((p for p in unmatched if matches(expected["summary"], p.raw_text)), None)
            if hit is None:
                score.misses.append(expected["summary"])
                continue
            unmatched.remove(hit)
            score.found += 1

            if expected["classification"] == hit.classification.value:
                score.classification_correct += 1

            score.owner_scored += 1
            if expected["owner_participant_id"] == hit.owner_participant_id:
                score.owner_correct += 1

            # Only score dates the label says are resolvable; "no date was
            # spoken" is not a date-resolution failure.
            if expected["due_date"] is not None:
                score.date_scored += 1
                if hit.due_date and hit.due_date.isoformat() == expected["due_date"]:
                    score.date_correct += 1

            from app.core.config import get_settings
            from app.domain.safety.gate import check_gate

            decision = check_gate(hit, get_settings().confidence_threshold)
            if decision.eligible == expected["gate_eligible"]:
                score.gate_correct += 1

        scores.append(score)

    return EvaluationReport(extractor=getattr(extractor, "name", "unknown"), per_transcript=scores)
