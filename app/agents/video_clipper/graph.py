"""LangGraph graph for the Video Clipper Agent.

Single-node graph: START → video_clipper → END.
All pipeline logic lives inside video_clipper_node.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.video_clipper.node import video_clipper_node
from app.agents.video_clipper.state import VideoClipperState


def build_video_clipper_graph() -> StateGraph:
    graph = StateGraph(VideoClipperState)
    graph.add_node("video_clipper", video_clipper_node)
    graph.add_edge(START, "video_clipper")
    graph.add_edge("video_clipper", END)
    return graph.compile()
