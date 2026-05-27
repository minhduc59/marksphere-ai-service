"""Bundled font catalog for the Video Clipper Agent.

The 21 TTF files live at ai-service/assets/fonts/. The dict below maps a
stable, user-facing key (passed in from the frontend) to (filename, ASS
Fontname). ASS Fontname must match the family name embedded in the TTF, or
ffmpeg/libass falls back to a default — keep these aligned with the actual
font tables.
"""
from __future__ import annotations

from pathlib import Path

# Project root is .../ai-service/ ; this file lives at .../ai-service/app/agents/video_clipper/fonts.py
FONTS_DIR: Path = Path(__file__).resolve().parents[3] / "assets" / "fonts"


# key  →  (filename, ASS Fontname)
FONT_CATALOG: dict[str, tuple[str, str]] = {
    "Inter":              ("Inter.ttf",                      "Inter"),
    "Roboto":             ("Roboto.ttf",                     "Roboto"),
    "Anton":              ("Anton-Regular.ttf",              "Anton"),
    "Archivo Black":      ("ArchivoBlack-Regular.ttf",       "Archivo Black"),
    "Bangers":            ("Bangers-Regular.ttf",            "Bangers"),
    "Barlow Condensed":   ("BarlowCondensed-Bold.ttf",       "Barlow Condensed"),
    "Bebas Neue":         ("BebasNeue-Regular.ttf",          "Bebas Neue"),
    "DM Sans":            ("DMSans.ttf",                     "DM Sans"),
    "League Spartan":     ("LeagueSpartan.ttf",              "League Spartan"),
    "Montserrat":         ("Montserrat-Variable-wght.ttf",   "Montserrat"),
    "Nunito Sans":        ("NunitoSans.ttf",                 "Nunito Sans"),
    "Open Sans":          ("OpenSans.ttf",                   "Open Sans"),
    "Oswald":             ("Oswald-Variable-wght.ttf",       "Oswald"),
    "Poppins":            ("Poppins-ExtraBold.ttf",          "Poppins"),
    "Raleway":            ("Raleway-Variable-wght.ttf",      "Raleway"),
    "Rubik":              ("Rubik.ttf",                      "Rubik"),
    "Sora":               ("Sora.ttf",                       "Sora"),
    "The Bold Font":      ("THEBOLDFONT.ttf",                "THE BOLD FONT"),
    "TikTok Sans":        ("TikTokSans-Regular.ttf",         "TikTok Sans"),
    "Urbanist":           ("Urbanist.ttf",                   "Urbanist"),
    "Work Sans":          ("WorkSans.ttf",                   "Work Sans"),
}


DEFAULT_FONT_KEY = "Inter"


def resolve_font(family_key: str) -> tuple[Path, str]:
    """Return (fontsdir_path, ass_fontname) for the given family key.

    Falls back to the default font if the key is unknown — never raises,
    because a bad font name shouldn't kill the entire pipeline.
    """
    entry = FONT_CATALOG.get(family_key) or FONT_CATALOG[DEFAULT_FONT_KEY]
    filename, ass_fontname = entry
    return FONTS_DIR / filename, ass_fontname
