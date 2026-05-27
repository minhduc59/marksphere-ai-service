"""Unit tests for caption step helper functions (no ffmpeg required)."""

import pytest

# Import private helpers directly for unit testing
from app.agents.video_clipper.steps.caption import _ms_to_ass, _hex_to_ass_color, _build_ass


# ── _ms_to_ass ────────────────────────────────────────────────────────────

class TestMsToAss:
    def test_zero(self):
        assert _ms_to_ass(0) == "0:00:00.00"

    def test_one_second(self):
        assert _ms_to_ass(1000) == "0:00:01.00"

    def test_one_minute(self):
        assert _ms_to_ass(60_000) == "0:01:00.00"

    def test_one_hour(self):
        assert _ms_to_ass(3_600_000) == "1:00:00.00"

    def test_centiseconds(self):
        # 1234 ms = 1s 234ms → 23 centiseconds
        assert _ms_to_ass(1234) == "0:00:01.23"

    def test_90_seconds(self):
        assert _ms_to_ass(90_000) == "0:01:30.00"

    def test_negative_clamped_to_zero(self):
        assert _ms_to_ass(-500) == "0:00:00.00"

    def test_complex_time(self):
        # 3723456 ms = 1h 2m 3.456s → 1h 2m 3s 45cs
        assert _ms_to_ass(3_723_456) == "1:02:03.45"


# ── _hex_to_ass_color ─────────────────────────────────────────────────────

class TestHexToAssColor:
    def test_white(self):
        assert _hex_to_ass_color("#FFFFFF") == "&H00FFFFFF"

    def test_black(self):
        assert _hex_to_ass_color("#000000") == "&H00000000"

    def test_red(self):
        # #FF0000 → BGR: 00FF → &H000000FF
        assert _hex_to_ass_color("#FF0000") == "&H000000FF"

    def test_blue(self):
        # #0000FF → BGR: FF0000 → &H00FF0000
        assert _hex_to_ass_color("#0000FF") == "&H00FF0000"

    def test_without_hash(self):
        assert _hex_to_ass_color("FFFFFF") == "&H00FFFFFF"

    def test_invalid_returns_white_fallback(self):
        assert _hex_to_ass_color("#ZZZ") == "&H00FFFFFF"

    def test_case_insensitive(self):
        assert _hex_to_ass_color("#ffffff") == "&H00ffffff"


# ── _build_ass ────────────────────────────────────────────────────────────

WORDS = [
    {"text": "Hello", "start": 1000, "end": 1500},
    {"text": "world", "start": 1600, "end": 2100},
    {"text": "this", "start": 5000, "end": 5400},
    {"text": "is", "start": 5500, "end": 5700},
    {"text": "a", "start": 5800, "end": 5900},
    {"text": "test", "start": 6000, "end": 6500},
]


class TestBuildAss:
    def test_contains_script_info_header(self):
        ass = _build_ass(WORDS, 0, 30000, 24, "#FFFFFF", "#000000", 2)
        assert "[Script Info]" in ass
        assert "PlayResX: 1080" in ass
        assert "PlayResY: 1920" in ass

    def test_contains_events_section(self):
        ass = _build_ass(WORDS, 0, 30000, 24, "#FFFFFF", "#000000", 2)
        assert "[Events]" in ass
        assert "Dialogue:" in ass

    def test_words_grouped_correctly(self):
        # 6 words → 2 groups of 3
        ass = _build_ass(WORDS, 0, 30000, 24, "#FFFFFF", "#000000", 2)
        dialogue_count = ass.count("Dialogue:")
        assert dialogue_count == 2

    def test_timestamps_are_relative_to_clip_start(self):
        # Clip starts at 1000ms — first word's timecode should be near 0:00:00.00
        ass = _build_ass(WORDS, 1000, 30000, 24, "#FFFFFF", "#000000", 2)
        # The first dialogue should start at 0:00:00.00 (1000-1000=0)
        assert "0:00:00.00" in ass

    def test_words_outside_clip_range_excluded(self):
        # Only provide word window 5000-6500 (clip 5000-7000)
        ass = _build_ass(WORDS, 5000, 7000, 24, "#FFFFFF", "#000000", 2)
        # "Hello world" (1000-2100ms) should not appear
        assert "Hello" not in ass
        assert "test" in ass

    def test_color_applied_in_style(self):
        ass = _build_ass(WORDS, 0, 30000, 24, "#FF0000", "#000000", 2)
        # Red in ASS BGR is &H000000FF
        assert "&H000000FF" in ass

    def test_font_size_applied(self):
        ass = _build_ass(WORDS, 0, 30000, 32, "#FFFFFF", "#000000", 2)
        assert ",32," in ass

    def test_empty_word_list_produces_empty_dialogue(self):
        ass = _build_ass([], 0, 30000, 24, "#FFFFFF", "#000000", 2)
        assert "Dialogue:" not in ass
