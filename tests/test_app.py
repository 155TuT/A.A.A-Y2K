"""Headless tests of the real Textual controls and native pointer routing."""

import time

import pytest
from textual import events
from textual.widgets import Button, Input, Static

from arrow_y2k.app import ArrowApp
from arrow_y2k.model import Arrow, Board, Direction, GameSession
from arrow_y2k.persistence import load_map
from arrow_y2k.pixels import board_metrics
from arrow_y2k.solver import solve, validate_certificate
from arrow_y2k.widgets import BoardView


async def click(pilot, selector):
    """Use actual button input, including Textual hit testing and messages."""
    assert await pilot.click(selector, offset=(2, 1)), selector
    await pilot.pause()


def finish_animation(app):
    """Advance animation clocks, avoiding wall-clock waits in UI tests."""
    if app.animation is not None:
        app.animation_started = time.monotonic() - app.animation_duration - 1
    if app.heart_started is not None:
        app.heart_started = time.monotonic() - 1
    app.tick()


def native_pointer(app, cell, kind=events.MouseDown, button=1):
    view = app.query_one("#board", BoardView)
    mask = (frozenset((x, y) for x in range(12) for y in range(10))
            if app.editing else app.session.board.mask)
    geometry = board_metrics(view.content_size.width * 6, view.content_size.height * 12, mask)
    pixel_x, pixel_y = geometry.cell_center(cell)
    screen_x = view.content_region.x + pixel_x / 6
    screen_y = view.content_region.y + pixel_y / 12
    return kind(None, screen_x, screen_y, 0, 0, button, False, False, False,
                screen_x=screen_x, screen_y=screen_y)


async def click_cell(app, pilot, cell, button=1):
    down = native_pointer(app, cell, button=button)
    app.post_message(down)
    await pilot.pause()
    app.post_message(native_pointer(app, cell, events.MouseUp, button))
    await pilot.pause()
    return down


def blocked_board():
    return Board(
        frozenset((x, y) for x in range(3) for y in range(2)),
        (Arrow("blocked", ((0, 0),), Direction.RIGHT),
         Arrow("free", ((1, 0),), Direction.UP)),
    )


@pytest.mark.parametrize("size", [(85, 32), (106, 30)])
async def test_native_controls_fit_both_logical_window_sizes(size):
    app = ArrowApp(native=True)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        screen = app.screen.region
        footer = app.query_one("#footer").region
        board = app.query_one("#board").region
        side = app.query_one("#side").region
        assert screen.contains_region(board)
        assert not board.overlaps(side)
        assert not board.overlaps(footer)
        ids = ("level-1", "level-2", "level-3", "hearts", "status", "hint",
               "solve", "restart", "next", "custom")
        regions = [app.query_one("#" + name).region for name in ids]
        assert all(side.contains_region(region) for region in regions)
        assert all(not region.overlaps(footer) for region in regions)
        assert all(not first.overlaps(second) for index, first in enumerate(regions)
                   for second in regions[index + 1:])
        await click(pilot, "#custom")
        assert app.editing
        panel = app.query_one("#editor-panel").region
        for name in ("template", "seed", "parameters", "map-path", "save", "load",
                     "clear", "editor-status", "generate", "back", "editor-help"):
            region = app.query_one("#" + name).region
            assert panel.contains_region(region), (size, name, region, panel)
            assert not region.overlaps(footer), (size, name)


async def test_hint_level_buttons_restart_and_complete_solver_demonstration():
    app = ArrowApp(native=True)
    async with app.run_test(size=(106, 30)) as pilot:
        await click(pilot, "#hint")
        assert app.hint_id in app.session.remaining
        assert app.session.current_board.first_collision(app.hint_id) is None
        assert app.session.moves == 0
        await click(pilot, "#level-2")
        assert app.level_index == 2
        assert app.hint_id is None
        assert app.session.lives == 3
        assert app.session.board.width != app.session.board.height
        await click(pilot, "#level-3")
        assert app.level_index == 3
        assert len(app.session.board.mask) < app.session.board.width * app.session.board.height
        await click(pilot, "#level-1")
        initial_count = len(app.session.remaining)
        await pilot.press("h")
        assert app.hint_id is not None
        await click_cell(app, pilot, app.session.remaining[app.hint_id].head)
        assert len(app.session.remaining) == initial_count - 1
        await click(pilot, "#restart")
        assert len(app.session.remaining) == initial_count
        assert app.session.moves == 0
        assert app.animation is None
        await click(pilot, "#solve")
        for _ in range(initial_count + 2):
            finish_animation(app)
            await pilot.pause()
            if app.session.status == "won" and app.animation is None:
                break
        assert app.session.status == "won"
        assert app.session.remaining == {}
        assert app.session.lives == 3
        assert app.assisted
        assert not app.auto_solving
        assert not app.query_one("#next", Button).disabled
        await click(pilot, "#next")
        assert app.level_index == 2
        assert app.session.status == "playing"
        assert not app.assisted


