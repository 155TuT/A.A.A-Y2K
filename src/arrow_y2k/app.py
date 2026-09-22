"""Compose independent rules, storage, achievements, audio and Textual pages."""
from __future__ import annotations
import math
import secrets
import time
from collections import deque
from pathlib import Path
from textual.app import App
from textual.binding import Binding
from textual.geometry import Offset
from textual import on
from textual.widgets import Button, Input, Select, Static, Switch

from .campaign import GameRun
from .catalog import preset_maps
from .generation import GenerateConfig
from .storage import GameStore, DomainStorageError
from .achievements import AchievementService
from .audio import AudioController
from .pixels import Animation
from .solver import solve
from .pages import PAGES, MODE_NAMES


class ArrowApp(App):
    CSS_PATH = "game.tcss"
    TITLE = "ARROW.AFTER.ARROW-Y2K"
    ENABLE_COMMAND_PALETTE = False
    ALLOW_SELECT = False
    BINDINGS = [
        Binding("escape", "menu", "菜单", priority=True),
        Binding("ctrl+q", "quit", "退出", priority=True),
        ("h", "hint", "提示"), ("s", "solve", "演示"), ("r", "restart", "重来"),
    ]

    def __init__(self, *, native=False, seed=None, data_dir=None, clock=time.monotonic):
        super().__init__()
        self.native = native
        self.clock = clock
        self.seed = seed
        self.store = GameStore(Path(data_dir) if data_dir is not None else None)
        self.achievements = AchievementService(self.store.profile)
        cfg = self.store.settings
        self.audio = AudioController(cfg.master_volume, cfg.effects_volume, cfg.muted)
        self.resolution_name = cfg.resolution
        self.host_action = None
        self.game: GameRun | None = None
        self.page = "home"
        self._page_ready = False
        self.paused_page = "home"
        self.back_page = "home"
        self.settings_section = "basic"
        self.last_tick = self.clock()
        self.autosave_elapsed = 0.0
        self.animation = None
        self.animation_elapsed = 0.0
        self.animation_duration = .65
        self.heart_progress = None
        self.heart_elapsed = None
        self.lost_index = None
        self._label_values = {}
        self.hovered = self.hint_id = None
        self.cursor = (0, 0)
        self.failed_ids = set()
        self.auto_solving = False
        self.message = ""
        self.painting = 0
        self.presets = preset_maps()
        first = self.presets[0]
        self.editor_selection = "preset:" + first.id
        self.editor_name = first.name + " / 我的版本"
        self.editor_difficulty = first.difficulty
        self.editor_mask = set(first.mask)
        self.editor_seed = "my-map"
        self.editor_density, self.editor_length, self.editor_turns = 85, 12, 65
        self.editor_path = str(self.store.root / "exports" / "my-map.json")
        self.editor_hover = None
        self.toast_queue = deque()
        self.toast_text = ""
        self.toast_until = 0.0

    @property
    def session(self):
        return self.game.session if self.game is not None else None

    @property
    def editing(self):
        return self.page == "editor"

    @property
    def window_drag_region(self):
        # Headers and the game's top margin reserve this whole source-pixel row.
        return (0, 0, self.size.width * 6, 12)

    def reset_pointer_state(self):
        if not self.screen_stack:
            return
        self._set_mouse_over(None, None)
        self.mouse_position = Offset(-1, -1)
        self.capture_mouse(None)
        self.painting = 0
        self.hovered = self.editor_hover = None
        self.screen.clear_selection()
        for widget in self.screen.query("Button, Switch"):
            widget.remove_class("-active")
        if isinstance(self.focused, (Button, Switch)):
            self.screen.set_focus(None)

    def on_mount(self):
        self.push_screen(PAGES["home"]())
        self.set_interval(1 / 60, self.tick)
        if self.store.warnings:
            self.show_toast("数据提示", self.store.warnings[0])

    def page_ready(self):
        self._page_ready = True
        self.refresh_labels()

    def route(self, page):
        self.consume_game_time()
        if self.page == "editor":
            self.capture_editor()
        self.reset_pointer_state()
        self._label_values.clear()
        self._page_ready = False
        self.page = page
        self.painting = 0
        self.last_tick = self.clock()
        self.switch_screen(PAGES[page]())

    def q(self, selector, kind=Static):
        return self.screen.query_one(selector, kind)

    def set_text(self, selector, text):
        matches = self.screen.query(selector)
        if matches and self._label_values.get(selector) != text:
            matches.first(Static).update(text)
            self._label_values[selector] = text

    def refresh_labels(self):
        if not self.is_mounted or not self._page_ready or not self.screen_stack or not self.screen.is_mounted:
            return
        if self.page == "game" and self.game:
            if not self.screen.query("#solve") or not self.screen.query("#board"):
                return
            game = self.game
            self.set_text("#level-name", game.name)
            self.set_text("#mode-name", MODE_NAMES[game.difficulty] + (" / 自制试玩" if game.custom else ""))
            self.set_text("#stats", f"LEFT {len(self.session.remaining)}/{len(self.session.board.arrows)}")
            if game.seconds_left is None:
                value = "XX:XX"
            else:
                seconds = math.ceil(game.seconds_left)
                value = f"{seconds // 60:02d}:{seconds % 60:02d}"
            self.set_text("#timer", value)
            self.set_text("#combo", f"COMBO {game.combo:03d}  /  +{game.combo_bonus_seconds}s" if game.mode == "endless" else "")
            self.set_text("#status", self.message)
            solve_button = self.q("#solve", Button)
            label = "停止 S" if self.auto_solving else "演示 S"
            if str(solve_button.label) != label:
                solve_button.label = label
            self.q("#board", object).refresh()
            self.q("#hearts", object).refresh()
        elif self.page == "result" and self.game:
            game = self.game
            reason = "时间耗尽" if game.failure_reason == "timeout" else "生命耗尽"
            lead = reason if game.outcome == "lost" else "无尽挑战完成" if game.outcome == "endless_won" else "50 关全部完成" if game.outcome == "campaign_won" else "全部箭头已移除"
            assist = "\n演示局不计成就与通关纪录。" if game.assisted else ""
            self.set_text("#result-summary", f"{lead}\n第 {game.level_index} 关 / {MODE_NAMES[game.difficulty]}\nLEFT {len(self.session.remaining)}/{len(self.session.board.arrows)}\n用时 {game.elapsed_seconds:.1f} 秒{assist}")
        elif self.page == "editor":
            self.set_text("#editor-status", f"{len(self.editor_mask)} 格 · 左绘右擦")
            self.q("#board", object).refresh()
        self.set_text("#achievement-toast", self.toast_text)
        matches = self.screen.query("#achievement-toast")
        if matches:
            toast = matches.first()
            toast.styles.offset = (max(0, self.screen.size.width - 27), 0)
            toast.set_class(bool(self.toast_text), "show-toast")

    def sound(self, event):
        if self.native and self.host_action is not None:
            self.audio.play(event)

    def show_toast(self, title, description=""):
        self.toast_queue.append((title, description))
        self.advance_toast()

    def advance_toast(self):
        now = self.clock()
        if self.toast_text and now < self.toast_until:
            return
        if self.toast_queue:
            title, description = self.toast_queue.popleft()
            self.toast_text = f"[#72d69c]{title}[/]\n{description}"
            self.toast_until = now + 4.0
        else:
            self.toast_text = ""
        if self.is_mounted:
            self.refresh_labels()

    def awards(self, items):
        for item in items:
            self.show_toast("成就达成 / " + item.title, item.description)
            self.sound("achievement")
        try:
            self.store.save_profile()
        except DomainStorageError as error:
            # Keep earned progress in memory; the next normal save can persist it.
            self.show_toast("成绩保存失败", str(error))

    def reset_visuals(self):
        self.animation = None
        self.animation_elapsed = 0.0
        self.heart_elapsed = self.heart_progress = self.lost_index = None
        self.hovered = self.hint_id = None
        self.failed_ids.clear()
        self.auto_solving = False
        self.autosave_elapsed = 0.0
        self.cursor = min(self.session.board.mask, key=lambda c: (c[1], c[0])) if self.game else (0, 0)

    def start_game(self, mode):
        if mode not in self.store.profile.unlocked_modes:
            self.show_toast("模式尚未解锁")
            return
        self.auto_save()
        seed = self.seed if self.seed is not None else secrets.token_hex(8)
        self.game = GameRun.new(mode, seed, tutorial=not self.store.profile.tutorial_completed)
        self.reset_visuals()
        self.message = self.game.description
        self.route("game")

    def click_cell(self, cell):
        if self.page != "game" or not self.game or self.animation or self.game.outcome != "playing":
            return
        self.cursor = cell
        arrow_id = self.session.current_board.occupancy.get(cell)
        if arrow_id:
            self.auto_solving = False
            self.play_arrow(arrow_id)

    def play_arrow(self, arrow_id):
        if not self.game or self.animation or self.game.outcome != "playing":
            return
        self.consume_game_time()
        if self.game.outcome != "playing":
            self.process_result()
            return
        result = self.game.click(arrow_id)
        if result.kind == "ignored":
            return
        self.hovered = self.hint_id = None
        collision = result.kind == "collision"
        self.animation_duration = .95 if collision else .65
        self.animation_elapsed = 0.0
        self.animation = Animation(result.arrow, "collision" if collision else "exit", 0.0,
                                   result.collision.distance if collision else None)
        if collision:
            self.lost_index = self.session.lives
            self.heart_elapsed = -self.animation_duration * .30
            self.heart_progress = 0.0
            self.message = "[#d96b9e]发生碰撞。[/]\n先移除头部射线上的遮挡。"
            self.sound("collision")
        else:
            self.failed_ids.discard(arrow_id)
            self.message = "路径畅通。" if not self.game.assisted else "正在演示；本局不计成就。"
            if not self.game.assisted:
                self.awards(self.achievements.record_arrow(True))
            self.sound("click")
        self.refresh_labels()

    def consume_game_time(self):
        now = self.clock()
        dt = max(0.0, now - self.last_tick)
        self.last_tick = now
        if self.page != "game" or not self.game or not self._page_ready:
            return 0.0
        self.game.tick(dt)
        self.autosave_elapsed += dt
        if self.store.settings.autosave and self.autosave_elapsed >= self.store.settings.save_minutes * 60:
            self.auto_save()
        return dt

    def tick(self):
        if not self.is_mounted or not self.screen_stack:
            return
        dt = self.consume_game_time()
        if self.toast_text or self.toast_queue:
            self.advance_toast()
        if self.page != "game" or not self.game or not self._page_ready:
            return
        if self.animation:
            self.animation_elapsed += dt
            p = min(1.0, self.animation_elapsed / self.animation_duration)
            self.animation = Animation(self.animation.arrow, self.animation.kind, p, self.animation.collision_distance)
            if p >= 1.0:
                if self.animation.kind == "collision":
                    self.failed_ids.add(self.animation.arrow.id)
                self.animation = None
        if self.heart_elapsed is not None:
            self.heart_elapsed += dt
            self.heart_progress = max(0.0, min(1.0, self.heart_elapsed / .7))
            if self.heart_progress >= 1:
                self.heart_elapsed = self.heart_progress = self.lost_index = None
        if not self.animation and self.game.outcome != "playing":
            self.process_result()
            return
        if self.auto_solving and not self.animation and self.game.outcome == "playing":
            solution = solve(self.session.current_board)
            if solution.order:
                self.play_arrow(solution.order[0])
        self.refresh_labels()

    def process_result(self):
        game = self.game
        self.auto_solving = False
        if not game.counted:
            if not game.assisted:
                if game.outcome == "lost" and not game.custom:
                    self.awards(self.achievements.record_loss())
                elif game.outcome == "endless_won":
                    self.awards(self.achievements.record_endless(game.elapsed_seconds))
                elif game.outcome != "lost":
                    self.awards(self.achievements.record_level(game))
            game.counted = True
            self.sound("lose" if game.outcome == "lost" else "win")
        self.auto_save()
        if game.mode == "endless" and game.outcome == "level_won":
            game.advance()
            self.reset_visuals()
            self.message = game.description
            self.last_tick = self.clock()
            self.route("game")
        else:
            self.route("result")

    def auto_save(self):
        self.autosave_elapsed = 0.0
        if not self.game or not self.store.settings.autosave:
            return False
        try:
            self.store.save_slot(0, self.game)
            return True
        except DomainStorageError as error:
            self.show_toast("自动保存失败", str(error))
            return False

    def action_menu(self):
        if self.page == "menu":
            self.route(self.paused_page)
        else:
            self.paused_page = self.page
            self.route("menu")

    def action_quit(self):
        self.request_desktop_exit()

    def request_desktop_exit(self):
        self.consume_game_time()
        self.auto_save()
        self.audio.close()
        self.exit()

    def action_hint(self):
        if self.page != "game" or self.animation or self.game.outcome != "playing":
            return
        solution = solve(self.session.current_board)
        self.hint_id = solution.order[0] if solution.order else None
        self.message = "绿色箭头可以移除。\n沿头部方向观察遮挡。"
        self.refresh_labels()

    def action_solve(self):
        if self.page != "game" or self.game.outcome != "playing":
            return
        self.auto_solving = not self.auto_solving
        if self.auto_solving:
            self.game.assisted = True
        self.message = "演示不计成就与纪录；再次按 S 停止。" if self.auto_solving else "演示已停止。"
        self.refresh_labels()

    def action_restart(self):
        if self.page not in ("game", "result") or not self.game:
            return
        if not self.game.custom and self.game.outcome == "playing" and not self.game.assisted:
            self.awards(self.achievements.record_loss())
        self.game.restart()
        self.reset_visuals()
        self.message = "重新开始。"
        self.route("game")

    def apply_settings(self):
        from dataclasses import replace
        cfg = replace(self.store.settings)
        if self.settings_section == "basic":
            cfg.autosave = self.q("#cfg-autosave", Switch).value
            cfg.save_minutes = int(self.q("#cfg-save-minutes", Input).value)
        elif self.settings_section == "audio":
            cfg.muted = self.q("#cfg-muted", Switch).value
            cfg.master_volume = int(self.q("#cfg-master", Input).value) / 100
            cfg.effects_volume = int(self.q("#cfg-effects", Input).value) / 100
        elif self.settings_section == "video":
            cfg.resolution = str(self.q("#cfg-resolution", Select).value)
            cfg.reduced_motion = self.q("#cfg-motion", Switch).value
        cfg.validate()
        old_resolution = self.store.settings.resolution
        self.store.settings = cfg
        self.store.save_settings()
        self.audio.configure(cfg.master_volume, cfg.effects_volume, cfg.muted)
        self.autosave_elapsed = 0.0
        self.resolution_name = cfg.resolution
        if self.host_action and old_resolution != cfg.resolution:
            self.host_action("resolution:" + cfg.resolution)
        self.set_text("#settings-status", "设置已保存。")

    def load_editor(self, selection):
        self.editor_selection = selection
        kind, identifier = selection.split(":", 1)
        if kind == "preset":
            item = next(p for p in self.presets if p.id == identifier)
            self.editor_name = item.name + " / 我的版本"
        else:
            item = next(p for p in self.store.list_custom_maps() if p.id == identifier)
            self.editor_name = item.name
            self.editor_seed = item.config.seed
            self.editor_density = round(item.config.density * 100)
            self.editor_length = item.config.max_length
            self.editor_turns = round(item.config.turn_bias * 100)
        self.editor_mask = set(item.mask)
        self.editor_difficulty = item.difficulty

    def capture_editor(self):
        if not self.is_mounted or not self.screen.query("#map-name"):
            return
        self.editor_name = self.q("#map-name", Input).value
        self.editor_seed = self.q("#editor-seed", Input).value
        self.editor_difficulty = str(self.q("#map-difficulty", Select).value)
        self.editor_path = self.q("#map-path", Input).value
        for field, selector in (("editor_density","#density"),("editor_length","#length"),("editor_turns","#turns")):
            text = self.q(selector, Input).value
            if text.isdigit():
                setattr(self, field, int(text))

    def editor_config(self):
        self.capture_editor()
        return GenerateConfig(self.editor_seed, int(self.q("#density", Input).value) / 100,
                              int(self.q("#length", Input).value), int(self.q("#turns", Input).value) / 100)

    def paint_cell(self, cell, *, erase=False):
        if cell is None:
            return
        before = cell in self.editor_mask
        self.editor_mask.discard(cell) if erase else self.editor_mask.add(cell)
        if before != (cell in self.editor_mask):
            self.record_map_edit()
        self.refresh_labels()

    def record_map_edit(self):
        if "map_editor" not in self.store.profile.achievements:
            self.awards(self.achievements.record_editor())

    def editor_action(self, key):
        self.capture_editor()
        identifier = self.editor_selection.split(":", 1)[1] if self.editor_selection.startswith("custom:") else None
        if key == "editor-clear":
            if self.editor_mask:
                self.editor_mask.clear()
                self.record_map_edit()
        elif key == "editor-delete":
            if identifier is None:
                raise ValueError("预设地图不能删除。")
            self.store.delete_custom_map(identifier)
            self.load_editor("preset:" + self.presets[0].id)
            self.page = "home"  # Do not recapture the deleted editor fields.
            self.route("editor")
            return
        elif key == "editor-import":
            item = self.store.import_custom_map(Path(self.editor_path).expanduser())
            self.load_editor("custom:" + item.id)
            self.page = "home"
            self.route("editor")
            return
        elif key in ("editor-save", "editor-export"):
            item = self.store.save_custom_map(self.editor_name, frozenset(self.editor_mask),
                                              self.editor_config(), self.editor_difficulty, map_id=identifier)
            self.editor_selection = "custom:" + item.id
            self.awards(self.achievements.record_editor())
            if key == "editor-export":
                self.store.export_custom_map(item.id, Path(self.editor_path).expanduser())
            self.page = "home"
            self.route("editor")
            self.show_toast("地图已导出" if key == "editor-export" else "地图已保存", item.name)
            return
        elif key == "editor-play":
            self.auto_save()
            self.game = GameRun.from_custom(frozenset(self.editor_mask), self.editor_config(), self.editor_difficulty)
            self.game.name = self.editor_name
            self.reset_visuals()
            self.message = self.game.description
            self.route("game")
            return
        self.refresh_labels()

    @on(Select.Changed, "#map-catalog")
    def select_map(self, event):
        if self.page == "editor" and isinstance(event.value, str) and event.value != self.editor_selection:
            self.load_editor(event.value)
            self.page = "home"
            self.route("editor")

    def dispatch(self, key):
        try:
            if key == "new-game":
                self.route("difficulty")
            elif key.startswith("start-"):
                self.start_game(key[6:])
            elif key == "go-home":
                self.consume_game_time()
                self.auto_save()
                self.auto_solving = False
                self.route("home")
            elif key == "resume":
                self.route(self.paused_page)
            elif key == "pause":
                self.action_menu()
            elif key == "back":
                self.route(self.back_page)
            elif key.startswith("open-"):
                target = {"open-saves":"saves", "open-settings":"settings",
                          "open-achievements":"achievements", "open-editor":"editor"}[key]
                self.back_page = self.page
                self.route(target)
            elif key.startswith("settings-"):
                self.settings_section = key[9:]
                self.route("settings")
            elif key in ("apply-settings", "audio-preview"):
                self.apply_settings()
                if key == "audio-preview":
                    self.sound("click")
            elif key.startswith("load-slot-"):
                loaded = self.store.load_slot(int(key.rsplit("-", 1)[1]))
                if loaded is not None:
                    # Read first: saving the outgoing game may overwrite slot 0.
                    self.auto_save()
                    self.game = loaded
                    self.reset_visuals()
                    self.message = "已恢复保存的局面。"
                    if loaded.outcome == "playing":
                        self.route("game")
                    else:
                        self.process_result()
            elif key.startswith("save-slot-"):
                self.store.save_slot(int(key.rsplit("-", 1)[1]), self.game)
                self.route("saves")
                self.show_toast("手动存档已保存")
            elif key.startswith("delete-slot-"):
                self.store.delete_slot(int(key.rsplit("-", 1)[1]))
                self.route("saves")
            elif key == "next-level" and self.game:
                if self.game.advance():
                    self.reset_visuals()
                    self.message = self.game.description
                    self.route("game")
            elif key in ("hint", "solve", "restart"):
                getattr(self, "action_" + key)()
            elif key.startswith("editor-"):
                self.editor_action(key)
            elif key == "exit-desktop":
                self.request_desktop_exit()
            elif key in ("minimize", "github"):
                if self.host_action:
                    self.host_action("minimize" if key == "minimize" else "open_url")
                elif key == "github":
                    import webbrowser
                    webbrowser.open("https://github.com/155TuT/arrow-Y2K")
        except (DomainStorageError, ValueError, OSError) as error:
            text = str(error).replace("[", "\\[")
            self.show_toast("操作未完成", text)
            self.set_text("#editor-status" if self.editing else "#settings-status", text)
