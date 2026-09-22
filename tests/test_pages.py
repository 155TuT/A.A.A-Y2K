"""Real Textual page flows with isolated storage and deterministic elapsed time.

Test-only profile unlocks and achievement counters are written exclusively to
pytest's temporary directory; no production player state is touched.
"""

import json

import pytest
from textual import events
from textual.widgets import Button, Input, Select, Static, Switch

from arrow_y2k.app import ArrowApp
from arrow_y2k.campaign import GameRun
from arrow_y2k.catalog import maps_for
from arrow_y2k.desktop import compose_frame
from arrow_y2k.generation import GenerateConfig
from arrow_y2k.pixels import board_metrics
from arrow_y2k.solver import solve
from arrow_y2k.storage import GameStore
from arrow_y2k.widgets import BoardView


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_app(tmp_path):
    clock = FakeClock()
    app = ArrowApp(data_dir=tmp_path, clock=clock, seed="page-tests")
    app.store.profile.unlocked_modes.update(("medium", "hard", "endless"))
    # These tests exercise UI capability dispatch, not the machine's speakers.
    app.audio.play = lambda event: True
    return app, clock


async def click(pilot, selector):
    assert await pilot.click(selector, offset=(2, 1)), selector
    await pilot.pause()


async def start(pilot, mode="medium"):
    await click(pilot, "#new-game")
    await click(pilot, "#start-" + mode)


async def advance(app, clock, pilot, seconds):
    clock.advance(seconds)
    app.tick()
    await pilot.pause()


async def native_click(app, pilot, cell, button=1):
    view = app.screen.query_one("#board", BoardView)
    mask = (frozenset((x, y) for x in range(20) for y in range(16))
            if app.editing else app.session.board.mask)
    width, height = view.content_size.width * 6, view.content_size.height * 12
    px, py = board_metrics(width, height, mask).cell_center(cell)
    sx, sy = view.content_region.x + px / 6, view.content_region.y + py / 12
    for event in (events.MouseDown, events.MouseUp):
        app.post_message(event(None, sx, sy, 0, 0, button, False, False, False,
                               screen_x=sx, screen_y=sy))
    await pilot.pause()


def visible_controls_fit(app):
    screen = app.screen.region
    for widget in app.screen.query("Button, Input, Select"):
        if widget.visible and widget.display and widget.region.width and widget.region.height:
            assert screen.contains_region(widget.region), (app.page, widget.id, widget.region, screen)


async def test_home_difficulty_game_navigation_and_paused_timers(tmp_path):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        assert app.page == "home"
        await start(pilot)
        assert app.page == "game"
        assert app.game.seconds_left == 240
        for forbidden in ("brand", "resolution", "minimize", "close", "level-tabs", "caption"):
            assert not app.screen.query("#" + forbidden)
        await advance(app, clock, pilot, 7)
        assert app.game.seconds_left == 233
        await pilot.press("escape")
        assert app.page == "menu"
        await advance(app, clock, pilot, 100)
        assert app.game.seconds_left == 233
        await click(pilot, "#open-settings")
        await advance(app, clock, pilot, 100)
        assert app.game.seconds_left == 233
        await pilot.press("escape")
        assert app.page == "menu"
        await click(pilot, "#open-saves")
        await advance(app, clock, pilot, 100)
        assert app.game.seconds_left == 233
        await pilot.press("escape")
        await click(pilot, "#go-home")
        assert app.page == "home"
        await advance(app, clock, pilot, 100)
        assert app.game.seconds_left == 233
        assert app.game.elapsed_seconds == 7


async def test_collision_animation_freezes_while_paused_and_resumes(tmp_path):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        await start(pilot)
        blocked = next(a for a in app.session.current_board.arrows
                       if app.session.current_board.first_collision(a.id) is not None)
        await native_click(app, pilot, blocked.head)
        assert app.session.lives == 2
        assert app.effects.animations[0].kind == "collision"
        await advance(app, clock, pilot, .2)
        frozen = app.effects.animations[0].progress
        await pilot.press("escape")
        await advance(app, clock, pilot, 100)
        assert app.effects.animations[0].progress == frozen
        assert app.session.lives == 2
        await click(pilot, "#resume")
        await advance(app, clock, pilot, 1)
        assert not app.effects.active
        assert blocked.id in app.failed_ids
        assert app.game.seconds_left == pytest.approx(228.8)


