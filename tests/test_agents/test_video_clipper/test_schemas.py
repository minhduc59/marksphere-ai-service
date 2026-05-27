"""Unit tests for VideoClipper Pydantic schemas (segment selection validation)."""

import pytest
from pydantic import ValidationError

from app.agents.video_clipper.schemas import SegmentSelection, SelectionResult


# ── SegmentSelection ──────────────────────────────────────────────────────


def test_valid_segment_passes():
    seg = SegmentSelection(start_ms=5000, end_ms=35000, score=85.0, rationale="Strong hook.")
    assert seg.end_ms - seg.start_ms == 30000


def test_segment_rejects_end_before_start():
    with pytest.raises(ValidationError, match="end_ms"):
        SegmentSelection(start_ms=10000, end_ms=5000, score=50.0, rationale="test")


def test_segment_rejects_equal_start_and_end():
    with pytest.raises(ValidationError, match="end_ms"):
        SegmentSelection(start_ms=10000, end_ms=10000, score=50.0, rationale="test")


def test_segment_rejects_too_short():
    # 5 000 ms = 5s — below 10s minimum
    with pytest.raises(ValidationError, match="Clip too short"):
        SegmentSelection(start_ms=0, end_ms=5000, score=50.0, rationale="test")


def test_segment_rejects_too_long():
    # 91 000 ms = 91s — above 90s maximum
    with pytest.raises(ValidationError, match="Clip too long"):
        SegmentSelection(start_ms=0, end_ms=91000, score=50.0, rationale="test")


def test_segment_accepts_minimum_boundary():
    seg = SegmentSelection(start_ms=0, end_ms=10000, score=50.0, rationale="ok")
    assert (seg.end_ms - seg.start_ms) == 10000


def test_segment_accepts_maximum_boundary():
    seg = SegmentSelection(start_ms=0, end_ms=90000, score=90.0, rationale="ok")
    assert (seg.end_ms - seg.start_ms) == 90000


def test_segment_score_out_of_range_rejected():
    with pytest.raises(ValidationError):
        SegmentSelection(start_ms=0, end_ms=30000, score=101.0, rationale="test")


def test_segment_negative_score_rejected():
    with pytest.raises(ValidationError):
        SegmentSelection(start_ms=0, end_ms=30000, score=-1.0, rationale="test")


def test_segment_defaults_are_set():
    seg = SegmentSelection(start_ms=0, end_ms=15000)
    assert seg.score == 0.0
    assert seg.text == ""
    assert seg.rationale == ""
    assert seg.virality is None


# ── SelectionResult ───────────────────────────────────────────────────────


def test_selection_result_valid():
    result = SelectionResult(
        segments=[
            SegmentSelection(start_ms=0, end_ms=30000, score=90.0, rationale="good"),
            SegmentSelection(start_ms=60000, end_ms=90000, score=80.0, rationale="ok"),
        ]
    )
    assert len(result.segments) == 2


def test_selection_result_empty_list_is_valid():
    result = SelectionResult(segments=[])
    assert result.segments == []


def test_selection_result_summary_defaults_empty():
    result = SelectionResult(segments=[])
    assert result.summary == ""
