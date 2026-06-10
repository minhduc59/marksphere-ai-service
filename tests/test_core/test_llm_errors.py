"""Tests for the shared LLM-error classifier."""

from app.core.llm_errors import classify_llm_error


def test_invalid_api_key_is_fatal() -> None:
    detail, fatal = classify_llm_error(
        "Error code: 401 - {'error': {'message': 'invalid_api_key'}}"
    )
    assert detail == "Invalid OpenAI API key"
    assert fatal is True


def test_quota_is_fatal() -> None:
    _, fatal = classify_llm_error("insufficient_quota: exceeded your current quota")
    assert fatal is True


def test_rate_limit_is_transient() -> None:
    detail, fatal = classify_llm_error("rate_limit_exceeded (429)")
    assert fatal is False
    assert "rate limit" in detail.lower()


def test_timeout_is_transient() -> None:
    _, fatal = classify_llm_error("request timed out")
    assert fatal is False


def test_unknown_is_transient() -> None:
    detail, fatal = classify_llm_error("connection reset by peer")
    assert fatal is False
    assert "unexpected error" in detail.lower()


def test_empty_input_is_safe() -> None:
    detail, fatal = classify_llm_error("")
    assert fatal is False
    assert detail
