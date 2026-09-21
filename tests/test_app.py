"""Current controller integration: result accounting and run restoration."""
import json

import pytest
from textual.widgets import Static

from arrow_y2k.app import ArrowApp
from arrow_y2k.campaign import GameRun
from arrow_y2k.model import Arrow, Board, Direction, GameSession


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def small_board(count=2, blocked=False):
    cells = frozenset((x, 0) for x in range(count))
    arrows = tuple(Arrow(f"a{x}", ((x, 0),), Direction.RIGHT if blocked and x == 0 else Direction.UP)
                   for x in range(count))
    return Board(cells, arrows)


async def install(app, pilot, mode="easy", level=1, count=2, blocked=False):
    app.store.profile.unlocked_modes.add(mode)
    app.start_game(mode)
    await pilot.pause()
    app.game = GameRun._level(mode, "controller-test", level, False)
    app.game.session = GameSession(small_board(count, blocked))
    app.reset_visuals()
    app.refresh_labels()
    await pilot.pause()
    return app.game


async def step(app, pilot, clock, seconds):
    clock.advance(seconds)
    app.tick()
    await pilot.pause()


async def finish(app, pilot, clock):
    await step(app, pilot, clock, app.animation_duration + 0.01)


@pytest.mark.parametrize("failure", ["timeout", "lives"])
async def test_failure_routes_to_result_and_resets_official_streak(tmp_path, failure):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock, seed="test")
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, "medium", blocked=True)
        app.store.profile.current_streak = 5
        if failure == "timeout":
            await step(app, pilot, clock, 600)
            assert game.session.lives == 3
        else:
            for _ in range(3):
                app.play_arrow("a0")
                await finish(app, pilot, clock)
            assert game.session.lives == 0
        assert app.page == "result"
        assert (game.outcome, game.failure_reason, game.counted) == ("lost", failure, True)
        assert app.store.profile.current_streak == 0
        assert app.screen.query("#restart") and not app.screen.query("#next-level")
        summary = str(app.q("#result-summary", Static).render())
        assert ("时间耗尽" if failure == "timeout" else "生命耗尽") in summary
        assert app.store.load_slot(0).to_dict() == game.to_dict()


async def test_clear_waits_for_animation_then_next_enters_correct_tier(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, level=3, count=1)
        app.play_arrow("a0")
        assert game.outcome == "level_won" and app.page == "game"
        assert not game.counted and not app.screen.query("#next-level")
        await finish(app, pilot, clock)
        assert app.page == "result" and game.counted
        assert "medium" in app.store.profile.unlocked_modes
        assert app.store.profile.current_streak == 1
        assert await pilot.click("#next-level", offset=(2, 1))
        await pilot.pause()
        assert app.page == "game" and game.level_index == 4
        assert game.difficulty == "medium" and game.seconds_left == 600
        assert game.outcome == "playing" and not game.counted


async def test_fiftieth_level_shows_campaign_completion_and_unlocks_endless(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, mode="hard", level=50, count=1)
        app.play_arrow("a0")
        await finish(app, pilot, clock)
        assert (app.page, game.outcome) == ("result", "campaign_won")
        assert "endless" in app.store.profile.unlocked_modes
        assert not app.screen.query("#next-level")
        assert "50 关全部完成" in str(app.q("#result-summary", Static).render())


async def test_assisted_solver_does_not_award_arrows_unlocks_or_streak(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, level=3)
        app.store.profile.current_streak = 4
        app.action_solve()
        app.tick()
        for _ in range(4):
            if app.page == "result":
                break
            await finish(app, pilot, clock)
        assert (app.page, game.outcome, game.assisted) == ("result", "level_won", True)
        profile = app.store.profile
        assert profile.total_arrows == 0 and profile.current_streak == 4
        assert profile.unlocked_modes == {"easy"}
        assert not profile.completed_levels and game.counted
        assert "演示局不计" in str(app.q("#result-summary", Static).render())


async def test_endless_clear_auto_advances_and_restoring_boundary_save_continues(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, "endless")
        await step(app, pilot, clock, 4.25)
        game.session.lives = 2
        app.play_arrow("a0")
        await finish(app, pilot, clock)
        app.play_arrow("a1")
        expected = (game.seconds_left, game.combo, game.best_combo, game.elapsed_seconds)
        boundary = game.to_dict()
        await finish(app, pilot, clock)
        assert app.page == "game" and game.level_index == 2 and game.session.lives == 3
        assert (game.seconds_left, game.combo, game.best_combo, game.elapsed_seconds) == expected
        assert game.outcome == "playing" and not game.counted
        # An exact boundary snapshot can also come from saving during the last exit animation.
        app.store.save_slot(1, GameRun.from_dict(boundary))
        app.dispatch("load-slot-1")
        await pilot.pause()
        assert app.page == "game" and app.game.level_index == 2
        assert (app.game.seconds_left, app.game.combo, app.game.best_combo, app.game.elapsed_seconds) == expected


