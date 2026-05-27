"""Unit tests for the human feedback classifier."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.post_generator.nodes import feedback_classifier


def _fake_response(payload: dict | str):
    """Wrap a dict or raw string in a ``response.content`` shape matching ChatOpenAI."""
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(content=content)


def _patch_llm(response):
    mock_llm = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
    return patch(
        "app.agents.post_generator.nodes.feedback_classifier.get_review_llm",
        return_value=mock_llm,
    )


SAMPLE_POST = {
    "caption": "AI is rewriting how teams ship software.",
    "hashtags": ["#fyp", "#techtok"],
    "cta": "Save this for later",
    "image_prompt": {"prompt": "neon developer at a glowing terminal"},
}


@pytest.mark.asyncio
async def test_content_only_feedback_routes_to_content():
    with _patch_llm(
        _fake_response(
            {
                "regenerate_content": True,
                "regenerate_image": False,
                "reasoning": "wording change",
            }
        )
    ):
        result = await feedback_classifier.classify_feedback(
            "Make the caption shorter and punchier", SAMPLE_POST
        )
    assert result["regenerate_content"] is True
    assert result["regenerate_image"] is False


@pytest.mark.asyncio
async def test_image_only_feedback_routes_to_image():
    with _patch_llm(
        _fake_response(
            {
                "regenerate_content": False,
                "regenerate_image": True,
                "reasoning": "visual change",
            }
        )
    ):
        result = await feedback_classifier.classify_feedback(
            "The photo is too dark — make it more vibrant", SAMPLE_POST
        )
    assert result["regenerate_content"] is False
    assert result["regenerate_image"] is True


@pytest.mark.asyncio
async def test_mixed_feedback_routes_to_both():
    with _patch_llm(
        _fake_response(
            {
                "regenerate_content": True,
                "regenerate_image": True,
                "reasoning": "rewrite both",
            }
        )
    ):
        result = await feedback_classifier.classify_feedback(
            "Rewrite the hook AND use a totally different photo style",
            SAMPLE_POST,
        )
    assert result["regenerate_content"] is True
    assert result["regenerate_image"] is True


@pytest.mark.asyncio
async def test_both_false_is_promoted_to_both_true():
    # Defensive invariant: at least one target must be true.
    with _patch_llm(
        _fake_response(
            {
                "regenerate_content": False,
                "regenerate_image": False,
                "reasoning": "n/a",
            }
        )
    ):
        result = await feedback_classifier.classify_feedback(
            "redo", SAMPLE_POST
        )
    assert result["regenerate_content"] is True
    assert result["regenerate_image"] is True


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_parsed():
    fenced = "```json\n{\"regenerate_content\": true, \"regenerate_image\": false, \"reasoning\": \"x\"}\n```"
    with _patch_llm(_fake_response(fenced)):
        result = await feedback_classifier.classify_feedback("change copy", SAMPLE_POST)
    assert result["regenerate_content"] is True
    assert result["regenerate_image"] is False


@pytest.mark.asyncio
async def test_unparsable_response_falls_back_to_content_only():
    with _patch_llm(_fake_response("definitely not json")):
        result = await feedback_classifier.classify_feedback("change something", SAMPLE_POST)
    # Fallback policy: content-only.
    assert result["regenerate_content"] is True
    assert result["regenerate_image"] is False
    assert "Fallback" in result["reasoning"]


@pytest.mark.asyncio
async def test_empty_feedback_short_circuits_without_calling_llm():
    with _patch_llm(_fake_response("ignored")) as patched:
        result = await feedback_classifier.classify_feedback("   ", SAMPLE_POST)
    assert result["regenerate_content"] is True
    assert result["regenerate_image"] is False
    # The LLM should not have been invoked for empty input.
    patched.return_value.ainvoke.assert_not_called()
