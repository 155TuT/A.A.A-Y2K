"""JSON map exchange: only the mask and generator settings are persisted."""

from dataclasses import asdict
import json
from pathlib import Path

from .generation import GenerateConfig
from .model import Board, Cell


def save_map(path: str | Path, mask: frozenset[Cell], config: GenerateConfig) -> None:
    board = Board(mask)
    payload = {
        "schema_version": 1,
        "width": board.width,
        "height": board.height,
        "cells": [list(cell) for cell in sorted(mask)],
        "generation": asdict(config),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_map(path: str | Path) -> tuple[frozenset[Cell], GenerateConfig]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported map schema version")
    cells = payload["cells"]
    if not isinstance(cells, list) or any(
        not isinstance(cell, list) or len(cell) != 2 or
        any(type(coordinate) is not int for coordinate in cell)
        for cell in cells
    ):
        raise ValueError("Map coordinates must be pairs of integers")
    mask = frozenset((x, y) for x, y in cells)
    Board(mask)
    config = GenerateConfig(**payload["generation"])
    return mask, config
