"""Unit tests for runner.run_publish_pipeline error-handling paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.publish_post import runner


def _fake_graph(result_or_exc):
    graph = MagicMock()
    if isinstance(result_or_exc, Exception):
        graph.ainvoke = AsyncMock(side_effect=result_or_exc)
    else:
        graph.ainvoke = AsyncMock(return_value=result_or_exc)
    return graph


@pytest.mark.asyncio
async def test_runner_returns_failed_on_unhandled_exception():
    pub_id = "8a52a55b-1111-4111-8111-111111111111"

    with (
        patch.object(runner, "build_publish_graph",
                     return_value=_fake_graph(RuntimeError("boom"))),
        patch.object(runner, "mark_publish_failed", AsyncMock()) as marker,
    ):
        result = await runner.run_publish_pipeline(
            content_post_id="cp-1",
            published_post_id=pub_id,
        )

    assert result["publish_status"] == "failed"
    assert result["error"] == "boom"
    assert result["published_post_id"] == pub_id
    marker.assert_awaited_once()
    assert marker.await_args.kwargs["published_post_id"] == pub_id
    assert marker.await_args.kwargs["stage"] == "pipeline"


@pytest.mark.asyncio
async def test_runner_logs_failed_when_graph_returns_failed_status():
    fake_state = {
        "publish_status": "failed",
        "published_post_id": "pub-2",
        "provider_post_id": "",
        "error": "Backend HTTP 401",
    }
    with patch.object(runner, "build_publish_graph",
                      return_value=_fake_graph(fake_state)):
        with patch.object(runner.logger, "info") as info_log, \
                patch.object(runner.logger, "error") as error_log:
            result = await runner.run_publish_pipeline(
                content_post_id="cp-2",
                published_post_id="pub-2",
            )

    assert result["publish_status"] == "failed"
    # The misleading "publish_pipeline: completed" log must NOT fire on failure.
    completed_calls = [
        c for c in info_log.call_args_list
        if c.args and c.args[0] == "publish_pipeline: completed"
    ]
    assert completed_calls == []
    failed_calls = [
        c for c in error_log.call_args_list
        if c.args and c.args[0] == "publish_pipeline: failed"
    ]
    assert len(failed_calls) == 1


@pytest.mark.asyncio
async def test_runner_logs_completed_on_success():
    fake_state = {
        "publish_status": "processing",
        "published_post_id": "pub-3",
        "provider_post_id": "zernio-123",
        "error": "",
    }
    with patch.object(runner, "build_publish_graph",
                      return_value=_fake_graph(fake_state)):
        with patch.object(runner.logger, "info") as info_log:
            result = await runner.run_publish_pipeline(
                content_post_id="cp-3",
                published_post_id="pub-3",
            )

    assert result["publish_status"] == "processing"
    completed_calls = [
        c for c in info_log.call_args_list
        if c.args and c.args[0] == "publish_pipeline: completed"
    ]
    assert len(completed_calls) == 1
