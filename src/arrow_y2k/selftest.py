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
from unittest.mock import patch

from .achievements import AchievementService
from .campaign import GameRun, difficulty_for_level
from .catalog import maps_for, preset_maps
from .generation import GenerateConfig, generate, template_mask
from .model import Arrow, Board, Direction, GameSession
from .solver import solve, validate_certificate
from .storage import DomainStorageError, GameStore, Profile


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
        self.assertEqual((run.level_index, run.difficulty, run.seconds_left), (4, "medium", 600.0))

    def test_countdown_and_terminal_state_ignore_further_ticks(self):
        run = GameRun.new("hard", "countdown")
        run.tick(1.25)
        self.assertEqual((run.seconds_left, run.elapsed_seconds), (478.75, 1.25))
        run.tick(999)
        self.assertEqual((run.seconds_left, run.elapsed_seconds, run.outcome), (0, 480, "lost"))
        run.tick(100)
        self.assertEqual(run.elapsed_seconds, 480)
        run.restart()
        self.assertEqual((run.seconds_left, run.elapsed_seconds, run.outcome), (480, 0, "playing"))

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
        self.app = ArrowApp(native=False, seed="shared-ui", data_dir=Path(self.temporary.name), clock=self.clock)

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
            self.assertAlmostEqual(self.app.game.seconds_left, 597.5)
            self.app.dispatch("open-settings")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, SettingsPage)
            self.clock.value += 40
            self.app.tick()
            self.assertAlmostEqual(self.app.game.seconds_left, 597.5)
            self.app.action_menu()
            await pilot.pause()
            self.app.dispatch("resume")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, SettingsPage)
            self.app.dispatch("back")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, GamePage)
            self.clock.value += 0.5
            self.app.tick()
            self.assertAlmostEqual(self.app.game.seconds_left, 597.0)

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
            self.assertAlmostEqual(self.app.game.seconds_left, 592.25)


    async def test_native_host_exports_integer_scaled_frame(self):
        from PIL import Image, ImageChops
        from .desktop import run_desktop
        self.app.native = True
        path = Path(self.temporary.name) / "native-frame.png"
        with patch.dict("os.environ", {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
                                       "PYGAME_HIDE_SUPPORT_PROMPT": "1"}):
            await run_desktop(self.app, "1024x768", screenshot_path=path, quit_after=0.1)
            # Both SDL's close event and a Textual menu exit may end the app
            # between the host loop's event pump and its next composition.
            import asyncio
            import pygame
            from .app import ArrowApp
            for source in ("sdl", "textual"):
                closing = ArrowApp(native=True, data_dir=Path(self.temporary.name) / source)
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
            self.assertEqual(frame.size, (1024, 768))
            enlarged = frame.resize((512, 384), Image.Resampling.NEAREST).resize(frame.size, Image.Resampling.NEAREST)
            self.assertIsNone(ImageChops.difference(frame, enlarged).getbbox())


CONTRACT_CLASSES = (
    RulesContract, GeneratorContract, CampaignContract, StorageContract,
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
