"""Native art must obey ordinary Textual popup and input layering."""

import asyncio
from types import SimpleNamespace

from PIL import Image
from textual.app import App
from textual.geometry import Region
from textual.widgets import Button, Select, Static, Tooltip

from arrow_y2k.desktop import PixelHost, compose_frame, configure_native_colors, _rasterize_strips
from arrow_y2k.fonts import CELL_HEIGHT, CELL_WIDTH


class NativeButton(Button):
    native_full_region = True

    def native_frame(self, width, height):
        return Image.new("RGB", (width, height), (255, 0, 128))


class PopupApp(App):
    CSS = """
    Screen { layers: base overlay; background: #10171b; }
    NativeButton { position: absolute; layer: base; width: 12; min-width: 0; height: 5; }
    #under-left { offset: 6 2; }
    #under-right { offset: 18 2; }
    Tooltip#notice { position: absolute; layer: overlay; display: block;
                    width: 26; height: 3; margin: 0; padding: 1 2;
                    color: #72d69c; background: #263c43; }
    Select { position: absolute; layer: overlay; width: 28; height: 3; offset: 5 0; }
    """

    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay

    def compose(self):
        yield NativeButton("left", id="under-left")
        yield NativeButton("right", id="under-right")
        if self.overlay == "tooltip":
            yield Tooltip("GitHub / 项目主页", id="notice")
        else:
            yield Select([("项目主页", "home"), ("返回主页", "back"), ("读取存档", "load")],
                         value="home", allow_blank=False)



def test_expanded_select_covers_native_buttons():
    async def scenario():
        app = PopupApp("select")
        configure_native_colors(app)
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.click(Select)
            await pilot.pause()
            overlay = app.query_one("SelectOverlay")
            assert overlay.display and overlay.region.overlaps(app.query_one("#under-left").region)
            region = overlay.region
            expected = _rasterize_strips(
                overlay.render_lines(Region(0, 0, region.width, region.height)),
                (region.width * CELL_WIDTH, region.height * CELL_HEIGHT),
            )
            frame = compose_frame(app, (360, 240))
            actual = frame.crop((region.x * CELL_WIDTH, region.y * CELL_HEIGHT,
                                 region.right * CELL_WIDTH, region.bottom * CELL_HEIGHT))
            assert actual.tobytes() == expected.tobytes()
            assert (255, 0, 128) not in actual.get_flattened_data()
    asyncio.run(scenario())


def test_full_region_native_renderer_replaces_border_as_well_as_content():
    async def scenario():
        app = PopupApp("tooltip")
        configure_native_colors(app)
        async with app.run_test(size=(60, 20)) as pilot:
            tooltip = app.query_one("#notice")
            tooltip.display = False
            await pilot.pause()
            button = app.query_one("#under-left")
            button.native_complete_overlay = True
            frame = compose_frame(app, (360, 240))
            assert frame.getpixel((button.region.x * CELL_WIDTH, button.region.y * CELL_HEIGHT)) == (255, 0, 128)
            assert frame.getpixel((button.content_region.x * CELL_WIDTH, button.content_region.y * CELL_HEIGHT)) == (255, 0, 128)
    asyncio.run(scenario())


def test_header_button_keeps_click_while_title_area_still_drags(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame

    class HeaderApp(App):
        CSS = """
        #back { width: 14; height: 3; }
        #title { position: absolute; offset: 16 0; width: 30; height: 3; }
        """
        window_drag_region = (0, 0, 480, 36)

        def __init__(self):
            super().__init__()
            self.presses = 0

        def compose(self):
            yield Button("返回主页", id="back")
            yield Static("PAGE / 页面", id="title")

        def on_button_pressed(self):
            self.presses += 1

    async def scenario():
        app = HeaderApp()
        host = PixelHost(app)
        host._pygame = pygame
        captures = []
        host._geometry = SimpleNamespace(global_pointer=lambda: (50, 50), capture_pointer=captures.append)
        host._window = SimpleNamespace(position=(100, 100))
        pygame.display.init()
        try:
            async with app.run_test(size=(80, 30)) as pilot:
                await pilot.pause()
                point = (4 * CELL_WIDTH * host.resolution.scale, CELL_HEIGHT * host.resolution.scale)
                host.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point))
                host.process_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=point))
                await pilot.pause()
                assert app.presses == 1
                assert host._drag is None and not captures
                title_point = (20 * CELL_WIDTH * host.resolution.scale, CELL_HEIGHT * host.resolution.scale)
                host.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=title_point))
                assert host._drag is not None and captures[-1]
        finally:
            pygame.display.quit()
    asyncio.run(scenario())