async def test_hundredth_endless_combo_finishes_midboard_and_records_fastest_time(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, "endless", count=3)
        app.store.profile.endless_best_seconds = 12.0
        game.combo = game.best_combo = 99
        await step(app, pilot, clock, 5.0)
        app.play_arrow("a0")
        assert game.outcome == "endless_won" and len(game.session.remaining) == 2
        await finish(app, pilot, clock)
        assert app.page == "result" and game.counted
        assert app.store.profile.endless_best_seconds == 5.0
        assert "endless_clear" in app.store.profile.achievements
        assert not app.screen.query("#next-level")
        assert "无尽挑战完成" in str(app.q("#result-summary", Static).render())


async def test_repeatedly_loaded_completed_results_do_not_double_count(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, level=3, count=1)
        app.play_arrow("a0")
        await finish(app, pilot, clock)
        app.store.save_slot(1, game)
        completed = app.store.profile.to_dict()
        for _ in range(3):
            app.dispatch("load-slot-1")
            await pilot.pause()
            assert app.page == "result" and app.game.counted
            assert app.store.profile.to_dict() == completed


async def test_loading_unprocessed_winning_snapshot_accounts_result_once(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, level=3, count=1)
        app.play_arrow("a0")
        assert game.outcome == "level_won" and not game.counted
        app.store.save_slot(1, game)
        for _ in range(2):
            app.dispatch("load-slot-1")
            await pilot.pause()
            assert app.page == "result" and app.game.counted
            assert app.store.profile.current_streak == 1
            assert "medium" in app.store.profile.unlocked_modes
            assert len(app.store.profile.completed_levels) == 1


@pytest.mark.parametrize("corruption", ["json", "snapshot"])
async def test_malformed_slot_load_preserves_current_game_and_file(tmp_path, corruption):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        await install(app, pilot)
        app.store.save_slot(1, app.game)
        path = tmp_path / "slots" / "slot-1.json"
        if corruption == "json":
            payload = "{broken"
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["run"]["remaining_ids"] = ["nonexistent"]
            payload = json.dumps(data)
        path.write_text(payload, encoding="utf-8")
        before = app.game.to_dict()
        app.dispatch("load-slot-1")
        await pilot.pause()
        assert app.game.to_dict() == before and app.page == "game"
        assert path.read_text(encoding="utf-8") == payload
        assert "操作未完成" in app.toast_text


async def test_click_after_deadline_cannot_beat_timeout_before_next_frame(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, mode="medium", count=1)
        arrows_before = app.store.profile.total_arrows
        # Deliver the click before Textual's next scheduled frame can run.
        clock.advance(game.seconds_left + 0.1)
        app.play_arrow("a0")
        await pilot.pause()
        assert (game.outcome, game.failure_reason, game.seconds_left) == ("lost", "timeout", 0)
        assert game.session.lives == 3 and game.session.moves == 0
        assert set(game.session.remaining) == {"a0"}
        assert app.store.profile.total_arrows == arrows_before
        assert app.page == "result" and game.counted


async def test_load_auto_slot_reads_requested_snapshot_before_saving_outgoing_game(tmp_path):
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        await install(app, pilot)
        outgoing = app.game.to_dict()
        requested = GameRun.new("hard", "saved target")
        requested.tick(12.5)
        requested_snapshot = requested.to_dict()
        app.store.save_slot(0, requested)
        app.dispatch("load-slot-0")
        await pilot.pause()
        assert app.page == "game" and app.game.to_dict() == requested_snapshot
        # The active outgoing game is still retained when autosave overwrites slot zero.
        assert app.store.load_slot(0).to_dict() == outgoing


async def test_first_real_canvas_edit_awards_and_persists_before_map_save(tmp_path):
    from arrow_y2k.storage import GameStore
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        app.dispatch("open-editor")
        await pilot.pause()
        assert "map_editor" not in app.store.profile.achievements
        assert (19, 15) not in app.editor_mask
        app.paint_cell((19, 15))
        await pilot.pause()
        assert app.store.profile.edited_map
        assert "map_editor" in app.store.profile.achievements
        reopened = GameStore(tmp_path)
        assert reopened.profile.edited_map and "map_editor" in reopened.profile.achievements
        assert reopened.list_custom_maps() == []
        before = app.store.profile.to_dict()
        app.paint_cell((19, 15))
        assert app.store.profile.to_dict() == before


async def test_profile_write_failure_keeps_playable_progress_and_reports_error(tmp_path, monkeypatch):
    from arrow_y2k.storage import DomainStorageError, GameStore
    clock = Clock()
    app = ArrowApp(native=True, data_dir=tmp_path, clock=clock)
    async with app.run_test(size=(106, 30)) as pilot:
        game = await install(app, pilot, count=3)
        original = app.store.save_profile
        def locked_file():
            raise DomainStorageError("profile.json temporarily locked")
        monkeypatch.setattr(app.store, "save_profile", locked_file)
        app.play_arrow("a0")
        assert set(game.session.remaining) == {"a1", "a2"}
        assert app.store.profile.total_arrows == 1
        assert "成绩保存失败" in app.toast_text
        await finish(app, pilot, clock)
        assert app.page == "game" and game.outcome == "playing"
        monkeypatch.setattr(app.store, "save_profile", original)
        app.play_arrow("a1")
        assert app.store.profile.total_arrows == 2
        assert GameStore(tmp_path).profile.total_arrows == 2
