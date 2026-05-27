"""Unit tests for app.agents.publish_post.failure_handler."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.publish_post import failure_handler
from app.db.models.enums import PublishStatus


class _FakePub:
    def __init__(self) -> None:
        self.status = PublishStatus.PROCESSING
        self.error_message: str | None = None
        self.retry_count = 0


def _fake_session(pub: _FakePub | None):
    """Build an async-context-manager-compatible fake DB session."""

    db = MagicMock()
    db.commit = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=pub)
    db.execute = AsyncMock(return_value=scalar_result)

    @asynccontextmanager
    async def factory():
        yield db

    return factory, db


@pytest.mark.asyncio
async def test_mark_publish_failed_updates_row_and_notifies(monkeypatch):
    pub = _FakePub()
    factory, db = _fake_session(pub)
    monkeypatch.setattr(failure_handler, "async_session_factory", factory)

    posted: list[dict] = []

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            posted.append({"url": url, **kwargs})
            response = MagicMock()
            response.raise_for_status = MagicMock()
            return response

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    pub_id = str(uuid.uuid4())
    await failure_handler.mark_publish_failed(
        published_post_id=pub_id,
        error_message="Backend HTTP 401: Invalid internal API key",
        stage="publish",
    )

    assert pub.status == PublishStatus.FAILED
    assert pub.error_message == "Backend HTTP 401: Invalid internal API key"
    assert db.commit.await_count == 1
    assert len(posted) == 1
    assert posted[0]["url"].endswith("/v1/publisher/internal/notify-status")
    body = posted[0]["json"]
    assert body["publishedPostId"] == pub_id
    assert body["status"] == "failed"
    assert body["stage"] == "publish"


@pytest.mark.asyncio
async def test_notify_failure_does_not_mask_pipeline_failure(monkeypatch):
    pub = _FakePub()
    factory, db = _fake_session(pub)
    monkeypatch.setattr(failure_handler, "async_session_factory", factory)

    class _BrokenClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("backend unreachable")

    monkeypatch.setattr(httpx, "AsyncClient", _BrokenClient)

    pub_id = str(uuid.uuid4())
    # Must not raise even though the notify call blew up.
    await failure_handler.mark_publish_failed(
        published_post_id=pub_id,
        error_message="upstream broke",
        stage="publish",
    )

    assert pub.status == PublishStatus.FAILED
    assert pub.error_message == "upstream broke"


@pytest.mark.asyncio
async def test_mark_publish_failed_truncates_long_error(monkeypatch):
    pub = _FakePub()
    factory, _ = _fake_session(pub)
    monkeypatch.setattr(failure_handler, "async_session_factory", factory)

    with patch.object(failure_handler, "_notify_backend", AsyncMock()):
        await failure_handler.mark_publish_failed(
            published_post_id=str(uuid.uuid4()),
            error_message="x" * 5000,
            stage="publish",
        )

    assert pub.error_message is not None
    assert len(pub.error_message) == 2000


@pytest.mark.asyncio
async def test_mark_publish_failed_handles_missing_row(monkeypatch):
    factory, db = _fake_session(None)
    monkeypatch.setattr(failure_handler, "async_session_factory", factory)

    with patch.object(failure_handler, "_notify_backend", AsyncMock()) as notify:
        await failure_handler.mark_publish_failed(
            published_post_id=str(uuid.uuid4()),
            error_message="oops",
            stage="publish",
        )

    # No row to update → no commit, but notify still fires.
    db.commit.assert_not_awaited()
    notify.assert_awaited_once()
