"""Capture the real Textual app inside the native CRT shell using isolated data.

Run: python tools/capture_crt.py [--output PATH]
No player profile, map, or save is opened. The shutdown GIF uses the same
CrtShell.render timing path as the native desktop host, without mock UI.
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
from arrow_y2k.crt import CrtShell, SHUTDOWN_DURATION
from arrow_y2k.desktop import RESOLUTIONS, compose_frame, configure_native_colors


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    paths = sorted((ROOT / "src" / "arrow_y2k").rglob("*.py"))
    paths += [ROOT / "src" / "arrow_y2k" / "game.tcss", Path(__file__)]
    paths += sorted((ROOT / "src" / "arrow_y2k" / "assets" / "icons").glob("*"))
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in paths if path.is_file()}


def gif_frame(image):
    """Reserve index 255 for the enclosure's transparent outer corner mask."""
    frame = image.convert("RGB").quantize(colors=255, dither=Image.Dither.NONE)
    palette = frame.getpalette()
    frame.putpalette(palette[:765] + [0, 0, 0])
    transparent = image.getchannel("A").point(lambda alpha: 255 if alpha < 128 else 0)
    frame.paste(255, mask=transparent)
    frame.info["transparency"] = 255
    return frame


async def capture_resolution(name, output, fixtures):
    preset = RESOLUTIONS[name]
    app = ArrowApp(seed="crt-visual-v4", data_dir=fixtures / name, clock=lambda: 0.0)
    app.store.settings.muted = True
    app.audio.configure(.65, .7, True)
    app.TOOLTIP_DELAY = .01
    configure_native_colors(app)
    shell = CrtShell((preset.width, preset.height), preset.scale)
    records = []
    async with app.run_test(size=preset.terminal_size, tooltips=True) as pilot:
        async def snap(label, *, pressed=None, shutdown_elapsed=None):
            await pilot.pause()
            content = compose_frame(app, preset.logical_size)
            image = shell.render(content, 2.0, pressed=pressed,
                                 shutdown_elapsed=shutdown_elapsed, reduced_motion=False,
                                 monochrome=app.store.settings.monochrome)
            path = output / f"{name}-{label}.png"
            image.save(path)
            records.append({"image": path.name, "page": app.page, "size": list(image.size),
                            "viewport": list(shell.viewport), "sha256": sha256(path),
                            "pressed": pressed, "shutdown_elapsed": shutdown_elapsed,
                            "monochrome": app.store.settings.monochrome,
                            "master_volume": app.store.settings.master_volume,
                            "mode": image.mode, "scale": preset.scale})
            return content

        await snap("home")
        app.toggle_display_mode()
        await snap("home-mono")
        app.toggle_display_mode()
        await pilot.hover("#github", offset=(1, 1))
        await pilot.pause(.08)
        await snap("home-hover-github")
        await pilot.hover("#home-title")
        await pilot.press("escape")
        await snap("exit-confirm")
        app.route("settings")
        await snap("settings")
        app.dispatch("settings-audio")
        await snap("settings-audio-65")
        app.adjust_master_volume(5)
        await snap("settings-audio-70", pressed="plus")
        app.dispatch("settings-video")
        await pilot.pause()
        await pilot.click("#cfg-resolution", offset=(2, 1))
        await snap("settings-dropdown")
        app.start_game("easy")
        game = await snap("game")
        app.toggle_display_mode()
        await snap("game-mono")
        app.toggle_display_mode()
        app.action_menu()
        await pilot.pause()
        await pilot.hover("#minimize", offset=(2, 1))
        await snap("menu-minimize-hover")
        app.route("game")
        await snap("no-signal", shutdown_elapsed=.6)
        app.route("home")
        for control in shell.control_rects:
            await snap("pressed-" + control, pressed=control)

        if name == "1280x720":
            frames, durations, phases = [], [], []
            samples = [(None, 100) for _ in range(5)]
            samples += [(index * .05, 50) for index in range(6)]
            samples += [(.3 + index * .1, 100) for index in range(10)]
            samples += [(SHUTDOWN_DURATION, 250)]
            for index, (shutdown, duration) in enumerate(samples):
                frames.append(gif_frame(shell.render(game, index * .1, pressed=None,
                                           shutdown_elapsed=shutdown, reduced_motion=False,
                                           monochrome=app.store.settings.monochrome)))
                durations.append(duration)
                phases.append(shutdown)
            path = output / f"{name}-shutdown.gif"
            frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations,
                           loop=0, disposal=2, optimize=False, transparency=255, background=255)
            records.append({"image": path.name, "kind": "native shutdown animation",
                            "size": list(frames[0].size), "duration_ms": sum(durations),
                            "sample_durations_ms": durations, "shutdown_samples": phases,
                            "sha256": sha256(path), "transparent_corners": True})
        app.audio.close()
    return records


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "crt-v4")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    before = source_hashes()
    records = []
    with tempfile.TemporaryDirectory(prefix="crt-capture-", dir=artifacts) as directory:
        fixtures = Path(directory).resolve()
        assert fixtures.parent == artifacts.resolve()
        for name in RESOLUTIONS:
            records.extend(await capture_resolution(name, output, fixtures))
    after = source_hashes()
    if before != after:
        raise RuntimeError("Capture source files changed while rendering; rerun after sources settle.")
    report = {"kind": "isolated synthetic UI fixtures; not real player progress",
              "renderer": "compose_frame actual Textual compositor -> native CrtShell.render",
              "source_sha256": after, "captures": records}
    (output / "capture-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Captured {len(records)} native CRT artifacts: {output}")


if __name__ == "__main__":
    asyncio.run(main())
