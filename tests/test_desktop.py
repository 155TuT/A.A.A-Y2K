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


def test_header_drag_uses_full_width_and_global_pointer_without_stealing_board(monkeypatch):
    from types import SimpleNamespace
    from arrow_y2k.windowing import WorkArea
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame

    app = BridgeApp()
    messages, captures, resets = [], [], []
    app.post_message = messages.append
    app.reset_pointer_state = lambda: resets.append(True)
    app.window_drag_region = (0, 0, 640, 12)
    host = PixelHost(app)
    host._pygame = pygame
    # Global x is negative on a monitor to the left of the primary display.
    pointer = [-820, 110]
    host._geometry = SimpleNamespace(
        global_pointer=lambda: tuple(pointer),
        capture_pointer=captures.append,
        work_areas=lambda: [WorkArea(-1920, 0, 1920, 1040)],
    )
    host._window = SimpleNamespace(position=(-1800, 100))
    pygame.display.init()
    try:
        # Right end of the header works; the previous 150-source-pixel limit
        # made most of the title strip unusable.
        host.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(980, 10)))
        assert host._drag is not None
        assert not messages
        pointer[:] = [-720, 145]
        host.process_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(1080, 45), rel=(100, 35), buttons=(1, 0, 0)))
        assert host._window.position == (-1700, 135)
        # SDL local coordinates change as the window moves. Using this stale
        # local position would move the window back, causing visible jitter.
        host.process_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(980, 10), rel=(0, 0), buttons=(1, 0, 0)))
        assert host._window.position == (-1700, 135)
        pointer[:] = [-650, 175]
        host.process_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(1050, 40), rel=(70, 30), buttons=(1, 0, 0)))
        assert host._window.position == (-1630, 165)
        host.process_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(980, 10)))
        assert host._drag is None and captures[-1] is False
        # The game/editor begin below the first logical row; those clicks are
        # ordinary lossless Textual messages, regardless of page name.
        host.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(980, 24)))
        assert isinstance(messages[-1], events.MouseDown)
        assert host._drag is None
    finally:
        pygame.display.quit()


def test_native_mouse_resets_on_leave_blur_minimize_and_restore(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    app = BridgeApp()
    resets, messages = [], []
    app.reset_pointer_state = lambda: resets.append(True)
    app.post_message = messages.append
    host = PixelHost(app)
    host._pygame = pygame
    pygame.display.init()
    pygame.display.set_mode((320, 240))
    try:
        for kind in (pygame.WINDOWLEAVE, pygame.WINDOWFOCUSLOST,
                     pygame.WINDOWMINIMIZED, pygame.WINDOWRESTORED, pygame.WINDOWFOCUSGAINED):
            host._drag = ((0, 0), (0, 0))
            host.process_event(pygame.event.Event(kind))
            assert host._drag is None
        host.handle_action("minimize")
        assert len(resets) == 6
        assert [type(message) for message in messages] == [events.AppBlur, events.AppFocus]
    finally:
        pygame.display.quit()


def test_motion_coalescing_preserves_click_order_and_every_painted_cell(monkeypatch):
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    host = PixelHost(BridgeApp())
    host._pygame = pygame
    delivered = []
    host.process_event = delivered.append
    motion = lambda x, held=False: pygame.event.Event(
        pygame.MOUSEMOTION, pos=(x, 80), rel=(1, 0), buttons=(int(held), 0, 0))
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(10, 80))
    up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(14, 80))
    batch = [*[motion(x) for x in range(10)], down,
             *[motion(x, True) for x in range(10, 15)], up,
             *[motion(x) for x in range(15, 20)]]
    host.process_events(batch)
    assert delivered == [batch[9], down, *batch[11:16], up, batch[-1]]
    assert sum(event.type == pygame.MOUSEBUTTONDOWN for event in delivered) == 1
    assert sum(event.type == pygame.MOUSEBUTTONUP for event in delivered) == 1


def test_window_placement_keeps_integer_size_and_handles_negative_monitors():
    from arrow_y2k.windowing import WorkArea, choose_work_area, place_window
    main = WorkArea(0, 0, 2560, 1400)
    left = WorkArea(-1920, -200, 1920, 1040)
    assert choose_work_area([main, left], (-1700, 0, 1280, 720)) == left
    assert place_window((1920, 1080), main, (640, 500)) == (640, 320)
    assert place_window((1920, 1080), left, (-1700, 0)) == (-1920, -200)
    assert place_window((1280, 720), left) == (-1600, -40)
    assert place_window((1280, 720), main, (9999, 9999)) == (1280, 680)
    assert choose_work_area([main, left], (-4000, -300, 300, 200)) == left