async def test_manual_slots_restore_exact_state_and_autosave_does_not_overwrite_them(tmp_path):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        await start(pilot)
        blocked = next(a for a in app.session.current_board.arrows
                       if app.session.current_board.first_collision(a.id) is not None)
        await native_click(app, pilot, blocked.head)
        await advance(app, clock, pilot, 1)
        legal_id = solve(app.session.current_board).order[0]
        await native_click(app, pilot, app.session.remaining[legal_id].head)
        await advance(app, clock, pilot, 1)
        expected = app.game.to_dict()
        await pilot.press("escape")
        await click(pilot, "#open-saves")
        assert len(app.screen.query(".save-slot")) == 5
        assert not app.screen.query("#save-slot-0")
        assert not app.screen.query("#delete-slot-0")
        await click(pilot, "#save-slot-1")
        assert app.store.load_slot(1).to_dict() == expected
        summary = app.store.slots()[1]
        assert summary.lives == 2
        assert summary.left == len(expected["remaining_ids"])
        info = str(app.screen.query_one("#slot-1 .save-info", Static).render())
        assert "LEFT" in info and "中等" in info and "第 1 关" in info
        await click(pilot, "#load-slot-1")
        assert app.page == "game"
        assert app.game.to_dict() == expected
        # Loading preserves the outgoing game in the automatic slot first.
        before_timer = app.store.load_slot(0).to_dict()
        await advance(app, clock, pilot, 179.9)
        assert app.store.load_slot(0).to_dict() == before_timer
        await advance(app, clock, pilot, .11)
        automatic = app.store.load_slot(0).to_dict()
        assert automatic["run"]["elapsed_seconds"] > before_timer["run"]["elapsed_seconds"]
        assert automatic["remaining_ids"] == expected["remaining_ids"]
        assert automatic["lives"] == 2
        assert app.store.load_slot(1).to_dict() == expected
        # Turn automatic persistence off through actual settings controls.
        await pilot.press("escape")
        await click(pilot, "#open-settings")
        await click(pilot, "#cfg-autosave")
        await click(pilot, "#apply-settings")
        assert app.store.settings.autosave is False
        await click(pilot, "#back")
        await click(pilot, "#resume")
        await advance(app, clock, pilot, 181)
        assert app.store.load_slot(0).to_dict() == automatic
        assert app.store.load_slot(1).to_dict() == expected
        await pilot.press("escape")
        await click(pilot, "#open-saves")
        await click(pilot, "#save-slot-2")
        assert app.store.load_slot(2).to_dict() == app.game.to_dict()
        app.request_desktop_exit()
    fresh = GameStore(tmp_path)
    assert fresh.settings.autosave is False
    assert fresh.load_slot(0).to_dict() == automatic
    assert fresh.load_slot(1).to_dict() == expected


async def test_exit_saves_when_enabled(tmp_path):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        await start(pilot)
        await advance(app, clock, pilot, 12.25)
        expected = app.game.to_dict()
        await pilot.press("escape")
        await click(pilot, "#exit-desktop")
    assert GameStore(tmp_path).load_slot(0).to_dict() == expected


async def test_settings_frequency_audio_switches_and_resolution_are_persistent(tmp_path):
    app, clock = make_app(tmp_path)
    host_actions = []
    app.host_action = host_actions.append
    async with app.run_test(size=(106, 30)) as pilot:
        await click(pilot, "#open-settings")
        app.q("#cfg-save-minutes", Input).value = "5"
        await click(pilot, "#apply-settings")
        assert app.store.settings.save_minutes == 5
        await click(pilot, "#settings-audio")
        await click(pilot, "#cfg-muted")
        app.q("#cfg-master", Input).value = "40"
        app.q("#cfg-effects", Input).value = "60"
        await click(pilot, "#apply-settings")
        assert app.audio.muted
        assert app.audio.master_volume == .4
        assert app.audio.effects_volume == .6
        await click(pilot, "#settings-video")
        await pilot.click("#cfg-resolution", offset=(2, 1))
        await pilot.pause()
        assert app.q("#cfg-resolution", Select).expanded
        await pilot.press("down", "enter")
        assert app.q("#cfg-resolution", Select).value == "1920x1080"
        await click(pilot, "#cfg-motion")
        await click(pilot, "#apply-settings")
        assert host_actions == ["resolution:1920x1080"]
    settings = GameStore(tmp_path).settings
    assert (settings.save_minutes, settings.muted, settings.master_volume, settings.effects_volume,
            settings.resolution, settings.reduced_motion) == (5, True, .4, .6, "1920x1080", True)