async def test_native_fractional_pointer_hits_three_collisions_then_restart():
    app = ArrowApp(native=True)
    async with app.run_test(size=(106, 30)) as pilot:
        app.session = GameSession(blocked_board())
        app.reset_visuals()
        app.refresh_labels()
        await pilot.pause()
        for lives in (2, 1, 0):
            down = await click_cell(app, pilot, (0, 0))
            assert not down.pointer_screen_x.is_integer() or not down.pointer_screen_y.is_integer()
            assert app.session.lives == lives
            assert len(app.session.remaining) == 2
            assert app.animation is not None
            assert app.animation.kind == "collision"
            assert app.animation.collision_distance == 1
            assert app.lost_index == lives
            # Clicking during impact must not consume another life.
            await click_cell(app, pilot, (0, 0))
            assert app.session.lives == lives
            finish_animation(app)
            await pilot.pause()
        assert app.session.status == "lost"
        assert app.animation is None
        assert app.query_one("#hint", Button).disabled
        assert app.query_one("#solve", Button).disabled
        await click_cell(app, pilot, (1, 0))
        assert app.session.moves == 3
        assert len(app.session.remaining) == 2
        await click(pilot, "#restart")
        assert app.session.status == "playing"
        assert app.session.lives == 3
        assert app.session.moves == 0
        assert app.lost_index is None


async def test_editor_paint_drag_erase_save_load_and_generate_disconnected_map(tmp_path):
    app = ArrowApp(native=True)
    async with app.run_test(size=(106, 30)) as pilot:
        await click(pilot, "#custom")
        await click(pilot, "#clear")
        assert app.editor_mask == set()
        # Mouse capture must keep drag painting active until release.
        app.post_message(native_pointer(app, (0, 0)))
        await pilot.pause()
        app.post_message(native_pointer(app, (1, 0), events.MouseMove))
        await pilot.pause()
        app.post_message(native_pointer(app, (1, 0), events.MouseUp))
        await pilot.pause()
        assert app.painting == 0
        for cell in ((1, 1), (4, 3), (5, 3), (11, 9)):
            await click_cell(app, pilot, cell)
        custom_mask = frozenset({(0, 0), (1, 0), (1, 1), (4, 3), (5, 3), (11, 9)})
        assert app.editor_mask == set(custom_mask)
        await click_cell(app, pilot, (11, 9), button=3)
        assert (11, 9) not in app.editor_mask
        await click_cell(app, pilot, (11, 9))
        path = tmp_path / "painted-map.json"
        for name, value in (("map-path", str(path)), ("seed", "ui-test-种子"),
                            ("density", "100"), ("length", "4"), ("turns", "80")):
            app.query_one("#" + name, Input).value = value
        await click(pilot, "#save")
        assert path.exists()
        saved_mask, config = load_map(path)
        assert saved_mask == custom_mask
        assert config.seed == "ui-test-种子"
        assert config.density == 1
        await click(pilot, "#clear")
        app.query_one("#seed", Input).value = "changed"
        await click(pilot, "#load")
        assert app.editor_mask == set(custom_mask)
        assert app.query_one("#seed", Input).value == "ui-test-种子"
        await click(pilot, "#generate")
        assert not app.editing
        assert app.session.board.mask == custom_mask
        assert len(app.session.board.occupancy) == len(custom_mask)
        assert app.seed == "ui-test-种子"
        solution = solve(app.session.board)
        assert solution.solvable
        assert validate_certificate(app.session.board, solution.order)


async def test_invalid_editor_inputs_keep_canvas_and_current_game_intact():
    app = ArrowApp(native=True)
    original = app.session.board
    async with app.run_test(size=(106, 30)) as pilot:
        await click(pilot, "#custom")
        await click(pilot, "#clear")
        await click(pilot, "#generate")
        assert app.editing
        assert app.session.board == original
        assert app.editor_mask == set()
        assert "empty" in str(app.query_one("#editor-status", Static).render()).lower()
        await click_cell(app, pilot, (3, 4))
        app.query_one("#density", Input).value = "0"
        await click(pilot, "#generate")
        assert app.editing
        assert app.editor_mask == {(3, 4)}
        assert app.session.board == original
        await click(pilot, "#back")
        assert not app.editing
        assert app.session.board == original


async def test_resolution_button_dispatches_host_capability():
    app = ArrowApp(native=True)
    actions = []
    app.host_action = actions.append
    async with app.run_test(size=(106, 30)) as pilot:
        await click(pilot, "#resolution")
        assert app.resolution_name == "1920x1080"
        assert actions == ["resolution:1920x1080"]
        await pilot.press("f6")
        assert app.resolution_name == "1024x768"
        assert actions[-1] == "resolution:1024x768"
