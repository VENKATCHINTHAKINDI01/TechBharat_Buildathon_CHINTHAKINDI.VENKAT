"""Code-switch normalization and composite confidence."""
import pytest

from app.core.config import Settings
from app.domain.models import (
    DateResolutionMethod,
    OwnerResolutionMethod,
    TranscriptSegment,
)
from app.services.confidence import compute_confidence
from app.services.normalization import NullNormalizer, SarvamNormalizer, build_normalizer

# --- normalization ---------------------------------------------------------


def test_detects_telugu_script():
    assert SarvamNormalizer.looks_code_switched("Yes, Monday morning ki పంపిస్తాను.")


def test_detects_romanized_code_switching():
    assert SarvamNormalizer.looks_code_switched(
        "Priya, deployment checklist complete chesi Monday varaku share chesthava?"
    )


def test_plain_english_is_not_sent_for_translation():
    assert not SarvamNormalizer.looks_code_switched(
        "Rohit, can you finish the API migration by Friday?"
    )


async def test_normalization_never_replaces_the_original_text():
    """The whole safety argument depends on this."""

    class StubClient:
        def translate(self, **_kwargs):
            class R:
                translated_text = "Yes, I will send it by Monday morning."

            return R()

    segments = [
        TranscriptSegment(segment_id="s0", speaker="Priya", text="Monday morning ki పంపిస్తాను.")
    ]
    out = await SarvamNormalizer(Settings(sarvam_api_key="k"), client=StubClient()).normalize(segments)

    assert out[0].text == "Monday morning ki పంపిస్తాను."  # untouched
    assert out[0].normalized_text == "Yes, I will send it by Monday morning."
    assert out[0].extraction_text == out[0].normalized_text


async def test_translation_failure_degrades_to_the_original():
    class Exploding:
        def translate(self, **_kwargs):
            raise RuntimeError("sarvam down")

    segments = [TranscriptSegment(segment_id="s0", speaker="P", text="Monday varaku share chesthava?")]
    out = await SarvamNormalizer(Settings(sarvam_api_key="k"), client=Exploding()).normalize(segments)

    assert out[0].normalized_text is None
    assert out[0].extraction_text == out[0].text


async def test_null_normalizer_is_a_true_no_op():
    segments = [TranscriptSegment(segment_id="s0", speaker="A", text="hello")]
    assert await NullNormalizer().normalize(segments) == segments


def test_build_normalizer_picks_null_without_a_key():
    assert build_normalizer(Settings(sarvam_api_key="")).name == "none"
    assert build_normalizer(Settings(sarvam_api_key="k")).name == "sarvam"


# --- confidence ------------------------------------------------------------


def test_perfect_resolution_scores_near_the_extraction_confidence():
    score = compute_confidence(
        extraction_confidence=0.9,
        owner_method=OwnerResolutionMethod.exact_match,
        date_method=DateResolutionMethod.relative,
        date_was_claimed=True,
    )
    assert score == pytest.approx(0.95, abs=0.01)


def test_unresolved_owner_drags_the_score_below_the_default_threshold():
    score = compute_confidence(
        extraction_confidence=0.9,
        owner_method=OwnerResolutionMethod.unresolved,
        date_method=DateResolutionMethod.relative,
        date_was_claimed=True,
    )
    assert score < 0.75


def test_fuzzy_owner_scores_below_an_exact_match():
    kwargs = dict(
        extraction_confidence=0.9,
        date_method=DateResolutionMethod.relative,
        date_was_claimed=True,
    )
    fuzzy = compute_confidence(owner_method=OwnerResolutionMethod.fuzzy_match, **kwargs)
    exact = compute_confidence(owner_method=OwnerResolutionMethod.exact_match, **kwargs)
    assert fuzzy < exact


def test_no_date_claimed_is_not_penalised():
    """Nothing was promised, so nothing was got wrong."""
    score = compute_confidence(
        extraction_confidence=0.9,
        owner_method=OwnerResolutionMethod.exact_match,
        date_method=DateResolutionMethod.unresolved,
        date_was_claimed=False,
    )
    assert score == pytest.approx(0.95, abs=0.01)


def test_a_claimed_but_unresolvable_date_is_penalised():
    score = compute_confidence(
        extraction_confidence=0.9,
        owner_method=OwnerResolutionMethod.exact_match,
        date_method=DateResolutionMethod.unresolved,
        date_was_claimed=True,
    )
    assert score < 0.85


def test_score_is_clamped_into_range():
    assert compute_confidence(
        extraction_confidence=5.0,
        owner_method=OwnerResolutionMethod.exact_match,
        date_method=DateResolutionMethod.absolute,
        date_was_claimed=True,
    ) == 1.0
