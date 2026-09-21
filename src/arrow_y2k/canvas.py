"""Shared bounds for editable, imported, and saved game canvases."""
from collections.abc import Iterable
from .model import Cell

CANVAS_WIDTH = 20
CANVAS_HEIGHT = 16


def validate_canvas(cells: Iterable[Cell]) -> None:
    """Validate cell coordinates; emptiness and occupancy remain Board rules."""
    for cell in cells:
        if not isinstance(cell, (tuple, list)) or len(cell) != 2 or any(type(v) is not int for v in cell):
            raise ValueError("Canvas coordinates must be pairs of integers")
        x, y = cell
        if not 0 <= x < CANVAS_WIDTH or not 0 <= y < CANVAS_HEIGHT:
            raise ValueError(f"Canvas coordinates must fit {CANVAS_WIDTH} by {CANVAS_HEIGHT} cells")
