"""Tests for wiring the From Article URL flow into the review/publish hook.

Covers the two genuinely new pieces:

1. ``_resolve_article_cfg`` — per-request override → saved config → default
   precedence used to build the pipeline-config dict for an article run.
2. ``apply_review_and_publish`` — the shared hook (extracted from the
   HackerNews supervisor) now also driven by the article pipeline. Proves the
   review-gate and auto-publish behave the same regardless of caller.

The DB session and ``run_publish_pipeline`` are faked so the wiring is
exercised without Postgres/Redis/TikTok.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from app.agents.supervisor import apply_review_and_publish
from app.db.models.content_post import ContentPost
from app.db.models.enums import ContentStatus
from app.services.article_pipeline import _resolve_article_cfg


# --------------------------------------------------------------------------- #
# Fake async session that serves one payload and is also an async ctx manager.
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, payload):
        self._payload = payload

    def scalar_one_or_none(self):
        return self._payload

    def scalars(self):
        return self

    def all(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload

    async def execute(self, _stmt):
        return _FakeResult(self._payload)

    async def commit(self):
        pass


class _FakeFactory:
    def __init__(self, payload):
        self.session = _FakeSession(payload)

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_a):
        return False


def _draft(score: float, *, image: bool) -> ContentPost:
    return ContentPost(
        id=uuid.uuid4(),
        scan_run_id=uuid.uuid4(),
        status=ContentStatus.DRAFT,
        review_score=score,
        image_path="https://cdn/x.png" if image else None,
    )


# --------------------------------------------------------------------------- #
# 1. _resolve_article_cfg precedence
# --------------------------------------------------------------------------- #
def test_resolve_cfg_override_beats_config():
    cfg = {
        "require_review": False,
        "auto_approve_threshold": 6.0,
        "auto_publish": True,
        "publish_mode": "auto",
        "scheduled_publish_time": None,
        "default_privacy_level": "PUBLIC_TO_EVERYONE",
    }
    resolved = _resolve_article_cfg(cfg, {"require_review": True, "privacy_level": "SELF_ONLY"})
    # Explicit override wins...
    assert resolved["require_review"] is True
    assert resolved["default_privacy_level"] == "SELF_ONLY"
    # ...unset fields fall back to the saved config.
    assert resolved["auto_publish"] is True
    assert resolved["auto_approve_threshold"] == 6.0


def test_resolve_cfg_defaults_when_no_config_or_overrides():
    assert _resolve_article_cfg(None, None) == {
        "require_review": True,
        "auto_approve_threshold": 7.0,
        "auto_publish": False,
        "publish_mode": "auto",
        "scheduled_publish_time": None,
        "default_privacy_level": "SELF_ONLY",
    }


# --------------------------------------------------------------------------- #
# 2. apply_review_and_publish driven by the article-path config
# --------------------------------------------------------------------------- #
async def test_require_review_short_circuits():
    posts = [_draft(9.0, image=True)]
    with patch("app.agents.supervisor.async_session_factory", _FakeFactory(posts)), patch(
        "app.agents.publish_post.runner.run_publish_pipeline", new=AsyncMock()
    ) as pub:
        await apply_review_and_publish(
            str(uuid.uuid4()), {"require_review": True}, str(uuid.uuid4())
        )
    assert posts[0].status == ContentStatus.DRAFT  # untouched
    pub.assert_not_called()


async def test_auto_approve_and_publish_when_review_off():
    good = _draft(8.0, image=True)
    imageless = _draft(9.0, image=False)
    low = _draft(4.0, image=True)
    posts = [good, imageless, low]

    pub = AsyncMock(return_value={"publish_status": "scheduled"})
    with patch("app.agents.supervisor.async_session_factory", _FakeFactory(posts)), patch(
        "app.agents.publish_post.runner.run_publish_pipeline", new=pub
    ):
        await apply_review_and_publish(
            str(uuid.uuid4()),
            {"require_review": False, "auto_approve_threshold": 7.0, "auto_publish": True},
            str(uuid.uuid4()),
        )

    assert good.status == ContentStatus.APPROVED
    assert imageless.status == ContentStatus.FLAGGED_FOR_REVIEW  # image mandatory
    assert low.status == ContentStatus.DRAFT  # below threshold
    # Only the approved (scored + imaged) post is published.
    pub.assert_awaited_once()
    assert pub.await_args.kwargs["content_post_id"] == str(good.id)
