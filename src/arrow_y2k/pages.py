"""Page inheritance supplies consistent navigation without duplicating game rules."""
from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Horizontal, Vertical, VerticalScroll, Center
from textual.widgets import Button, Static, Input, Select, Switch
from .widgets import BoardView, HeartsView, SaveHearts, TitleView, CreditsView, PixelButton, PixelSelect

MODE_NAMES = {"easy": "简单", "medium": "中等", "hard": "困难", "endless": "无尽"}


class Page(Screen):
    """Minimal Textual adapter; screen contents are composed from widgets."""
    AUTO_FOCUS = ""
    ALLOW_SELECT = False
    def header(self, title):
        return Static(title, classes="page-header")

    def toast(self):
        toast = Static("", id="achievement-toast")
        # Ask the native adapter to keep overlay CJK glyphs whole when a lower
        # widget boundary would otherwise cut the compositor's text strips.
        toast.native_complete_overlay = True
        return toast

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.app.dispatch(str(event.button.id))

    def on_mount(self):
        for button in self.query(Button):
            button.active_effect_duration = 0
        self.call_after_refresh(self.app.page_ready)


class HomePage(Page):
    def compose(self) -> ComposeResult:
        yield TitleView(id="home-title")
        with Center():
            with Vertical(id="home-menu"):
                with Horizontal(classes="button-row"):
                    yield PixelButton("开始游戏", icon="play", id="new-game", classes="primary")
                    yield PixelButton("读取存档", icon="folder", id="open-saves")
                yield PixelButton("成就", icon="trophy", id="open-achievements")
                yield PixelButton("地图创作", icon="map", id="open-editor")
                yield PixelButton("设置", icon="gear", id="open-settings")
                with Horizontal(id="home-links"):
                    yield PixelButton("退出到桌面", icon="exit", icon_only=True, id="exit-desktop", classes="danger")
                    yield Static("", id="home-links-space")
                    yield PixelButton("GitHub / 项目主页", icon="github", icon_only=True, id="github")
        yield CreditsView(classes="home-foot")
        yield self.toast()


class DifficultyPage(Page):
    def compose(self):
        yield self.header("NEW RUN / 新建游戏")
        with Center():
            with Vertical(classes="center-menu"):
                yield Static("选择起始难度", classes="section-title")
                for key, name in MODE_NAMES.items():
                    unlocked = key in self.app.store.profile.unlocked_modes
                    yield Button(name if unlocked else name + " / 尚未解锁",
                                 id="start-" + key, disabled=not unlocked)
                yield Static("所有模式从第 1 关编号开始。\n简单过第 3 关转中等；中等过第 10 关转困难。\n中等 04:00 / 困难 02:00 / 无尽 00:30\n碰撞扣时：中等 10 秒；困难 / 无尽 20 秒。\n无尽 1 颗心起步，过关 +1，最多 3 颗。", classes="mode-help")
                yield PixelButton("返回主页", icon="exit", classes="danger", id="go-home")
        yield self.toast()


class GamePage(Page):
    def compose(self):
        with Horizontal(id="game-layout"):
            yield BoardView(id="board")
            with Vertical(id="game-side"):
                yield Static("", id="level-name")
                yield Static("", id="mode-name")
                yield Static("LIFE", classes="eyebrow")
                yield HeartsView(id="hearts")
                yield Static("", id="stats")
                yield Static("", id="timer")
                yield Static("", id="combo")
                yield Static("", id="status")
                with Horizontal(classes="button-row"):
                    yield Button("提示 H", id="hint")
                    yield Button("演示 S", id="solve")
                with Horizontal(classes="button-row"):
                    yield Button("重来 R", id="restart")
                    yield Button("暂停 ESC", id="pause")
        yield self.toast()


class PausePage(Page):
    def compose(self):
        yield self.header("PAUSED / 菜单")
        with Center():
            with Vertical(classes="center-menu"):
                yield Button("继续", id="resume", classes="primary")
                yield Button("读取存档 / 手动保存", id="open-saves")
                yield Button("设置", id="open-settings")
                yield Button("最小化", id="minimize")
                yield PixelButton("退出到主页", icon="exit", classes="danger", id="go-home")
                yield PixelButton("退出到桌面", icon="exit", classes="danger", id="exit-desktop")
                yield Static("计时已暂停。\n手动保存可随时使用；自动保存遵循基本设置。", classes="mode-help")
        yield self.toast()


