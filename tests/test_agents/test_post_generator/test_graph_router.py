"""Tests for the post-gen graph's strategy short-circuit router."""

from app.agents.post_generator.graph import build_post_gen_graph, strategy_router


def test_skip_when_no_content_plan() -> None:
    """A fatal strategy failure (empty plan, not a revision) skips generation."""
    assert strategy_router({"content_plan": [], "posts_to_revise": []}) == "skip"


def test_generate_when_plan_present() -> None:
    assert (
        strategy_router({"content_plan": [{"angle": "x"}], "posts_to_revise": []})
        == "generate"
    )


def test_revision_pass_still_generates_without_plan() -> None:
    """An empty plan during a revision pass must not be treated as a failure."""
    assert (
        strategy_router({"content_plan": [], "posts_to_revise": ["post-1"]})
        == "generate"
    )


def test_graph_compiles() -> None:
    assert build_post_gen_graph() is not None
