"""Audit generated boards and capture all current pages with isolated fixtures."""
from __future__ import annotations
import asyncio
import hashlib
import json
import platform
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arrow_y2k.catalog import preset_maps
from arrow_y2k.generation import GenerateConfig, generate
from arrow_y2k.solver import solve, validate_certificate
from capture_pages import main as capture_pages


def audit_generation():
    masks = {p.id: p.mask for p in preset_maps()}
    masks["disconnected"] = frozenset({(0,0), (2,0), (2,1), (3,1), (5,5), (8,7)})
    records = []
    for name, mask in masks.items():
        for seed in range(5):
            config = GenerateConfig(str(seed), (.4, .75, 1)[seed % 3], 1 + seed * 4, seed / 4)
            level = generate(mask, config)
            assert validate_certificate(level.board, level.solution.order)
            independent = solve(level.board)
            assert independent.solvable and validate_certificate(level.board, independent.order)
            records.append({"template": name, "seed": seed, "cells": len(mask),
                            "occupied": len(level.board.occupancy), "arrows": len(level.board.arrows),
                            "certificate_length": len(level.solution.order)})
    return records


def main():
    records = audit_generation()
    target = ROOT / "output" / "verification"
    target.mkdir(parents=True, exist_ok=True)
    sources = sorted((ROOT / "src" / "arrow_y2k").glob("*.py"))
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "generation_cases": records,
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(records)} generated boards with independent solver replay.", flush=True)
    asyncio.run(capture_pages())


if __name__ == "__main__":
    main()
