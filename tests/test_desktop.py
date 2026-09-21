"""Exercise the native bridge against real Textual widgets and messages."""

import asyncio

import pytest

from PIL import Image
from textual import events
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Input

from arrow_y2k.desktop import PixelHost, RESOLUTIONS, compose_frame, configure_native_colors, mouse_message, raster_point
from arrow_y2k.fonts import glyph_mask, pixel_font


class Art(Widget):
    DEFAULT_CSS = "Art { width: 10; height: 4; }"

    def __init__(self):
        super().__init__()
        self.points = []

    def native_frame(self, width, height):
        return Image.new("RGB", (width, height), (250, 0, 80))

    def on_mouse_down(self, event):
        self.points.append(raster_point(event, self))

    def on_mouse_move(self, event):
        self.points.append(raster_point(event, self))


class BridgeApp(App):
    CSS = "Screen { background: #123456; }"
    def __init__(self):
        super().__init__()
        self.presses = 0

    def compose(self) -> ComposeResult:
        yield Button("开始 PLAY", id="play")
        yield Input(id="seed")
        yield Art()

    def on_button_pressed(self, event):
        self.presses += 1


def test_bundled_font_matches_terminal_and_has_binary_coverage():
    font = pixel_font()
    assert font.getlength("A") == 6
    assert font.getlength("箭") == 12
    assert glyph_mask("箭").size == (12, 12)
    assert set(glyph_mask("箭").get_flattened_data()) <= {0, 1, 255}


def test_integer_resolution_presets():
    assert [preset.scale for preset in RESOLUTIONS.values()] == [2, 2, 3]
    for preset in RESOLUTIONS.values():
        w, h = preset.logical_size
        assert (w * preset.scale, h * preset.scale) == (preset.width, preset.height)


def test_bridge_routes_actual_buttons_input_and_subcell_mouse():
    async def scenario():
        app = BridgeApp()
        configure_native_colors(app)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            button = app.query_one("#play", Button)
            point = (button.region.x * 6 + 12, button.region.y * 12 + 12)
            app.post_message(mouse_message(events.MouseDown, point))
            app.post_message(mouse_message(events.MouseUp, point))
            await pilot.pause()
            assert app.presses == 1
            field = app.query_one("#seed", Input)
            point = (field.content_region.x * 6 + 7, field.content_region.y * 12 + 3)
            app.post_message(mouse_message(events.MouseDown, point))
            app.post_message(mouse_message(events.MouseUp, point))
            app.post_message(events.Key("7", "7"))
            await pilot.pause()
            assert field.value == "7"
            art = app.query_one(Art)
            point = (art.content_region.x * 6 + 17, art.content_region.y * 12 + 19)
            app.post_message(mouse_message(events.MouseDown, point))
            app.post_message(mouse_message(events.MouseMove, point))
            await pilot.pause()
            assert art.points == [(17, 19), (17, 19)]
            frame = compose_frame(app, (480, 360))
            assert frame.getpixel(point) == (250, 0, 80)
            assert frame.size == (480, 360)
            assert frame.getpixel((479, 359)) == (0x12, 0x34, 0x56)

    asyncio.run(scenario())


def test_sdl_resize_and_committed_text_input(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame

    async def scenario():
        app = BridgeApp()
        host = PixelHost(app)
        host._pygame = pygame
        pygame.display.init()
        try:
            async with app.run_test(size=(106, 30)) as pilot:
                for resolution, expected in (("1024x768", (85, 32)), ("1920x1080", (106, 30)), ("1280x720", (106, 30))):
                    host.handle_action("resolution:" + resolution)
                    await pilot.pause()
                    assert tuple(app.size) == expected
                field = app.query_one(Input)
                field.focus()
                host.process_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="a", mod=0))
                host.process_event(pygame.event.Event(pygame.TEXTINPUT, text="a箭"))
                await pilot.pause()
                assert field.value == "a箭"
                pygame.scrap.put_text("种子-42")
                host.process_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v, unicode="", mod=pygame.KMOD_CTRL))
                await pilot.pause()
                assert field.value == "a箭种子-42"
                frame = compose_frame(app, host.resolution.logical_size)
                assert frame.getpixel((0, 359)) == (0x12, 0x34, 0x56)
        finally:
            pygame.display.quit()

    asyncio.run(scenario())


