"""Reproducible visual and logical audit, independent of an external GUI driver."""
from __future__ import annotations

import asyncio
import hashlib
import json
import platform
from pathlib import Path
from time import monotonic

from PIL import Image
from arrow_y2k.app import ArrowApp
from arrow_y2k.desktop import RESOLUTIONS, compose_frame, configure_native_colors
from arrow_y2k.generation import GenerateConfig, generate, template_mask
from arrow_y2k.pixels import Animation
from arrow_y2k.solver import validate_certificate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "verification"


async def snapshots() -> list[dict]:
    records = []
    for resolution_name, resolution in RESOLUTIONS.items():
        for index in (1, 2, 3):
            app = ArrowApp(native=True, level=index)
            app.resolution_name = resolution_name
            configure_native_colors(app)
            async with app.run_test(size=resolution.terminal_size) as pilot:
                await pilot.pause()
                frame = compose_frame(app, resolution.logical_size)
                target = OUT / f"level-{index}-{resolution_name}.png"
                frame.resize((resolution.width, resolution.height), Image.Resampling.NEAREST).save(target)
                records.append({"level": index, "resolution": resolution_name,
                                "capture": "Textual compositor", "file": target.name,
                                "arrows": len(app.session.remaining),
                                "solvable": app.level.solution.solvable})
    app = ArrowApp(native=True)
    configure_native_colors(app)
    async with app.run_test(size=(106, 30)) as pilot:
        await pilot.pause()
        blocked = next(a for a in app.session.board.arrows if app.session.board.first_collision(a.id))
        app.play_arrow(blocked.id)
        app.animation = Animation(blocked, "collision", .48, app.animation.collision_distance)
        app.animation_started = monotonic() - app.animation_duration * .48
        app.heart_started = monotonic() - .35
        app.heart_progress = .5
        compose_frame(app, (640, 360)).resize((1280, 720), Image.Resampling.NEAREST).save(OUT / "collision-heartbreak.png")
        app.action_restart()
        for _ in range(3):
            app.play_arrow(blocked.id)
            app.animation_started -= 2
            app.tick()
        app.heart_started = monotonic() - 2
        app.tick()
        await pilot.pause()
        compose_frame(app, (640, 360)).resize((1280, 720), Image.Resampling.NEAREST).save(OUT / "game-over.png")
        app.action_restart()
        for arrow_id in app.level.solution.order:
            app.play_arrow(arrow_id)
            app.animation_started -= 2
            app.tick()
        assert app.session.status == "won" and app.session.lives == 3
        await pilot.pause()
        compose_frame(app, (640, 360)).resize((1280, 720), Image.Resampling.NEAREST).save(OUT / "level-complete.png")
        app.action_editor()
        await pilot.pause()
        compose_frame(app, (640, 360)).resize((1280, 720), Image.Resampling.NEAREST).save(OUT / "map-studio.png")
    return records


def audit_generation() -> list[dict]:
    records = []
    masks = {key: template_mask(key, 9, 8) for key in ("square", "rectangle", "heart", "diamond", "ring", "cross")}
    masks["disconnected"] = frozenset({(0, 0), (2, 0), (2, 1), (3, 1), (5, 5), (8, 7)})
    for name, mask in masks.items():
        for seed in range(30):
            config = GenerateConfig(str(seed), (0.4, 0.75, 1.0)[seed % 3], 1 + seed % 15, (seed % 5) / 4)
            level = generate(mask, config)
            assert validate_certificate(level.board, level.solution.order)
            records.append({"mask": name, "seed": seed, "occupied": len(level.board.occupancy),
                            "arrows": len(level.board.arrows), "certificate_length": len(level.solution.order)})
    return records


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records = asyncio.run(snapshots())
    generation = audit_generation()
    source_files = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "src").rglob("*.tcss"))
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "captures": records, "generation_cases": generation,
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}}
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(generation)} generated boards; saved 13 visual states and source hashes to {OUT}")


if __name__ == "__main__":
    main()
