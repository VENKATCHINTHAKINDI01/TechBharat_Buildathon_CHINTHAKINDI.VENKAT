"""F015 -- dedupe key properties."""
from app.services.idempotency import compute_dedupe_key, normalize_text


def test_normalization_ignores_case_punctuation_and_spacing():
    assert normalize_text("Send the design doc.") == normalize_text("send   THE design doc")


def test_same_inputs_produce_the_same_key():
    a = compute_dedupe_key("m1", "p-rohit", "Finish the API migration")
    b = compute_dedupe_key("m1", "p-rohit", "finish the api migration!")
    assert a == b


def test_different_owner_produces_a_different_key():
    a = compute_dedupe_key("m1", "p-rohit", "Finish the API migration")
    b = compute_dedupe_key("m1", "p-meera", "Finish the API migration")
    assert a != b


def test_different_meeting_produces_a_different_key():
    a = compute_dedupe_key("m1", "p-rohit", "Finish the API migration")
    b = compute_dedupe_key("m2", "p-rohit", "Finish the API migration")
    assert a != b


def test_unresolved_owner_is_stable():
    a = compute_dedupe_key("m1", None, "Finish it")
    b = compute_dedupe_key("m1", None, "finish it")
    assert a == b


def test_key_is_a_sha256_hex_digest():
    key = compute_dedupe_key("m1", "p-rohit", "x")
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)