class ResultPage(Page):
    def compose(self):
        game = self.app.game
        lost = game.outcome == "lost"
        complete = game.outcome in ("campaign_won", "endless_won")
        title = "SIGNAL LOST / 挑战失败" if lost else "RUN COMPLETE / 模式通关" if complete else "SECTOR CLEAR / 本关通过"
        yield self.header(title)
        with Center():
            with Vertical(classes="center-menu"):
                yield Static("", id="result-summary", classes="result-summary")
                yield SaveHearts(game.session.lives, centered=True, id="result-hearts")
                if not lost and not complete and not game.custom:
                    yield Button("下一关", id="next-level", classes="primary")
                if lost or game.custom:
                    yield Button("再试一次", id="restart", classes="primary")
                yield Button("读取存档 / 手动保存", id="open-saves")
                yield PixelButton("退出到主页", icon="exit", classes="danger", id="go-home")
        yield self.toast()


class SavePage(Page):
    def compose(self):
        yield self.header("ARCHIVE / 读取存档与手动保存")
        yield Static("自动槽由定时器管理；手动槽可存入当前局面。读取会暂停当前游戏并恢复所选局面。", classes="save-help")
        for index, summary in enumerate(self.app.store.slots()):
            with Horizontal(classes="save-slot", id=f"slot-{index}"):
                title = "自动保存" if index == 0 else f"手动存档 {index}"
                if summary:
                    text = (f"{title} · 第 {summary.level_index} 关 · {MODE_NAMES[summary.difficulty]}\n"
                            f"LEFT {summary.left}/{summary.total}\n{summary.saved_at[:19].replace('T', ' ')}")
                else:
                    text = title + "\n空存档"
                yield Static(text, classes="save-info", markup=False)
                yield SaveHearts(summary.lives if summary else 0, classes="save-hearts")
                yield Button("读取", id=f"load-slot-{index}", disabled=summary is None)
                if index:
                    yield Button("存入", id=f"save-slot-{index}", disabled=self.app.game is None)
                    yield Button("删除", id=f"delete-slot-{index}", disabled=summary is None)
                else:
                    yield Static("自动覆写", classes="auto-badge")
        yield Button("返回", id="back")
        yield self.toast()


class SettingsPage(Page):
    def compose(self):
        cfg = self.app.store.settings
        section = self.app.settings_section
        yield self.header("CONFIG / 设置")
        with Horizontal(id="settings-tabs"):
            for key, label in (("basic","基本"),("audio","音频"),("video","画面"),("about","关于")):
                yield Button(label, id="settings-" + key, classes="selected" if key == section else "")
        with Center():
            with Vertical(id="settings-content"):
                if section == "basic":
                    with Horizontal(classes="setting-row"):
                        yield Static("自动保存")
                        yield Switch(cfg.autosave, animate=False, id="cfg-autosave")
                    yield Static("保存频率（分钟，1～60；游戏进行时计时）")
                    yield Input(str(cfg.save_minutes), type="integer", id="cfg-save-minutes")
                    yield Static("默认 3 分钟；退出当前游戏前也保存。\n关闭后不再覆写自动槽，四个手动槽仍可使用。", classes="mode-help")
                elif section == "audio":
                    with Horizontal(classes="setting-row"):
                        yield Static("静音")
                        yield Switch(cfg.muted, animate=False, id="cfg-muted")
                    yield Static("总音量 / 音效音量（0～100）")
                    with Horizontal(classes="button-row"):
                        yield Input(str(round(cfg.master_volume * 100)), type="integer", id="cfg-master")
                        yield Input(str(round(cfg.effects_volume * 100)), type="integer", id="cfg-effects")
                    yield Button("试听音效", id="audio-preview")
                    yield Static("合成点击、碰撞、通关与成就音效。\n音频设备不可用时仍可正常游玩。", classes="mode-help")
                elif section == "video":
                    yield Static("窗口分辨率")
                    yield PixelSelect([(s, s) for s in ("1024x768","1280x720","1920x1080")],
                                 value=cfg.resolution, allow_blank=False, id="cfg-resolution")
                    with Horizontal(classes="setting-row"):
                        yield Static("减少震动与闪动")
                        yield Switch(cfg.reduced_motion, animate=False, id="cfg-motion")
                    yield Static("保持整数像素缩放。减少震动仍保留碰撞变色\n和生命损失反馈；不改变判定规则。", classes="mode-help")
                else:
                    from . import __version__
                    yield Static(f"ARROW.AFTER.ARROW-Y2K\n版本 {__version__}\nPython / Textual / pygame-ce\n\nFusion Pixel 等宽字体 / SIL OFL 1.1", classes="about-copy")
                    yield Static(str(self.app.store.root), markup=False, classes="data-path")
                    yield Button("GitHub / 项目主页", id="github")
                yield Static("", id="settings-status")
                if section != "about":
                    yield Button("应用并保存", id="apply-settings", classes="primary")
                yield Button("返回", id="back")
        yield self.toast()