def test_sdl_actual_resize_repositions_into_selected_work_area(monkeypatch):
    from types import SimpleNamespace
    from arrow_y2k.windowing import DesktopGeometry, WorkArea, place_window
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    app = BridgeApp()
    app.post_message = lambda message: None
    host = PixelHost(app)
    host._pygame = pygame
    pygame.display.init()
    try:
        # Exercise the real shipped SDL ctypes adapter as well as the pure
        # geometry helper. Dummy has one usable display but no global pointer.
        geometry = DesktopGeometry(pygame)
        assert geometry.sdl is not None
        assert geometry.work_areas()
        assert geometry.global_pointer() is None
        host._geometry = SimpleNamespace(
            work_areas=lambda: [WorkArea(-1920, 0, 1920, 1040), WorkArea(0, 0, 2560, 1400)],
            capture_pointer=lambda enabled: None,
        )
        host._set_resolution("1280x720")
        host._window.position = (640, 500)
        host._set_resolution("1920x1080")
        expected = place_window(host.shell.outer_size, WorkArea(0, 0, 2560, 1400), (640, 500))
        assert tuple(host._window.position) == expected
        assert pygame.display.get_window_size() == host.shell.outer_size
        host._set_resolution("1280x720")
        host._window.position = (-1700, 200)
        host._set_resolution("1920x1080")
        assert tuple(host._window.position) == (-1920, 0)
        assert pygame.display.get_window_size() == host.shell.outer_size
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


@pytest.mark.parametrize("handle,cancel_event", [
    ("menu", "WINDOWLEAVE"), ("menu", "WINDOWFOCUSLOST"), ("frame", "WINDOWLEAVE"),
])
@pytest.mark.parametrize("batched", [False, True])
async def test_cancelled_shell_press_never_repeats_previous_tui_click(tmp_path, monkeypatch, handle, cancel_event, batched):
    from arrow_y2k.app import ArrowApp
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    app = ArrowApp(data_dir=tmp_path, clock=lambda: 0.0)
    app.audio.play = lambda _: True
    host = PixelHost(app)
    host._pygame = pygame
    pygame.display.init()
    try:
        host._set_resolution("1280x720", notify=False)
        async with app.run_test(size=(106, 30)) as pilot:
            app.route("settings")
            await pilot.pause()
            actions = []
            app.dispatch = actions.append
            region = app.screen.query_one("#apply-settings").region
            point = host.shell.forward_point((region.x * 6 + region.width * 3,
                                              region.y * 12 + region.height * 6))
            def mouse(kind, position, **extra):
                host.process_event(pygame.event.Event(kind, pos=position, **extra))
            def click():
                mouse(pygame.MOUSEBUTTONDOWN, point, button=1)
                mouse(pygame.MOUSEBUTTONUP, point, button=1)
            click()
            if not batched:
                await pilot.pause()
                assert actions == ["apply-settings"]
            if handle == "menu":
                x, y, width, height = host.shell.control_rects["menu"]
                shell_point = (x + width // 2, y + height // 2)
            else:
                shell_point = (10, 10)
            mouse(pygame.MOUSEBUTTONDOWN, shell_point, button=1)
            assert host._pressed_control == "menu" if handle == "menu" else host._drag is not None
            host.process_event(pygame.event.Event(getattr(pygame, cancel_event)))
            assert host._pressed_control is None and host._drag is None
            mouse(pygame.MOUSEMOTION, point, rel=(0, 0), buttons=(1, 0, 0))
            mouse(pygame.MOUSEBUTTONUP, point, button=1)
            await pilot.pause()
            assert actions == ["apply-settings"]
            assert not app.store.settings.monochrome
            click()
            await pilot.pause()
            assert actions == ["apply-settings", "apply-settings"]
            click()
            click()
            await pilot.pause()
            assert actions == ["apply-settings"] * 4
    finally:
        pygame.display.quit()


async def test_host_keeps_paired_right_erase_and_left_paint_events(tmp_path, monkeypatch):
    from arrow_y2k.app import ArrowApp
    from arrow_y2k.pixels import board_metrics
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    app = ArrowApp(data_dir=tmp_path, clock=lambda: 0.0)
    app.audio.play = lambda _: True
    host = PixelHost(app)
    host._pygame = pygame
    pygame.display.init()
    try:
        host._set_resolution("1280x720", notify=False)
        async with app.run_test(size=(106, 30)) as pilot:
            app.route("editor")
            await pilot.pause()
            board = app.screen.query_one("#board")
            region = board.content_region
            geometry = board_metrics(region.width * 6, region.height * 12, board.mask)
            cell = (1, 1)
            app.editor_mask = {cell}
            source = (region.x * 6 + geometry.origin_x + ((cell[0] - geometry.min_x) * 16 + 8) * geometry.scale,
                      region.y * 12 + geometry.origin_y + ((cell[1] - geometry.min_y) * 16 + 8) * geometry.scale)
            point = host.shell.forward_point(source)
            for button in (3, 1):
                host.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=point))
                await pilot.pause()
                assert app.painting == button
                assert (cell in app.editor_mask) == (button == 1)
                host.process_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=button, pos=point))
                await pilot.pause()
                assert app.painting == 0
                assert not host._screen_mouse_buttons
    finally:
        pygame.display.quit()
