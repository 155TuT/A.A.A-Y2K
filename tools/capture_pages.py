"""Capture current Textual pages, using disposable synthetic UI fixtures.

Run from any directory: python tools/capture_pages.py [--output PATH].
This writes screenshots only; it never opens or changes the real player data.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image
from arrow_y2k.app import ArrowApp
from arrow_y2k.campaign import GameRun
from arrow_y2k.desktop import RESOLUTIONS, compose_frame, configure_native_colors
from arrow_y2k.solver import solve


class CaptureClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


async def capture_resolution(name, output, fixture_root):
    preset = RESOLUTIONS[name]
    clock = CaptureClock()
    app = ArrowApp(native=True, data_dir=fixture_root / name, clock=clock, seed="capture-pages-2026")
    app.store.settings.muted = True
    app.audio.configure(.65, .7, True)
    app.store.profile.unlocked_modes.update(("medium", "hard", "endless"))
    configure_native_colors(app)
    records = []
    async with app.run_test(size=preset.terminal_size) as pilot:
        async def snap(label):
            await pilot.pause()
            frame = compose_frame(app, preset.logical_size)
            image = frame.resize((preset.width, preset.height), Image.Resampling.NEAREST)
            path = output / f"{name}-{label}.png"
            image.save(path)
            record = {"image": path.name, "page": app.page, "size": list(image.size),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            if app.game is not None:
                record["game"] = {"mode": app.game.mode, "level": app.game.level_index,
                                  "cells": len(app.session.board.mask), "lives": app.session.lives,
                                  "left": len(app.session.remaining), "seed": app.game.seed}
            if app.animation is not None:
                record["animation"] = {"kind": app.animation.kind, "progress": app.animation.progress,
                                       "heart_progress": app.heart_progress}
            records.append(record)

        await snap("home")
        app.route("difficulty")
        await snap("difficulty")
        # Complete the first two generated tutorials through the real UI
        # controller, then capture the third. Clock injection makes animation
        # sampling deterministic; no board or life values are fabricated.
        app.start_game("easy")
        await pilot.pause()
        for index in (1, 2, 3):
            await snap(f"tutorial-{index}")
            if index == 1:
                blocked_tutorial = next(a.id for a in app.session.current_board.arrows
                                        if app.session.current_board.first_collision(a.id) is not None)
                app.play_arrow(blocked_tutorial)
                clock.now += .40
                app.tick()
                await snap("collision-shake")
                clock.now += .34
                app.tick()
                await snap("heart-fragments")
                clock.now += .35
                app.tick()
                await pilot.pause()
            if index < 3:
                for arrow_id in solve(app.session.current_board).order:
                    app.play_arrow(arrow_id)
                    clock.now += .70
                    app.tick()
                    await pilot.pause()
                assert app.page == "result" and app.game.outcome == "level_won"
                app.dispatch("next-level")
                await pilot.pause()
        app.start_game("hard")
        await snap("game-hard")
        # Build the five summary rows from legal game-state changes. These are
        # disposable fixtures, never claims about a real player's performance.
        app.store.save_slot(0, app.game)
        first = solve(app.session.current_board).order[0]
        app.game.click(first)
        app.game.tick(8.25)
        app.store.save_slot(1, app.game)
        blocked = next(a.id for a in app.session.current_board.arrows
                       if app.session.current_board.first_collision(a.id) is not None)
        for slot in (2, 3, 4):
            app.game.click(blocked)
            app.store.save_slot(slot, app.game)
        app.game = app.store.load_slot(1)
        app.reset_visuals()
        app.route("saves")
        await snap("saves-filled")
        app.paused_page = "game"
        app.route("menu")
        await snap("menu")
        for section in ("basic", "audio", "video", "about"):
            app.settings_section = section
            app.route("settings")
            await snap("settings-" + section)
        app.load_editor("preset:hard-heart")
        app.route("editor")
        await snap("editor")
        app.store.profile.total_arrows = 99
        app.achievements.record_arrow(True)
        app.achievements.record_editor()
        app.store.save_profile()
        app.route("achievements")
        await snap("achievements")
        app.game = app.store.load_slot(4)
        app.reset_visuals()
        app.route("result")
        await snap("result-lost")
        # A separate actually completed one-arrow custom game checks the win
        # page's text and heart placement without grinding campaign progress.
        from arrow_y2k.generation import GenerateConfig
        app.game = GameRun.from_custom(frozenset({(0, 0)}), GenerateConfig("capture-win", 1, 1, 0), "easy")
        app.game.click(next(iter(app.session.remaining)))
        app.reset_visuals()
        app.route("result")
        await snap("result-won")
        app.game = app.store.load_slot(1)
        app.reset_visuals()
        app.route("game")
        await pilot.pause()
        app.show_toast("成就达成 / 百箭穿杨", "累计成功移除 100 支箭头。")
        await snap("achievement-toast")
        app.audio.close()
    return records


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "upgrade")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifact_root = ROOT / ".artifacts"
    artifact_root.mkdir(exist_ok=True)
    records = []
    # TemporaryDirectory creates and cleans only its own unique child under the
    # explicit artifact root; user maps, profiles and slots are never opened.
    with tempfile.TemporaryDirectory(prefix="page-capture-", dir=artifact_root) as directory:
        fixture_root = Path(directory).resolve()
        assert fixture_root.parent == artifact_root.resolve()
        for name in RESOLUTIONS:
            records.extend(await capture_resolution(name, output, fixture_root))
    sources = {}
    for filename in ("app.py", "pages.py", "widgets.py", "pixels.py", "desktop.py", "game.tcss", "campaign.py", "catalog.py", "generation.py"):
        sources[filename] = hashlib.sha256((ROOT / "src" / "arrow_y2k" / filename).read_bytes()).hexdigest()
    report = {"kind": "isolated synthetic UI fixtures; not real player progress",
              "renderer": "actual Textual compositor plus shared native raster widgets",
              "source_sha256": sources, "captures": records}
    (output / "capture-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Captured {len(records)} screenshots: {output}")


if __name__ == "__main__":
    asyncio.run(main())
