"""The same executable contract suite for source, pytest and frozen builds.

Only Python's standard unittest runner is required. Every test uses temporary
state; no live player profile, browser or external service is touched.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from .achievements import AchievementService
from .campaign import GameRun, difficulty_for_level
from .catalog import maps_for, preset_maps
from .generation import GenerateConfig, generate, template_mask
from .model import Arrow, Board, Direction, GameSession
from .solver import solve, validate_certificate
from .storage import DomainStorageError, GameStore, Profile


class LaunchContract(unittest.TestCase):
    def test_source_and_binary_entrypoint_always_use_native_host(self):
        from .__main__ import main
        with tempfile.TemporaryDirectory(prefix="aaa-launch-") as directory:
            args = ["game", "--resolution", "1024x768", "--data-dir", directory, "--seed", "launch-test"]
            with patch.object(sys, "argv", args), patch("arrow_y2k.app.ArrowApp") as factory:
                with patch("arrow_y2k.desktop.run_desktop", new_callable=AsyncMock) as host:
                    main()
                    factory.assert_called_once_with(seed="launch-test", data_dir=Path(directory))
                    host.assert_awaited_once_with(factory.return_value, resolution="1024x768",
                                                  screenshot_path=None, quit_after=None)
                    factory.return_value.run.assert_not_called()

    def test_terminal_flag_is_rejected_before_creating_player_state(self):
        from .__main__ import main
        with patch.object(sys, "argv", ["game", "--terminal"]):
            with patch("arrow_y2k.__main__.prepare_windowed_streams") as prepare:
                with self.assertRaises(SystemExit) as stopped:
                    main()
                self.assertEqual(stopped.exception.code, 2)
                prepare.assert_not_called()


class RulesContract(unittest.TestCase):
    def test_four_head_rays_and_blockers(self):
        mask = frozenset((x, y) for x in range(3) for y in range(3))
        for direction in Direction:
            with self.subTest(direction=direction.name):
                arrow = Arrow("a", ((1, 1),), direction)
                self.assertIsNone(Board(mask, (arrow,)).first_collision("a"))
                dx, dy = direction.delta
                blocker = Arrow("b", ((1 + dx, 1 + dy),), Direction.UP)
                collision = Board(mask, (arrow, blocker)).first_collision("a")
                self.assertEqual((collision.arrow_id, collision.distance), ("b", 1))

    def test_own_path_blocks_and_three_hits_lose(self):
        path = ((0, 1), (0, 0), (1, 0), (2, 0), (2, 1), (1, 1))
        arrow = Arrow("loop", path, Direction.LEFT)
        game = GameSession(Board(frozenset(path), (arrow,)))
        self.assertEqual(game.current_board.first_collision("loop").arrow_id, "loop")
        for expected in (2, 1, 0):
            result = game.click("loop")
            self.assertEqual(result.kind, "collision")
            self.assertEqual(game.lives, expected)
            self.assertIn("loop", game.remaining)
        self.assertEqual(game.status, "lost")
        game.restart()
        self.assertEqual((game.lives, game.status), (3, "playing"))

    def test_holes_do_not_end_rays_and_crossings_are_rejected(self):
        a = Arrow("a", ((0, 0),), Direction.RIGHT)
        b = Arrow("b", ((2, 0),), Direction.UP)
        board = Board(frozenset(((0, 0), (2, 0))), (a, b))
        self.assertEqual(board.first_collision("a").arrow_id, "b")
        with self.assertRaises(ValueError):
            Board(board.mask, (a, Arrow("c", ((0, 0),), Direction.UP)))
        game = GameSession(board)
        self.assertEqual(game.click("b").kind, "escaped")
        self.assertEqual(game.click("a").kind, "escaped")
        self.assertEqual((game.status, game.lives), ("won", 3))


class GeneratorContract(unittest.TestCase):
    def test_seed_and_constructive_certificate(self):
        mask = template_mask("heart", 14, 12)
        config = GenerateConfig("shared-seed", 0.83, 10, 0.65)
        one, two = generate(mask, config), generate(mask, config)
        self.assertEqual(one.board, two.board)
        self.assertTrue(validate_certificate(one.board, one.solution.order))
        self.assertTrue(solve(one.board).solvable)

    def test_every_medium_and_hard_preset_is_solvable(self):
        for difficulty in ("medium", "hard"):
            for item in maps_for(difficulty):
                with self.subTest(template=item.id):
                    level = generate(item.mask, GenerateConfig("shared-" + item.id, 0.9, 14, 0.8))
                    self.assertTrue(validate_certificate(level.board, level.solution.order))
                    occupancy = level.board.occupancy
                    self.assertEqual(len(occupancy), sum(len(a.cells) for a in level.board.arrows))
                    self.assertTrue(all(len(a.cells) <= 14 for a in level.board.arrows))


class CampaignContract(unittest.TestCase):
    def test_modes_start_at_one_and_difficulty_boundaries(self):
        for mode in ("easy", "medium", "hard", "endless"):
            run = GameRun.new(mode, "starts-at-one")
            self.assertEqual(run.level_index, 1)
            self.assertEqual(run.difficulty, mode)
        expected = ((3, "easy", "easy"), (4, "easy", "medium"),
                    (10, "easy", "medium"), (11, "easy", "hard"),
                    (1, "medium", "medium"), (10, "medium", "medium"),
                    (11, "medium", "hard"), (1, "hard", "hard"))
        for level, mode, difficulty in expected:
            self.assertEqual(difficulty_for_level(level, mode), difficulty)

    def test_easy_tutorial_advances_to_timed_medium(self):
        run = GameRun.new("easy", "tutorial-transition")
        for index in (1, 2, 3):
            self.assertEqual(run.level_index, index)
            for arrow_id in solve(run.session.current_board).order:
                run.click(arrow_id)
            self.assertEqual(run.outcome, "level_won")
            self.assertTrue(run.advance())
        self.assertEqual((run.level_index, run.difficulty, run.seconds_left), (4, "medium", 240.0))

    def test_countdown_and_terminal_state_ignore_further_ticks(self):
        run = GameRun.new("hard", "countdown")
        run.tick(1.25)
        self.assertEqual((run.seconds_left, run.elapsed_seconds), (118.75, 1.25))
        run.tick(999)
        self.assertEqual((run.seconds_left, run.elapsed_seconds, run.outcome), (0, 120, "lost"))
        run.tick(100)
        self.assertEqual(run.elapsed_seconds, 120)
        run.restart()
        self.assertEqual((run.seconds_left, run.elapsed_seconds, run.outcome), (120, 0, "playing"))

    @staticmethod
    def endless(combo=0, seconds=30):
        arrows = tuple(Arrow(str(x), ((x, 0),), Direction.UP) for x in range(3))
        run = GameRun(GameSession(Board(frozenset((x, 0) for x in range(3)), arrows)),
                      "endless", "endless", 1, "bonus", seconds)
        run.combo = run.best_combo = combo
        return run

    def test_endless_combo_rewards_and_both_win_conditions(self):
        run = self.endless(combo=8)
        run.click("0")
        self.assertEqual((run.combo, run.seconds_left), (9, 33))
        run.click("1")
        self.assertEqual((run.combo, run.seconds_left), (10, 37))
        run = self.endless(combo=98)
        run.click("0")
        self.assertEqual(run.outcome, "playing")
        run.click("1")
        self.assertEqual((run.combo, run.outcome), (100, "endless_won"))
        run = self.endless(seconds=897)
        run.click("0")
        self.assertEqual((run.seconds_left, run.outcome), (900, "playing"))
        run.click("1")
        self.assertEqual(run.outcome, "endless_won")


    def test_collision_penalties_and_life_loss_priority(self):
        board = Board(frozenset({(0, 0), (1, 0)}), (
            Arrow("blocked", ((0, 0),), Direction.RIGHT),
            Arrow("free", ((1, 0),), Direction.UP),
        ))
        for mode, penalty in (("easy", 0), ("medium", 10), ("hard", 20), ("endless", 20)):
            with self.subTest(mode=mode):
                run = GameRun.new(mode, "shared-penalty")
                run.session = GameSession(board)
                before = run.seconds_left
                run.combo = run.best_combo = 9
                self.assertEqual(run.collision_penalty_seconds, penalty)
                self.assertEqual(run.click("blocked").kind, "collision")
                self.assertEqual((run.session.lives, run.combo), (2, 0))
                self.assertEqual(run.seconds_left, None if before is None else before - penalty)
                self.assertEqual(run.elapsed_seconds, 0)
                if not penalty:
                    continue
                for lives, reason in ((2, "timeout"), (1, "lives")):
                    run.restart()
                    run.session.lives = lives
                    run.seconds_left = penalty / 2
                    run.click("blocked")
                    self.assertEqual((run.seconds_left, run.outcome, run.failure_reason), (0, "lost", reason))
                    snapshot = run.to_dict()
                    self.assertEqual(GameRun.from_dict(snapshot).to_dict(), snapshot)
                    self.assertEqual(run.click("free").kind, "ignored")

    def test_endless_initial_life_and_cross_level_recovery(self):
        run = GameRun.new("endless", "shared-lives")
        self.assertEqual((run.session.lives, run.seconds_left), (1, 30))
        for lives, expected in ((1, 2), (2, 3), (3, 3)):
            run.session = self.endless().session
            run.session.lives = lives
            for arrow_id in solve(run.session.current_board).order:
                run.click(arrow_id)
            before = (run.seconds_left, run.combo, run.elapsed_seconds)
            self.assertTrue(run.advance())
            self.assertEqual(run.session.lives, expected)
            self.assertEqual((run.seconds_left, run.combo, run.elapsed_seconds), before)
        run.restart()
        self.assertEqual((run.session.lives, run.seconds_left, run.combo), (1, 30, 0))

    def test_legacy_saves_keep_existing_time_and_lives(self):
        for mode, seconds, lives, reset_seconds, reset_lives in (
            ("medium", 597.25, 2, 240, 3), ("hard", 473.5, 1, 120, 3),
            ("endless", 111.125, 3, 30, 1),
        ):
            with self.subTest(mode=mode):
                saved = GameRun.new(mode, "legacy-shared").to_dict()
                saved["run"]["seconds_left"] = seconds
                saved["lives"] = lives
                run = GameRun.from_dict(saved)
                self.assertEqual(run.to_dict(), saved)
                run.restart()
                self.assertEqual((run.seconds_left, run.session.lives), (reset_seconds, reset_lives))


class IsolatedStoreCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aaa-shared-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = GameStore(self.root / "state")


class StorageContract(IsolatedStoreCase):
    def test_settings_profile_and_disabled_autosave_persist(self):
        self.store.settings.autosave = False
        self.store.settings.save_minutes = 7
        self.store.settings.master_volume = 0.2
        self.store.profile.total_arrows = 123
        self.store.save_settings()
        self.store.save_profile()
        loaded = GameStore(self.store.root)
        self.assertFalse(loaded.settings.autosave)
        self.assertEqual((loaded.settings.save_minutes, loaded.settings.master_volume), (7, 0.2))
        self.assertEqual(loaded.profile.total_arrows, 123)
        self.assertFalse((self.store.root / "slots").exists())

    def test_all_five_slots_restore_exact_board_time_and_progress(self):
        run = GameRun.new("medium", "five-slots")
        run.tick(12.75)
        run.click(solve(run.session.current_board).order[0])
        expected = run.to_dict()
        for index in range(5):
            self.store.save_slot(index, run)
        with patch("arrow_y2k.campaign.generate", side_effect=AssertionError("must restore, not regenerate")):
            for index in range(5):
                self.assertEqual(self.store.load_slot(index).to_dict(), expected)
            summaries = self.store.slots()
        self.assertEqual([item.slot for item in summaries], list(range(5)))
        self.assertTrue(all(item.left == item.total - 1 for item in summaries))
        with self.assertRaises(DomainStorageError):
            self.store.delete_slot(0)
        self.store.delete_slot(2)
        self.assertIsNone(self.store.load_slot(2))

    def test_custom_crud_import_and_preset_immutability(self):
        preset = preset_maps()[0]
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            preset.name = "changed"
        with self.assertRaises(DomainStorageError):
            self.store.delete_custom_map(preset.id)
        item = self.store.save_custom_map("共享测试地图", preset.mask, GenerateConfig("custom"), "easy")
        path = self.root / "exchange.json"
        self.store.export_custom_map(item.id, path)
        imported = self.store.import_custom_map(path)
        self.assertNotEqual(imported.id, item.id)
        self.assertEqual(imported.mask, item.mask)
        self.store.delete_custom_map(item.id)
        self.assertEqual(self.store.list_custom_maps(), [imported])

    def test_legacy_map_import_and_corrupt_or_failed_writes(self):
        from .persistence import save_map
        legacy = self.root / "legacy-heart.json"
        mask = template_mask("heart")
        save_map(legacy, mask, GenerateConfig("legacy"))
        imported = self.store.import_custom_map(legacy)
        self.assertEqual((imported.mask, imported.name), (mask, "legacy-heart"))
        self.store.save_settings()
        original = (self.store.root / "settings.json").read_bytes()
        self.store.settings.muted = True
        with patch("arrow_y2k.storage.os.replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(DomainStorageError):
                self.store.save_settings()
        self.assertEqual((self.store.root / "settings.json").read_bytes(), original)
        (self.store.root / "profile.json").write_text("{broken", encoding="utf-8")
        loaded = GameStore(self.store.root)
        self.assertTrue(loaded.warnings)
        self.assertEqual((self.store.root / "profile.json").read_text(encoding="utf-8"), "{broken")


class AchievementsContract(IsolatedStoreCase):
    def test_mode_unlock_thresholds_and_idempotent_completed_saves(self):
        from types import SimpleNamespace
        service = AchievementService(self.store.profile)
        self.assertEqual([a.id for a in service.list_all() if a.unlocked], ["mode_easy"])
        for index in range(1, 11):
            run = SimpleNamespace(custom=False, mode="easy", outcome="level_won",
                                  level_index=index, completion_id=f"run:{index}")
            service.record_level(run)
            if index == 2:
                self.assertNotIn("medium", service.profile.unlocked_modes)
            if index == 3:
                self.assertIn("medium", service.profile.unlocked_modes)
            if index == 9:
                self.assertNotIn("hard", service.profile.unlocked_modes)
        self.assertIn("hard", service.profile.unlocked_modes)
        self.assertIn("streak_10", service.profile.achievements)
        self.store.save_profile()
        again = AchievementService(GameStore(self.store.root).profile)
        self.assertEqual(again.record_level(run), [])
        self.assertEqual(again.profile.current_streak, 10)
        run.level_index, run.completion_id = 50, "run:50"
        self.assertIn("mode_endless", [item.id for item in again.record_level(run)])
        run.custom, run.completion_id = True, "custom:1"
        self.assertEqual(again.record_level(run), [])
        again.record_loss()
        self.assertEqual((again.profile.current_streak, again.profile.best_streak), (0, 11))

    def test_all_arrow_streak_editor_and_fastest_time_awards(self):
        from types import SimpleNamespace
        for count in (100, 500, 1000, 100000):
            service = AchievementService(Profile(total_arrows=count - 1))
            self.assertEqual(service.record_arrow(False), [])
            self.assertEqual(service.profile.total_arrows, count - 1)
            self.assertIn(f"arrows_{count}", [a.id for a in service.record_arrow(True)])
            self.assertEqual(service.record_arrow(True), [])
        for count in (10, 50, 100, 500):
            service = AchievementService(Profile(current_streak=count - 1))
            run = SimpleNamespace(custom=False, mode="easy", outcome="level_won",
                                  level_index=1, completion_id="streak:1")
            self.assertIn(f"streak_{count}", [a.id for a in service.record_level(run)])
        service = AchievementService(Profile())
        self.assertEqual([a.id for a in service.record_editor()], ["map_editor"])
        self.assertEqual(service.record_editor(), [])
        self.assertEqual([a.id for a in service.record_endless(120)], ["endless_clear"])
        self.assertEqual(service.record_endless(130), [])
        self.assertEqual(service.record_endless(100), [])
        self.assertEqual(service.profile.endless_best_seconds, 100)


class FontContract(unittest.TestCase):
    def test_pixel_icons_and_monitor_placement(self):
        from .icons import pixel_icon
        from .windowing import WorkArea, choose_work_area, place_window
        for name in ("play", "folder", "trophy", "map", "gear", "exit", "github", "heart"):
            with self.subTest(icon=name):
                icon = pixel_icon(name)
                self.assertEqual(icon.mode, "RGBA")
                self.assertIsNotNone(icon.getbbox())
        primary = WorkArea(0, 0, 2560, 1392)
        secondary = WorkArea(-2560, -155, 2560, 1528)
        self.assertEqual(choose_work_area([primary, secondary], (-2000, 200, 1280, 720)), secondary)
        self.assertEqual(place_window((1920, 1080), primary, (1600, 900)), (640, 312))
        self.assertEqual(place_window((1920, 1080), secondary, (-1200, 900)), (-1920, 293))
        self.assertEqual(place_window((1920, 1080), WorkArea(0, 0, 1280, 680)), (0, 0))

    def test_bundled_font_is_monospaced_binary_pixel_data(self):
        from .fonts import glyph_mask, pixel_font
        self.assertEqual(pixel_font().getlength("A"), 6)
        self.assertEqual(pixel_font().getlength("箭"), 12)
        self.assertEqual(glyph_mask("箭").mode, "1")
        self.assertEqual(glyph_mask("箭").size, (12, 12))


class FixedClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class TextualContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from .app import ArrowApp
        self.temporary = tempfile.TemporaryDirectory(prefix="aaa-textual-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.clock = FixedClock()
        self.app = ArrowApp(seed="shared-ui", data_dir=Path(self.temporary.name), clock=self.clock)

    async def test_home_and_global_escape_from_settings(self):
        from .pages import HomePage, PausePage, SettingsPage
        async with self.app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            self.assertIsInstance(self.app.screen, HomePage)
            self.app.dispatch("open-settings")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, SettingsPage)
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, PausePage)

    async def test_settings_pause_game_clock_and_resume_without_catchup(self):
        from .pages import GamePage, SettingsPage
        self.app.store.profile.unlocked_modes.add("medium")
        async with self.app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            self.app.start_game("medium")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, GamePage)
            self.clock.value += 2.5
            self.app.tick()
            self.assertAlmostEqual(self.app.game.seconds_left, 237.5)
            self.app.dispatch("open-settings")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, SettingsPage)
            self.clock.value += 40
            self.app.tick()
            self.assertAlmostEqual(self.app.game.seconds_left, 237.5)
            self.app.action_menu()
            await pilot.pause()
            self.app.dispatch("resume")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, GamePage)
            self.clock.value += 0.5
            self.app.tick()
            self.assertAlmostEqual(self.app.game.seconds_left, 237.0)

    async def test_autosave_disabled_persists_and_writes_no_slot(self):
        from textual.widgets import Switch
        async with self.app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            self.app.dispatch("open-settings")
            await pilot.pause()
            self.app.screen.query_one("#cfg-autosave", Switch).value = False
            await pilot.pause()
            self.app.dispatch("apply-settings")
            await pilot.pause()
            self.assertFalse(self.app.store.settings.autosave)
            self.app.start_game("easy")
            await pilot.pause()
            self.app.auto_save()
            self.assertIsNone(self.app.store.load_slot(0))
            loaded = GameStore(Path(self.temporary.name))
            self.assertFalse(loaded.settings.autosave)

    async def test_load_restores_time_and_does_not_count_paused_time(self):
        self.app.store.profile.unlocked_modes.add("medium")
        async with self.app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            self.app.start_game("medium")
            await pilot.pause()
            self.clock.value += 7.25
            self.app.tick()
            self.app.store.save_slot(1, self.app.game)
            expected = self.app.game.to_dict()
            self.app.dispatch("open-saves")
            await pilot.pause()
            self.clock.value += 60
            self.app.tick()
            self.app.dispatch("load-slot-1")
            await pilot.pause()
            self.assertEqual(self.app.game.to_dict(), expected)
            self.clock.value += 0.5
            self.app.tick()
            self.assertAlmostEqual(self.app.game.seconds_left, 232.25)


    async def test_concurrent_clicks_finish_independently_and_delay_result(self):
        async with self.app.run_test(size=(120, 44)) as pilot:
            self.app.start_game("easy")
            await pilot.pause()
            arrows = tuple(Arrow(str(x), ((x, 0),), Direction.UP) for x in range(3))
            self.app.game.session = GameSession(Board(frozenset((x, 0) for x in range(3)), arrows))
            self.app.reset_visuals()
            self.app.click_cell((0, 0))
            self.app.click_cell((1, 0))
            self.assertEqual(len(self.app.game.session.remaining), 1)
            self.assertEqual(len(self.app.effects.animations), 2)
            self.clock.value += .2
            self.app.click_cell((2, 0))
            self.assertEqual(len(self.app.effects.animations), 3)
            self.assertGreater(self.app.effects.animations[0].progress, self.app.effects.animations[-1].progress)
            self.assertEqual(self.app.game.outcome, "level_won")
            self.assertEqual(self.app.page, "game")
            self.clock.value += .5
            self.app.tick()
            self.assertEqual(len(self.app.effects.animations), 1)
            self.assertEqual(self.app.page, "game")
            self.clock.value += .2
            self.app.tick()
            await pilot.pause()
            self.assertEqual(self.app.page, "result")
            self.assertFalse(self.app.effects.active)

    async def test_busy_arrow_deduplication_and_pointer_reset(self):
        from textual.widgets import Button
        self.app.store.profile.unlocked_modes.add("medium")
        async with self.app.run_test(size=(120, 44)) as pilot:
            self.app.start_game("medium")
            await pilot.pause()
            board = Board(frozenset({(0, 0), (1, 0), (2, 0)}), (
                Arrow("a", ((0, 0),), Direction.RIGHT),
                Arrow("b", ((1, 0),), Direction.RIGHT),
                Arrow("c", ((2, 0),), Direction.UP),
            ))
            self.app.game.session = GameSession(board)
            self.app.reset_visuals()
            self.app.play_arrow("a")
            self.app.play_arrow("a")
            self.app.play_arrow("b")
            self.assertEqual((self.app.session.lives, self.app.session.moves, self.app.game.seconds_left), (1, 2, 220))
            self.assertEqual(set(self.app.effects.heart_frames), {1, 2})
            self.app.play_arrow("c")
            self.assertNotIn("c", self.app.session.remaining)
            self.assertEqual(len(self.app.effects.animations), 3)
            self.app.action_menu()
            await pilot.pause()
            button = self.app.screen.query_one(Button)
            self.app.screen.set_focus(button)
            button.add_class("-active")
            self.app._set_mouse_over(button, None)
            self.app.reset_pointer_state()
            self.assertIsNone(self.app.mouse_over)
            self.assertIsNone(self.app.screen.focused)
            self.assertFalse(button.has_class("-active"))
            self.assertFalse(self.app.screen.ALLOW_SELECT)
            self.assertTrue(all(item.active_effect_duration == 0 for item in self.app.screen.query(Button)))

    async def test_failure_keeps_last_living_auto_save_even_on_timer_and_exit(self):
        self.app.store.profile.unlocked_modes.add("hard")
        async with self.app.run_test(size=(120, 44)) as pilot:
            for reason in ("lives", "timeout"):
                with self.subTest(reason=reason):
                    self.app.start_game("hard")
                    await pilot.pause()
                    self.assertIsNotNone(self.app.store.load_slot(0))
                    self.app.game.session = GameSession(Board(frozenset({(0, 0), (1, 0)}), (
                        Arrow("blocked", ((0, 0),), Direction.RIGHT),
                        Arrow("free", ((1, 0),), Direction.UP),
                    )))
                    if reason == "lives":
                        self.app.session.lives = 1
                    else:
                        self.app.game.seconds_left = .5
                    self.app.auto_save()
                    path = Path(self.temporary.name) / "slots" / "slot-0.json"
                    before = path.read_bytes()
                    if reason == "lives":
                        self.app.play_arrow("blocked")
                    self.app.autosave_elapsed = 181
                    self.clock.value += 1.1
                    self.app.tick()
                    await pilot.pause()
                    self.assertEqual(self.app.game.failure_reason, reason)
                    self.assertFalse(self.app.auto_save())
                    self.app.dispatch("go-home")
                    await pilot.pause()
                    self.assertEqual(path.read_bytes(), before)
                    self.assertGreater(self.app.store.load_slot(0).session.lives, 0)
            self.app.request_desktop_exit()
            self.assertEqual(path.read_bytes(), before)

    async def test_real_tooltips_cover_native_icons_at_button_edges(self):
        from textual.geometry import Region
        from textual.widgets import Tooltip
        from .desktop import compose_frame, configure_native_colors, _rasterize_strips
        from .fonts import glyph_mask
        configure_native_colors(self.app)
        self.app.TOOLTIP_DELAY = .01
        async with self.app.run_test(size=(106, 30), tooltips=True) as pilot:
            for button_id in ("exit-desktop", "github"):
                for offset_x in (0, 1, 3):
                    with self.subTest(button=button_id, offset=offset_x):
                        await pilot.hover("#home-title")
                        await pilot.pause()
                        await pilot.hover("#" + button_id, offset=(offset_x, 1))
                        await pilot.pause(.06)
                        tooltip = self.app.screen.query_one("#textual-tooltip", Tooltip)
                        button = self.app.screen.query_one("#" + button_id)
                        self.assertTrue(tooltip.display)
                        region = tooltip.region
                        self.assertTrue(region.overlaps(button.region))
                        frame = compose_frame(self.app, (640, 360))
                        expected = _rasterize_strips(
                            tooltip.render_lines(Region(0, 0, region.width, region.height)),
                            (region.width * 6, region.height * 12),
                        )
                        actual = frame.crop((region.x * 6, region.y * 12,
                                             region.right * 6, region.bottom * 12))
                        self.assertEqual(actual.tobytes(), expected.tobytes())
                        # Check the first Chinese glyph itself as well, so a
                        # clipped CJK title cannot pass with a matching blank.
                        title = "项" if button_id == "github" else "退"
                        x0 = tooltip.content_region.x * 6 + (54 if button_id == "github" else 0)
                        y0 = tooltip.content_region.y * 12
                        ink = glyph_mask(title)
                        for y in range(ink.height):
                            for x in range(ink.width):
                                if ink.getpixel((x, y)):
                                    self.assertNotEqual(frame.getpixel((x0 + x, y0 + y)),
                                                        tooltip.styles.background.rgb)

    async def test_expanded_select_has_pixel_outline_green_options_and_keyboard_selection(self):
        from .desktop import compose_frame, configure_native_colors
        from .widgets import PixelSelect
        from .pixels import BACKGROUND
        app = self.app
        configure_native_colors(app)
        async with app.run_test(size=(106, 30)) as pilot:
            app.settings_section = 'video'
            app.route('settings')
            await pilot.pause()
            await pilot.click('#cfg-resolution', offset=(2, 1))
            await pilot.pause()
            select = app.screen.query_one('#cfg-resolution', PixelSelect)
            overlay = select.query_one('SelectOverlay')
            self.assertTrue(select.expanded and overlay.native_full_region)
            r = overlay.region
            frame = compose_frame(app, (640, 360))
            crop = frame.crop((r.x * 6, r.y * 12, r.right * 6, r.bottom * 12))
            line = overlay.styles.border_top[1].rgb
            fill = overlay.styles.background.rgb
            self.assertTrue(all((crop.getpixel((x, 6)) == line and crop.getpixel((x, crop.height - 7)) == line for x in range(crop.width))))
            self.assertTrue(all((crop.getpixel((0, y)) == line and crop.getpixel((crop.width - 1, y)) == line for y in range(6, crop.height - 6))))
            self.assertTrue(all((crop.getpixel((x, y)) == BACKGROUND for x in range(crop.width) for y in list(range(6)) + list(range(crop.height - 6, crop.height)))))
            self.assertTrue(all((crop.getpixel((x, 7)) == fill and crop.getpixel((x, crop.height - 8)) == fill for x in range(1, crop.width - 1))))
            colors = set(crop.get_flattened_data())
            self.assertTrue((28, 48, 40) in colors and (114, 214, 156) in colors)
            self.assertTrue((1, 120, 212) not in colors)
            await pilot.press('down', 'enter')
            await pilot.pause()
            self.assertTrue(not select.expanded and select.value == '1920x1080')

    async def test_crt_glass_routes_clicks_text_and_power_off_without_changing_rules(self):
        from .app import ArrowApp
        from .desktop import PixelHost, RESOLUTIONS, compose_frame
        from .pixels import board_metrics
        from .crt import SHUTDOWN_DURATION, SHUTDOWN_SHAKE_SECONDS
        from textual.widgets import Input
        from PIL import Image
        self.assertAlmostEqual(SHUTDOWN_DURATION - SHUTDOWN_SHAKE_SECONDS, 1.0)
        with patch.dict("os.environ", {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
                                       "PYGAME_HIDE_SUPPORT_PROMPT": "1"}):
            import pygame
            pygame.display.init()
            try:
                for name, preset in RESOLUTIONS.items():
                    with self.subTest(resolution=name):
                        clock = FixedClock()
                        app = ArrowApp(data_dir=Path(self.temporary.name) / name, seed="crt-input", clock=clock)
                        app.audio.configure(0, 0, True)
                        host = PixelHost(app, name)
                        host._pygame = pygame
                        host._set_resolution(name, notify=False)
                        app.host_action = host.handle_action
                        host.running = True
                        async with app.run_test(size=preset.terminal_size) as pilot:
                            await pilot.pause()
                            async def click_source(source):
                                point = host.shell.forward_point(source)
                                self.assertIsNotNone(point)
                                for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                                    host.process_event(pygame.event.Event(kind, button=1, pos=point))
                                await pilot.pause()
                            async def click_widget(selector):
                                r = app.screen.query_one(selector).region
                                await click_source((r.x * 6 + r.width * 3, r.y * 12 + r.height * 6))
                            async def press_control(control):
                                x, y, w, h = host.shell.control_rects[control]
                                point = (x + w // 2, y + h // 2)
                                for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                                    host.process_event(pygame.event.Event(kind, button=1, pos=point))
                                await pilot.pause()
                            def escape():
                                host.process_event(pygame.event.Event(pygame.KEYDOWN,
                                    key=pygame.K_ESCAPE, unicode="", mod=0))
                            await click_widget("#open-settings")
                            self.assertEqual(app.page, "settings")
                            await click_widget("#cfg-save-minutes")
                            host.process_event(pygame.event.Event(pygame.KEYDOWN,
                                key=pygame.K_a, unicode="", mod=pygame.KMOD_CTRL | pygame.KMOD_SHIFT))
                            await pilot.pause()
                            host.process_event(pygame.event.Event(pygame.TEXTINPUT, text="4"))
                            await pilot.pause()
                            self.assertEqual(app.screen.query_one("#cfg-save-minutes", Input).value, "4")
                            await click_widget("#settings-audio")
                            await press_control("plus")
                            self.assertEqual(app.screen.query_one("#cfg-master", Input).value, "70")
                            self.assertEqual(app.audio.master_volume, .70)
                            self.assertEqual(GameStore(app.store.root).settings.master_volume, .70)
                            await press_control("minus")
                            self.assertEqual(app.screen.query_one("#cfg-master", Input).value, "65")
                            await press_control("menu")
                            self.assertTrue(app.store.settings.monochrome)
                            self.assertTrue(GameStore(app.store.root).settings.monochrome)
                            await press_control("menu")
                            self.assertFalse(app.store.settings.monochrome)
                            self.assertFalse(GameStore(app.store.root).settings.monochrome)
                            # Releasing outside a physical key cancels the action.
                            x, y, w, h = host.shell.control_rects["plus"]
                            host.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                                                 pos=(x + w // 2, y + h // 2)))
                            host.process_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(10, 10)))
                            self.assertEqual(app.audio.master_volume, .65)
                            await click_widget("#go-home")
                            self.assertEqual(app.page, "home")
                            escape()
                            await pilot.pause()
                            self.assertEqual(app.page, "exit-confirm")
                            await click_widget("#cancel-exit")
                            self.assertEqual(app.page, "home")
                            await click_widget("#new-game")
                            await click_widget("#start-easy")
                            self.assertEqual(app.page, "game")
                            count = len(app.session.remaining)
                            for arrow_id in solve(app.session.current_board).order[:2]:
                                board = app.screen.query_one("#board")
                                r = board.content_region
                                g = board_metrics(r.width * 6, r.height * 12, app.session.board.mask)
                                cell = app.session.remaining[arrow_id].head
                                await click_source((r.x * 6 + g.origin_x + ((cell[0] - g.min_x) * 16 + 8) * g.scale,
                                                    r.y * 12 + g.origin_y + ((cell[1] - g.min_y) * 16 + 8) * g.scale))
                            self.assertEqual(len(app.session.remaining), count - 2)
                            # Display/audio controls must not dispatch gameplay events.
                            snapshot = app.game.to_dict()
                            for control, rect in host.shell.control_rects.items():
                                if control == "power":
                                    continue
                                x, y, w, h = rect
                                point = (x + w // 2, y + h // 2)
                                host.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point))
                                self.assertEqual(host._pressed_control, control)
                                host.process_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=point))
                                self.assertIsNone(host._pressed_control)
                            self.assertEqual(app.game.to_dict(), snapshot)
                            self.assertTrue(app.store.settings.monochrome)
                            frame = host.shell.render(compose_frame(app, preset.logical_size), 2, monochrome=True)
                            self.assertEqual(frame.mode, "RGBA")
                            self.assertEqual(frame.getpixel((0, 0))[3], 0)
                            x, y, w, h = host.shell.viewport
                            rgb = frame.crop((x, y, x + w, y + h)).convert("RGB").split()
                            self.assertEqual(rgb[0].tobytes(), rgb[1].tobytes())
                            self.assertEqual(rgb[1].tobytes(), rgb[2].tobytes())
                            with patch.object(app.store, "save_slot", wraps=app.store.save_slot) as save:
                                x, y, w, h = host.shell.control_rects["power"]
                                point = (x + w // 2, y + h // 2)
                                for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                                    host.process_event(pygame.event.Event(kind, button=1, pos=point))
                                host.process_event(pygame.event.Event(pygame.QUIT))
                                app.request_desktop_exit()
                                self.assertEqual(save.call_count, 1)
                            self.assertTrue(app._desktop_closing and host.running)
                            self.assertIsNotNone(host._shutdown_started)
                            self.assertFalse(app._exit)
                            clock.value += 50
                            app.tick()
                            self.assertEqual(app.game.to_dict(), snapshot)
                            self.assertEqual(app.store.load_slot(0).to_dict(), snapshot)
                            signal = host.shell.render(Image.new("RGB", preset.logical_size), 2,
                                                       shutdown_elapsed=SHUTDOWN_SHAKE_SECONDS + .5)
                            self.assertEqual(signal.size, host.shell.outer_size)
                            host._finish_exit()
                            self.assertFalse(host.running)
            finally:
                pygame.display.quit()

    async def test_native_host_exports_integer_scaled_crt_frame(self):
        from PIL import Image, ImageChops
        from .desktop import run_desktop
        path = Path(self.temporary.name) / "native-frame.png"
        with patch.dict("os.environ", {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
                                       "PYGAME_HIDE_SUPPORT_PROMPT": "1"}):
            with patch.object(self.app, "finish_desktop_exit", wraps=self.app.finish_desktop_exit) as finish:
                await run_desktop(self.app, "1024x768", screenshot_path=path, quit_after=0.1)
                self.assertEqual(finish.call_count, 1)
            # Both SDL's close event and a Textual menu exit may end the app
            # between the host loop's event pump and its next composition.
            import asyncio
            import pygame
            from .app import ArrowApp
            for source in ("sdl", "textual"):
                closing = ArrowApp(data_dir=Path(self.temporary.name) / source)
                async def close_soon():
                    await asyncio.sleep(0.08)
                    if source == "sdl":
                        pygame.event.post(pygame.event.Event(pygame.QUIT))
                    else:
                        closing.exit()
                closer = asyncio.create_task(close_soon())
                await asyncio.wait_for(run_desktop(closing, "1024x768"), timeout=4)
                await closer
        with Image.open(path) as frame:
            from .crt import CrtShell
            self.assertEqual(frame.size, CrtShell((1024, 768), 2).outer_size)
            enlarged = frame.resize(tuple(v // 2 for v in frame.size), Image.Resampling.NEAREST).resize(frame.size, Image.Resampling.NEAREST)
            self.assertIsNone(ImageChops.difference(frame, enlarged).getbbox(alpha_only=False))
            self.assertEqual(frame.mode, "RGBA")
            self.assertEqual(frame.getpixel((0, 0))[3], 0)


CONTRACT_CLASSES = (
    LaunchContract, RulesContract, GeneratorContract, CampaignContract, StorageContract,
    AchievementsContract, FontContract, TextualContract,
)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.setdefault(test.id(), {"id": test.id(), "status": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records[test.id()] = {"id": test.id(), "status": "failed", "detail": self._exc_info_to_string(err, test)}

    def addError(self, test, err):
        super().addError(test, err)
        self.records[test.id()] = {"id": test.id(), "status": "error", "detail": self._exc_info_to_string(err, test)}

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.records[test.id()] = {"id": test.id(), "status": "failed",
                                       "detail": self._exc_info_to_string(err, test)}

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records[test.id()] = {"id": test.id(), "status": "skipped", "detail": reason}


def contract_suite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    return unittest.TestSuite(loader.loadTestsFromTestCase(cls) for cls in CONTRACT_CLASSES)


def run_self_tests(report_path: str | None = None) -> int:
    """Run the identical packaged/source suite and optionally write audit JSON."""
    stream = io.StringIO()
    diagnostics = io.StringIO()
    # Windowed bootloaders set all four streams to None. Textual reads the
    # double-underscore originals, so redirecting sys.stderr alone is insufficient.
    with patch.multiple(sys, stdout=diagnostics, stderr=diagnostics,
                        __stdout__=diagnostics, __stderr__=diagnostics):
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult).run(contract_suite())
    report = {
        "schema_version": 1,
        "suite": "arrow_y2k.shared_contract",
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "tests_run": result.testsRun,
        "successful": result.wasSuccessful() and not result.skipped,
        "tests": sorted(result.records.values(), key=lambda item: item["id"]),
        "log": stream.getvalue(),
        "diagnostics": diagnostics.getvalue(),
    }
    if report_path is not None:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(f"Shared contract: {result.testsRun} tests; {'PASS' if report['successful'] else 'FAIL'}")
        if not report["successful"]:
            print(stream.getvalue())
    return 0 if report["successful"] else 1