class AchievementsPage(Page):
    def compose(self):
        p = self.app.store.profile
        yield self.header("RECORDS / 成就")
        fastest = "--" if p.endless_best_seconds is None else f"{p.endless_best_seconds:.2f} 秒"
        yield Static(f"已移动 {p.total_arrows} 支箭头   /   最高连续通关 {p.best_streak}\n无尽最快完成：{fastest}", classes="record-stats")
        with VerticalScroll(id="achievement-list"):
            for achievement in self.app.achievements.list_all():
                mark = "[#72d69c]已达成[/]" if achievement.unlocked else "[#62796c]未达成[/]"
                yield Static(f"{mark}  {achievement.title}\n    {achievement.description}", classes="achievement-row")
        yield PixelButton("返回主页", icon="exit", classes="danger", id="go-home")
        yield self.toast()


class EditorPage(Page):
    def compose(self):
        app = self.app
        yield self.header("MAP STUDIO / 地图创作")
        with Horizontal(id="editor-layout"):
            with Vertical(id="editor-canvas"):
                yield BoardView(id="board")
                yield Static("", id="editor-status")
            with Vertical(id="editor-side"):
                options = [(f"{MODE_NAMES[p.difficulty]} / {p.name}", "preset:" + p.id) for p in app.presets]
                options += [(f"自作 / {p.name}", "custom:" + p.id) for p in app.store.list_custom_maps()]
                yield PixelSelect(options, value=app.editor_selection, allow_blank=False, id="map-catalog")
                yield Input(app.editor_name, id="map-name", placeholder="地图名称")
                yield PixelSelect([(MODE_NAMES[k], k) for k in ("easy","medium","hard")],
                             value=app.editor_difficulty, allow_blank=False, id="map-difficulty")
                yield Input(app.editor_seed, id="editor-seed", placeholder="生成种子")
                yield Static("密度% / 长度上限 / 转弯%", classes="eyebrow")
                with Horizontal(id="parameters"):
                    yield Input(str(app.editor_density), id="density", type="integer")
                    yield Input(str(app.editor_length), id="length", type="integer")
                    yield Input(str(app.editor_turns), id="turns", type="integer")
                yield Input(app.editor_path, id="map-path", placeholder="导入 / 导出 JSON 路径")
                with Horizontal(classes="button-row tight"):
                    yield Button("保存", id="editor-save")
                    yield Button("导出", id="editor-export")
                    yield Button("删除", id="editor-delete", disabled=not app.editor_selection.startswith("custom:"))
                with Horizontal(classes="button-row tight"):
                    yield Button("导入", id="editor-import")
                    yield Button("清空", id="editor-clear")
                    yield Button("试玩", id="editor-play", classes="primary")
                yield PixelButton("返回主页", icon="exit", classes="danger", id="go-home")
        yield self.toast()


PAGES = {"home": HomePage, "difficulty": DifficultyPage, "game": GamePage,
         "menu": PausePage, "result": ResultPage, "saves": SavePage,
         "settings": SettingsPage, "achievements": AchievementsPage, "editor": EditorPage}