async def test_editor_presets_are_protected_custom_maps_are_editable_and_exportable(tmp_path):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        await click(pilot, "#open-editor")
        assert app.q("#editor-delete", Button).disabled
        preset_original = frozenset(app.editor_mask)
        await click(pilot, "#editor-clear")
        for cell in ((0, 0), (1, 0), (1, 1), (4, 2)):
            await native_click(app, pilot, cell)
        custom = frozenset({(0, 0), (1, 0), (1, 1), (4, 2)})
        assert app.editor_mask == set(custom)
        app.q("#map-name", Input).value = "UI test / 自制"
        exported = tmp_path / "exports" / "ui-map.json"
        app.q("#map-path", Input).value = str(exported)
        await click(pilot, "#editor-save")
        assert app.editor_selection.startswith("custom:")
        assert not app.q("#editor-delete", Button).disabled
        identifier = app.editor_selection
        assert len(app.store.list_custom_maps()) == 1
        await native_click(app, pilot, (4, 2), button=3)
        await click(pilot, "#editor-export")
        assert app.editor_selection == identifier
        assert len(app.store.list_custom_maps()) == 1
        payload = json.loads(exported.read_text(encoding="utf-8"))
        assert frozenset(map(tuple, payload["mask"])) == custom - {(4, 2)}
        assert app.presets[0].mask == preset_original
        await click(pilot, "#editor-delete")
        assert app.editor_selection.startswith("preset:")
        assert app.q("#editor-delete", Button).disabled
        assert app.store.list_custom_maps() == []
        assert exported.exists()


async def test_new_achievement_is_persisted_and_toast_stays_off_board(tmp_path):
    app, clock = make_app(tmp_path)
    app.store.profile.total_arrows = 99
    async with app.run_test(size=(106, 30)) as pilot:
        await start(pilot, "easy")
        legal_id = solve(app.session.current_board).order[0]
        await native_click(app, pilot, app.session.remaining[legal_id].head)
        assert app.store.profile.total_arrows == 100
        assert "arrows_100" in GameStore(tmp_path).profile.achievements
        toast = app.screen.query_one("#achievement-toast")
        assert toast.has_class("show-toast")
        assert "百箭穿杨" in app.toast_text
        assert app.screen.region.contains_region(toast.region)
        assert toast.region.right >= app.screen.region.right - 2
        assert toast.region.bottom >= app.screen.region.bottom - 2
        assert not toast.region.overlaps(app.screen.query_one("#board").region)
        await advance(app, clock, pilot, 4.1)
        assert not app.toast_text


@pytest.mark.parametrize("size", [(85, 32), (106, 30)])
async def test_all_pages_and_settings_fit_and_escape_to_menu(tmp_path, size):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await start(pilot)
        for page in ("home", "difficulty", "game", "saves", "settings", "achievements", "editor"):
            app.route(page)
            await pilot.pause()
            visible_controls_fit(app)
            assert compose_frame(app, (size[0] * 6, size[1] * 12)).size == (size[0] * 6, size[1] * 12)
            await pilot.press("escape")
            assert app.page == "menu", page
            visible_controls_fit(app)
            await click(pilot, "#resume")
            assert app.page == page
        for section in ("basic", "audio", "video", "about"):
            app.settings_section = section
            app.route("settings")
            await pilot.pause()
            visible_controls_fit(app)
        # Reach the result screen through a real one-arrow custom game.
        app.game = GameRun.from_custom(frozenset({(0, 0)}), GenerateConfig("result", 1, 1, 0), "easy")
        app.reset_visuals()
        app.route("game")
        await pilot.pause()
        await native_click(app, pilot, (0, 0))
        await advance(app, clock, pilot, 1)
        assert app.page == "result"
        visible_controls_fit(app)
        await pilot.press("escape")
        assert app.page == "menu"


@pytest.mark.parametrize("size", [(85, 32), (106, 30)])
async def test_all_hard_template_masks_fit_full_integer_pixels(tmp_path, size):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        for template in maps_for("hard"):
            app.game = GameRun.from_custom(template.mask, GenerateConfig("hard-layout", .9, 12, .7), "hard")
            app.reset_visuals()
            app.route("game")
            await pilot.pause()
            view = app.screen.query_one("#board", BoardView)
            width, height = view.content_size.width * 6, view.content_size.height * 12
            geometry = board_metrics(width, height, template.mask)
            assert geometry.origin_x >= 0 and geometry.origin_y >= 0, (size, template.id, geometry, view.region)
            assert view.native_frame(width, height).size == (width, height)
            visible_controls_fit(app)


async def test_rapid_repeated_native_clicks_and_triple_clicks_never_select_game_text(tmp_path):
    app, clock = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        await start(pilot, "easy")
        legal_id = solve(app.session.current_board).order[0]
        cell = app.session.remaining[legal_id].head
        for _ in range(3):
            await native_click(app, pilot, cell)
        assert app.store.profile.total_arrows == 1
        assert await pilot.click("#stats", offset=(1, 0), times=3)
        await pilot.pause()
        assert not app.screen.selections
        assert not app.screen.query_one("#stats").text_selection
