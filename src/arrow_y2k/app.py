"""The game's sole UI controller: Textual messages, widgets and animation timer."""
from __future__ import annotations

import time
from pathlib import Path
from collections.abc import Callable

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Select, Static

from .generation import GenerateConfig, generate, make_level, template_mask
from .model import GameSession
from .persistence import load_map, save_map
from .pixels import Animation
from .solver import solve
from .widgets import BoardView, HeartsView


class ArrowApp(App):
    """Composition root. Domain rules never depend on Textual or the host."""

    CSS_PATH = "game.tcss"
    TITLE = "一箭又一箭"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("r", "restart", "重来"), ("h", "hint", "提示"),
        ("s", "solve", "自动求解"), ("e", "editor", "造地图"),
        ("n", "next_level", "下一关"), ("f6", "resolution", "分辨率"),
        ("escape", "back", "返回"), ("ctrl+q", "quit", "退出"),
    ]

    def __init__(self, *, native: bool = False, level: int = 1, seed: str = "2026"):
        super().__init__()
        self.native = native
        self.level_index = level
        self.seed = seed
        self.level = make_level(level, seed=seed)
        self.session = GameSession(self.level.board)
        self.animation: Animation | None = None
        self.animation_started = 0.0
        self.animation_duration = 0.0
        self.heart_progress: float | None = None
        self.heart_started: float | None = None
        self.lost_index: int | None = None
        self.hovered: str | None = None
        self.hint_id: str | None = None
        self.failed_ids: set[str] = set()
        self.cursor = min(self.level.board.mask, key=lambda p: (p[1], p[0]))
        self.auto_solving = False
        self.assisted = False
        self.editing = False
        self.editor_mask = set(template_mask("heart", 9, 8))
        self.editor_hover = None
        self.painting = 0
        self.host_action: Callable[[str], None] | None = None
        self.resolution_name = "1280x720"
        self.message = self.level.description

    def compose(self) -> ComposeResult:
        with Horizontal(id="titlebar"):
            yield Static("[b]一箭又一箭[/b]  /  ARROW AFTER ARROW", id="brand")
            yield Button(self.resolution_name, id="resolution")
            yield Button("_", id="minimize", classes="window-button")
            yield Button("X", id="close", classes="window-button")
        with Horizontal(id="workspace"):
            with Vertical(id="play-pane"):
                yield Static(id="board-title")
                yield BoardView(id="board")
                yield Static(id="caption")
            with Vertical(id="side"):
                with Vertical(id="game-panel"):
                    with Horizontal(id="level-tabs"):
                        yield Button("01", id="level-1")
                        yield Button("02", id="level-2")
                        yield Button("03", id="level-3")
                    yield Static(id="level-name")
                    yield Static("LIFE / 生命", id="lives-label")
                    yield HeartsView(id="hearts")
                    yield Static(id="stats")
                    yield Static(id="status")
                    with Horizontal(classes="button-row"):
                        yield Button("提示 H", id="hint")
                        yield Button("演示 S", id="solve")
                    with Horizontal(classes="button-row"):
                        yield Button("重来 R", id="restart")
                        yield Button("下一关", id="next", classes="primary")
                    yield Button("+ 制作地图", id="custom")
                with Vertical(id="editor-panel", classes="hidden"):
                    yield Select([(label, key) for label, key in [
                        ("模板 / 方形", "square"), ("模板 / 长方形", "rectangle"),
                        ("模板 / 心形", "heart"), ("模板 / 菱形", "diamond"),
                        ("模板 / 环形", "ring"), ("模板 / 十字", "cross"),
                    ]], value="heart", allow_blank=False, id="template")
                    yield Static("SEED / 随机种子", classes="field-label")
                    yield Input(self.seed, placeholder="任意文字或数字", id="seed")
                    yield Static("密度% / 长度上限 / 转弯%", classes="field-label")
                    with Horizontal(id="parameters"):
                        yield Input("85", id="density", type="integer", max_length=3)
                        yield Input("12", id="length", type="integer", max_length=2)
                        yield Input("60", id="turns", type="integer", max_length=3)
                    yield Static("MAP / 本地 JSON 路径", classes="field-label")
                    yield Input("maps/my-map.json", id="map-path")
                    with Horizontal(classes="button-row", id="file-actions"):
                        yield Button("保存", id="save")
                        yield Button("载入", id="load")
                        yield Button("清空", id="clear")
                    yield Static(id="editor-status")
                    with Horizontal(classes="button-row"):
                        yield Button("生成试玩", id="generate", classes="primary")
                        yield Button("返回", id="back")
                    yield Static("左键绘制 / 右键擦除\n支持拖动连续绘制", id="editor-help")
        yield Static("H 提示   S 演示   R 重来     方向键 + Enter 选箭头", id="footer")

    def on_mount(self) -> None:
        self.set_interval(1 / 60, self.tick)
        self.refresh_labels()

    def refresh_labels(self) -> None:
        if not self.is_mounted:
            return
        count = len(self.session.remaining)
        initial = len(self.session.board.arrows)
        title = "MAP STUDIO / 地图工坊" if self.editing else self.level.name
        self.query_one("#board-title", Static).update(title)
        self.query_one("#caption", Static).update(
            "12 × 10 画布  /  每格只占用一次" if self.editing else "观察头部方向 · 点击箭头任意一格")
        self.query_one("#level-name", Static).update(self.level.name)
        self.query_one("#stats", Static).update(f"LEFT {count:02d} / {initial:02d}   ·   {len(self.session.board.mask)} 格")
        self.query_one("#status", Static).update(self.message)
        self.query_one("#editor-status", Static).update(f"已绘制 {len(self.editor_mask)} 格 · 生成后验证有解")
        self.query_one("#next", Button).disabled = self.session.status != "won" or self.animation is not None
        for key in ("hint", "solve"):
            self.query_one(f"#{key}", Button).disabled = self.session.status != "playing"
        self.query_one("#solve", Button).label = "停止 S" if self.auto_solving else "演示 S"
        self.query_one("#resolution", Button).label = self.resolution_name if self.native else "终端模式"
        for index in (1, 2, 3):
            self.query_one(f"#level-{index}").set_class(index == self.level_index and self.level.name != "种子关卡", "level-selected")
        self.query_one("#board").refresh()
        self.query_one("#hearts").refresh()

    def click_cell(self, cell) -> None:
        if self.editing or self.animation is not None or self.session.status != "playing":
            return
        self.cursor = cell
        arrow_id = self.session.current_board.occupancy.get(cell)
        if arrow_id:
            self.auto_solving = False
            self.play_arrow(arrow_id)

    def play_arrow(self, arrow_id: str) -> None:
        result = self.session.click(arrow_id)
        if result.kind == "ignored":
            return
        self.hint_id = None
        self.hovered = None
        self.animation_started = time.monotonic()
        collision = result.kind == "collision"
        self.animation_duration = 0.95 if collision else 0.65
        self.animation = Animation(result.arrow, "collision" if collision else "exit", 0.0,
                                   result.collision.distance if collision else None)
        if collision:
            self.lost_index = self.session.lives
            # The heart breaks when the arrow impacts, not during its approach.
            self.heart_started = self.animation_started + self.animation_duration * 0.28
            self.heart_progress = 0.0
            self.message = "[bold #ff5269]撞到了！[/]\n头部射线上仍有箭头。"
        else:
            self.failed_ids.discard(arrow_id)
            self.message = "路径畅通，飞出棋盘。"
        self.refresh_labels()

    def tick(self) -> None:
        now = time.monotonic()
        if self.animation is not None:
            progress = min(1.0, (now - self.animation_started) / self.animation_duration)
            self.animation = Animation(self.animation.arrow, self.animation.kind, progress,
                                       self.animation.collision_distance)
            if progress >= 1:
                if self.animation.kind == "collision":
                    self.failed_ids.add(self.animation.arrow.id)
                self.animation = None
                if self.session.status == "won":
                    mode = "演示完成" if self.assisted else "全部清空！"
                    self.message = f"[bold #b2efc8]{mode}[/]\n保留 {self.session.lives} 颗生命\n点击下一关继续。"
                    self.auto_solving = False
                elif self.session.status == "lost":
                    self.message = "[bold #ff5269]生命耗尽[/]\n按 R 重来，再试一次。"
                    self.auto_solving = False
                self.refresh_labels()
            self.query_one("#board").refresh()
        if self.heart_started is not None:
            self.heart_progress = max(0.0, min(1.0, (now - self.heart_started) / 0.7))
            self.query_one("#hearts").refresh()
            if self.heart_progress >= 1:
                self.heart_started = None
                self.heart_progress = None
                self.lost_index = None
        if self.auto_solving and self.animation is None and self.session.status == "playing" and not self.editing:
            solution = solve(self.session.current_board)
            if not solution.solvable:
                self.auto_solving = False
                self.message = "当前局面无解，请重来或调整地图。"
                self.refresh_labels()
            else:
                self.play_arrow(solution.order[0])

    def reset_visuals(self) -> None:
        self.animation = None
        self.heart_started = None
        self.heart_progress = None
        self.lost_index = None
        self.auto_solving = False
        self.assisted = False
        self.hovered = None
        self.hint_id = None
        self.failed_ids.clear()
        self.cursor = min(self.session.board.mask, key=lambda p: (p[1], p[0]))

    def load_level(self, index: int) -> None:
        self.level_index = index
        self.level = make_level(index, seed=self.seed)
        self.session = GameSession(self.level.board)
        self.reset_visuals()
        self.message = self.level.description
        self.refresh_labels()

    def action_restart(self) -> None:
        if self.editing:
            return
        self.session.restart()
        self.reset_visuals()
        self.message = "重新开始。先找朝外且路径畅通的箭头。"
        self.refresh_labels()

    def action_hint(self) -> None:
        if self.editing or self.animation or self.session.status != "playing":
            return
        solution = solve(self.session.current_board)
        self.hint_id = solution.order[0] if solution.order else None
        self.message = "[bold #b2efc8]浅绿色箭头可以飞出。[/]\n沿它头部的方向看向边界。"
        self.refresh_labels()

    def action_solve(self) -> None:
        if self.editing or self.session.status != "playing":
            return
        self.auto_solving = not self.auto_solving
        self.assisted = self.assisted or self.auto_solving
        self.message = "按通关顺序逐支演示，再按 S 停止。" if self.auto_solving else "已停止演示，可以继续手动点击。"
        self.refresh_labels()

    def action_next_level(self) -> None:
        if not self.editing and self.session.status == "won" and self.animation is None:
            self.load_level(self.level_index + 1)

    def action_editor(self) -> None:
        if self.editing:
            return
        if self.animation is not None:
            return
        self.auto_solving = False
        self.editing = True
        self.query_one("#game-panel").add_class("hidden")
        self.query_one("#editor-panel").remove_class("hidden")
        self.query_one("#footer", Static).update("地图工坊 / 模板、画布和种子组合     ESC 返回游戏")
        self.refresh_labels()

    def action_back(self) -> None:
        if self.editing:
            self.editing = False
            self.painting = 0
            self.query_one("#editor-panel").add_class("hidden")
            self.query_one("#game-panel").remove_class("hidden")
            self.query_one("#footer", Static).update("H 提示   S 演示   R 重来     方向键 + Enter 选箭头")
            self.refresh_labels()
        else:
            self.auto_solving = False
            self.refresh_labels()

    def action_resolution(self) -> None:
        if self.host_action:
            presets = ["1024x768", "1280x720", "1920x1080"]
            self.resolution_name = presets[(presets.index(self.resolution_name) + 1) % 3]
            self.host_action("resolution:" + self.resolution_name)
            self.refresh_labels()

    def paint_cell(self, cell, *, erase: bool = False) -> None:
        if cell is None:
            return
        if erase:
            self.editor_mask.discard(cell)
        else:
            self.editor_mask.add(cell)
        self.refresh_labels()

    @on(Select.Changed, "#template")
    def choose_template(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            self.editor_mask = set(template_mask(str(event.value), 9, 8))
            self.refresh_labels()

    def editor_config(self) -> GenerateConfig:
        return GenerateConfig(
            seed=self.query_one("#seed", Input).value,
            density=int(self.query_one("#density", Input).value) / 100,
            max_length=int(self.query_one("#length", Input).value),
            turn_bias=int(self.query_one("#turns", Input).value) / 100,
        )

    def editor_action(self, action: str) -> None:
        try:
            path = Path(self.query_one("#map-path", Input).value).expanduser()
            if action == "generate":
                config = self.editor_config()
                self.level = generate(frozenset(self.editor_mask), config)
                self.session = GameSession(self.level.board)
                self.seed = config.seed
                self.reset_visuals()
                self.message = "[bold #b2efc8]有解验证通过[/]\n种子：" + self.seed.replace("[", "\\[")
                self.action_back()
            elif action == "save":
                save_map(path, frozenset(self.editor_mask), self.editor_config())
                self.query_one("#editor-status", Static).update("已保存：" + path.name)
            elif action == "load":
                mask, config = load_map(path)
                if any(x >= 12 or y >= 10 for x, y in mask):
                    raise ValueError("画布最大为 12 × 10 格")
                self.editor_mask = set(mask)
                for key, value in [("seed", config.seed), ("density", round(config.density * 100)),
                                   ("length", config.max_length), ("turns", round(config.turn_bias * 100))]:
                    self.query_one(f"#{key}", Input).value = str(value)
                self.refresh_labels()
                self.query_one("#editor-status", Static).update("地图与种子参数已载入")
            elif action == "clear":
                self.editor_mask.clear()
                self.refresh_labels()
        except (ValueError, OSError, TypeError, KeyError) as error:
            self.query_one("#editor-status", Static).update("[red]" + str(error).replace("[", "\\[") + "[/]")

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        key = event.button.id
        if key and key.startswith("level-"):
            self.load_level(int(key[-1]))
        elif key in ("hint", "solve", "restart", "resolution"):
            getattr(self, f"action_{key}")()
        elif key == "next":
            self.action_next_level()
        elif key == "custom":
            self.action_editor()
        elif key == "back":
            self.action_back()
        elif key in ("generate", "save", "load", "clear"):
            self.editor_action(key)
        elif key == "close":
            self.exit()
        elif key == "minimize" and self.host_action:
            self.host_action("minimize")