def test_native_exit_variants_call_save_boundary_once(monkeypatch):
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame

    for action in ("quit", "alt-f4", "close"):
        app = BridgeApp()
        calls = []
        app.request_desktop_exit = lambda: calls.append("saved-and-exited")
        host = PixelHost(app)
        host._pygame = pygame
        host.running = True
        if action == "quit":
            event = pygame.event.Event(pygame.QUIT)
            host.process_event(event)
            host.process_event(event)
        elif action == "alt-f4":
            event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F4, unicode="", mod=pygame.KMOD_ALT)
            host.process_event(event)
        else:
            host.handle_action("close")
        assert calls == ["saved-and-exited"]
        assert not host.running


def test_header_drag_is_disabled_for_gameplay_and_opt_in_elsewhere(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame

    app = BridgeApp()
    messages = []
    app.post_message = messages.append
    host = PixelHost(app)
    host._pygame = pygame
    pygame.display.init()
    try:
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(80, 16))
        app.allow_window_drag = False
        host.process_event(event)
        assert host._drag is None
        assert isinstance(messages[-1], events.MouseDown)
        messages.clear()
        app.allow_window_drag = True
        host.process_event(event)
        assert host._drag == (80, 16)
        assert not messages
    finally:
        pygame.display.quit()


def test_project_link_capability_has_no_arbitrary_url_parameter(monkeypatch):
    from arrow_y2k.desktop import PROJECT_URL
    import arrow_y2k.desktop as desktop
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, new: opened.append((url, new)))
    host = PixelHost(BridgeApp())
    host.handle_action("open_url")
    assert opened == [(PROJECT_URL, 2)]
    import pytest
    with pytest.raises(ValueError):
        host.handle_action("open_url:https://example.invalid")


@pytest.mark.parametrize("resolution", tuple(RESOLUTIONS))
def test_native_overlay_preserves_cjk_glyph_across_underlying_button_boundary(resolution):
    from textual.containers import Horizontal
    from textual.widgets import Static
    from rich.cells import cell_len

    class OverlayApp(App):
        CSS = """
        Screen { layers: base overlay; background: #10171b; }
        #underlay { position: absolute; layer: base; width: 24; height: 3; }
        #underlay Button { width: 12; min-width: 0; height: 3; }
        #notice { position: absolute; layer: overlay; width: 26; height: 5;
                  background: #172a20; color: #72d69c; border: solid #72d69c;
                  padding: 0 1; }
        """
        def compose(self):
            with Horizontal(id="underlay"):
                yield Button("LEFT")
                yield Button("RIGHT")
            notice = Static("成就达成 / 百箭穿杨\n累计成功移除 100 支箭头。", id="notice")
            notice.native_complete_overlay = True
            yield notice

        def on_mount(self):
            width, height = self.size
            self.query_one("#underlay").styles.offset = (width - 25, height - 6)
            self.query_one("#notice").styles.offset = (width - 27, height - 6)

    async def scenario():
        app = OverlayApp()
        configure_native_colors(app)
        preset = RESOLUTIONS[resolution]
        async with app.run_test(size=preset.terminal_size) as pilot:
            await pilot.pause()
            notice = app.query_one("#notice")
            # The lower buttons' division lies in the middle of the two-cell
            # character. Rewriting the title or shifting one resolution does
            # not satisfy this regression.
            glyph_x = notice.content_region.x + cell_len("成就达成 / ")
            division = app.query_one("#underlay").region.x + 12
            assert glyph_x < division < glyph_x + 2
            frame = compose_frame(app, preset.logical_size)
            physical = frame.resize((preset.width, preset.height), Image.Resampling.NEAREST)
            glyph = glyph_mask("百")
            for y in range(glyph.height):
                for x in range(glyph.width):
                    if glyph.getpixel((x, y)):
                        source = (glyph_x * 6 + x, notice.content_region.y * 12 + y)
                        assert frame.getpixel(source) == (0x72, 0xd6, 0x9c)
                        assert physical.getpixel((source[0] * preset.scale, source[1] * preset.scale)) == (0x72, 0xd6, 0x9c)

    asyncio.run(scenario())
