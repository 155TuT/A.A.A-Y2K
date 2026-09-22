"""Semantic color source shared by Textual CSS and native pixel renderers.

The primary palette keeps the original full-color artwork. Monochrome display
is a presentation filter in the CRT renderer, never a second UI palette.
"""
from functools import lru_cache

TOKENS = {
    # Surfaces and typography.
    "surface": "#10171b",
    "host-surface": "#0b0e16",
    "host-text": "#f0f3f8",
    "surface-field": "#15231d",
    "surface-toast": "#172a20",
    "surface-hover": "#1c3028",
    "surface-slider": "#20302a",
    "text": "#cfdbd4",
    "text-control": "#b9c9c0",
    "text-strong": "#eef4e9",
    "text-secondary": "#c2d5c8",
    "text-subtle": "#688f7a",
    "text-help": "#789886",
    "text-credit": "#668474",
    "text-toast": "#adbdaf",
    "text-muted": "#62796c",
    "text-disabled": "#455950",
    # Shared interactive states and outlines.
    "accent": "#72d69c",
    "border": "#425f50",
    "border-focus": "#7d998a",
    "border-separator": "#30493b",
    "border-row": "#24392e",
    "border-disabled": "#2b3d33",
    "slider-hover": "#8eaa9a",
    "slider-on-hover": "#9ae6b4",
    "danger": "#c96579",
    "danger-hover": "#f07b90",
    "surface-danger": "#3a232c",
    "warning": "#d2bc6f",
    "warning-light": "#f6e099",
    "surface-warning": "#393323",
    "collision": "#d96b9e",
    # Board, life, and pixel icon materials.
    "board-tile": "#141d22",
    "board-grid": "#a7b8b6",
    "board-muted": "#2e3e43",
    "board-selected": "#254236",
    "ink": "#eff6e8",
    "heart": "#cc435f",
    "heart-shadow": "#752d42",
    "heart-light": "#f69dab",
    "icon-gold-shadow": "#6f5a31",
    "icon-play-shadow": "#2c6243",
    "icon-play-light": "#bdefc9",
    "icon-map-outline": "#68583c",
    "icon-map-paper": "#dbcda0",
    "icon-map-fold": "#b7a882",
    "icon-map-land": "#5d8959",
    "icon-map-water": "#6299a6",
    "icon-gear": "#afbebf",
    "icon-gear-shadow": "#54666b",
    "icon-gear-light": "#dbe4de",
    "icon-gear-hole": "#2d4141",
    "icon-gear-edge": "#e1e8e5",
    "brand-white": "#ffffff",
    # Native enclosure colors, kept independent from the screen filter.
    "crt-glass": "#040a0c",
    "crt-case": "#c5c4b0",
    "crt-case-light": "#e8e6d1",
    "crt-case-shadow": "#7c7e71",
    "crt-led-yellow": "#ecca4d",
    "crt-led-red": "#dc4333",
}


@lru_cache(maxsize=None)
def rgb(name: str) -> tuple[int, int, int]:
    value = TOKENS[name]
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def css_variables() -> dict[str, str]:
    """Namespaced variables injected through App.get_css_variables."""
    return {"aaa-" + name: value for name, value in TOKENS.items()}
