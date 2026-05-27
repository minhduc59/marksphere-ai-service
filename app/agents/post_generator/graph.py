"""Post Generation Agent — LangGraph graph assembly."""

from langgraph.graph import END, START, StateGraph

from app.agents.post_generator.nodes import (
    auto_review_node,
    content_generation_node,
    image_generation_node,
    image_prompt_creation_node,
    output_packaging_node,
    strategy_alignment_node,
)
from app.agents.post_generator.state import PostGenState


def review_router(state: PostGenState) -> str:
    """Conditional edge: route back to content_generation if posts need revision."""
    posts_to_revise = state.get("posts_to_revise", [])
    revision_count = state.get("revision_count", 0)

    if posts_to_revise and revision_count < 2:
        return "revise"
    return "package"


def build_post_gen_graph() -> StateGraph:
    """Build and compile the Post Generation LangGraph.

    Pipeline:
        START → strategy_alignment → content_generation → image_prompt_creation
              → image_generation → auto_review → [conditional: revise or package]
              → output_packaging → END

    The auto_review node routes back to content_generation if any post scores
    below 7 and revision_count < 2 (max 2 revision cycles).
    """
    graph = StateGraph(PostGenState)

    # Add nodes
    graph.add_node("strategy_alignment", strategy_alignment_node)
    graph.add_node("content_generation", content_generation_node)
    graph.add_node("image_prompt_creation", image_prompt_creation_node)
    graph.add_node("image_generation", image_generation_node)
    graph.add_node("auto_review", auto_review_node)
    graph.add_node("output_packaging", output_packaging_node)

    # Linear edges
    graph.add_edge(START, "strategy_alignment")
    graph.add_edge("strategy_alignment", "content_generation")
    graph.add_edge("content_generation", "image_prompt_creation")
    graph.add_edge("image_prompt_creation", "image_generation")
    graph.add_edge("image_generation", "auto_review")

    # Conditional edge: review loop or proceed to packaging
    graph.add_conditional_edges(
        "auto_review",
        review_router,
        {
            "revise": "content_generation",
            "package": "output_packaging",
        },
    )

    graph.add_edge("output_packaging", END)

    return graph.compile()
