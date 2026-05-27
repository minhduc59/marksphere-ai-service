"""Step 3: Use LLM to select the best viral clip segments."""
from __future__ import annotations

import json
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.video_clipper.prompts import (
    TRANSCRIPT_ANALYSIS_SYSTEM_PROMPT,
    build_transcript_user_message,
)
from app.agents.video_clipper.schemas import SelectionResult
from app.clients.openai_client import get_analyzer_llm

logger = structlog.get_logger()


def _parse_json(content: str) -> dict:
    """Extract JSON from LLM response, stripping optional markdown fences."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content.strip())


async def run(
    transcript_data: dict[str, Any],
    max_clips: int,
    start_time_s: float = 0.0,
    end_time_s: float = 0.0,
) -> list[dict]:
    """Call LLM to select viral segments.

    start_time_s / end_time_s are passed through when the source was NOT
    pre-trimmed (currently always 0 since download.py trims before this step).
    Kept as params for future use and as a belt-and-suspenders guard.

    Returns a list of validated segment dicts (up to max_clips), sorted by score descending.
    Raises RuntimeError if no valid segments are returned.
    """
    duration_ms = transcript_data.get("duration_ms", 0)

    words = transcript_data.get("words", [])
    if not words:
        raise RuntimeError("Transcript has no words — cannot select segments")

    # Belt-and-suspenders: if the video was not pre-trimmed, filter words here
    if start_time_s > 0 or end_time_s > 0:
        start_ms = int(start_time_s * 1000)
        end_ms = int(end_time_s * 1000) if end_time_s > 0 else None
        words = [
            w for w in words
            if w.get("end", 0) >= start_ms and (end_ms is None or w.get("start", 0) <= end_ms)
        ]
        if not words:
            raise RuntimeError("No transcript content in the selected time range")
        transcript_data = {**transcript_data, "words": words}

    if not transcript_data.get("words"):
        raise RuntimeError("Transcript has no words — cannot select segments")

    user_message = build_transcript_user_message(transcript_data, max_clips, duration_ms)
    messages = [
        SystemMessage(content=TRANSCRIPT_ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    llm = get_analyzer_llm()
    response = await llm.ainvoke(messages)
    raw = _parse_json(response.content)

    try:
        result = SelectionResult.model_validate(raw)
    except (ValidationError, ValueError) as e:
        logger.error("select: LLM response failed validation", error=str(e), raw=str(raw)[:500])
        raise RuntimeError(f"LLM segment selection failed validation: {e}") from e

    # Sort by score descending, cap to requested max
    segments = sorted(result.segments, key=lambda s: s.score, reverse=True)[:max_clips]

    if not segments:
        raise RuntimeError("LLM returned zero valid segments")

    logger.info("select: done", segments=len(segments))
    return [s.model_dump() for s in segments]
