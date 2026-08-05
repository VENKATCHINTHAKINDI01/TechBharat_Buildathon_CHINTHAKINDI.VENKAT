"""F016 -- the evaluation harness scores the deterministic baseline.

This test pins the reference extractor's current measured performance on
the labelled fixture set. It is deliberately an assertion on real numbers
rather than a smoke test: if a change to the extractor silently makes
owner attribution worse, this fails.
"""
from app.services.evaluation import TARGETS, evaluate, matches
from app.services.extraction.reference import ReferenceExtractor
from tests.conftest import FIXTURES

DATASET = FIXTURES / "labels.json"


def test_matcher_is_lenient_about_wording():
    assert matches("finish the API migration", "Rohit will finish the API migration by Friday")


def test_matcher_rejects_an_unrelated_item():
    assert not matches("finish the API migration", "Meera will send the design doc")


def test_reference_extractor_meets_the_briefs_targets():
    report = evaluate(ReferenceExtractor(), DATASET, FIXTURES)
    results = report.meets_targets()

    assert results["action_item_recall"], (
        f"recall {report.recall:.2%} < {TARGETS['action_item_recall']:.0%}; "
        f"missed: {report.as_dict()['misses']}"
    )
    assert results["action_item_precision"], f"precision {report.precision:.2%}"
    assert results["owner_accuracy"], f"owner accuracy {report.owner_accuracy:.2%}"
    assert results["date_accuracy"], f"date accuracy {report.date_accuracy:.2%}"


def test_gate_decisions_match_the_labels_exactly():
    """Every labelled item's expected eligibility must match what the
    gate actually decides -- this is the metric a judge reads as
    'unapproved actions: zero'."""
    report = evaluate(ReferenceExtractor(), DATASET, FIXTURES)
    assert report.gate_accuracy == 1.0, report.as_dict()


def test_report_serializes_for_the_evaluation_document():
    report = evaluate(ReferenceExtractor(), DATASET, FIXTURES).as_dict()
    assert report["extractor"] == "reference"
    assert set(TARGETS) <= set(report["targets"])
