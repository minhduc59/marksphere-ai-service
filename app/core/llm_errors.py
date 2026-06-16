"""Shared classification of LLM (OpenAI) error strings.

Maps a raw exception string to a concise, user-facing detail and a
fatal/transient flag. *Fatal* errors are config/billing problems that will not
succeed on retry (invalid key, exhausted quota); transient ones (rate limit,
timeout) may. Used by both the post-generation runner and the trend analyzer so
the two surface the same wording and make the same retry decision.
"""


def classify_llm_error(raw: str) -> tuple[str, bool]:
    """Return ``(user_facing_detail, is_fatal)`` for an LLM error string."""
    r = (raw or "").lower()
    if "insufficient_quota" in r or "exceeded your current quota" in r:
        return "OpenAI quota exceeded — check your API billing plan", True
    if "invalid_api_key" in r or "api key" in r or "401" in r:
        return "Invalid OpenAI API key", True
    if "rate_limit" in r or "429" in r:
        return "OpenAI rate limit hit — try again in a few minutes", False
    if "timeout" in r or "timed out" in r:
        return "Request timed out — try again", False
    return (
        "An unexpected error occurred. Please try again later or contact your "
        "administrator for support."
    ), False
