"""Borderless SDL display adapter for the *real* Textual application.

Textual owns layout, focus, buttons, inputs, messages and the gameplay timer.
SDL only supplies an OS window, input and presentation. The adapter's sole
private Textual API dependency is isolated in ``_textual_surface`` and pinned
to Textual 6.12.0. No gameplay or UI component is reimplemented here.
"""

from __future__ import annotations

import asyncio
import os
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw
from rich.cells import cell_len
from textual import events
from textual.geometry import Region

from .fonts import CELL_HEIGHT, CELL_WIDTH, draw_text
from .windowing import DesktopGeometry, choose_work_area, place_window

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget


@dataclass(frozen=True)
class Resolution:
    width: int
    height: int
    scale: int

    @property
    def logical_size(self) -> tuple[int, int]:
        return self.width // self.scale, self.height // self.scale

    @property
    def terminal_size(self) -> tuple[int, int]:
        width, height = self.logical_size
        return width // CELL_WIDTH, height // CELL_HEIGHT


RESOLUTIONS = {
    "1024x768": Resolution(1024, 768, 2),
    "1280x720": Resolution(1280, 720, 2),
    "1920x1080": Resolution(1920, 1080, 3),
}
BACKGROUND = (11, 14, 22)
FOREGROUND = (240, 243, 248)
PROJECT_URL = "https://github.com/155TuT/arrow-Y2K"


def configure_native_colors(app: App) -> None:
    """The graphical display is RGB even if its launching terminal sets NO_COLOR."""
    from textual.filter import Monochrome, NoColor

    for line_filter in app.get_line_filters():
        if isinstance(line_filter, (Monochrome, NoColor)):
            line_filter.enabled = False
    app.no_color = False


def raster_point(event: events.MouseEvent, widget: Widget) -> tuple[int, int]:
    """Map a forwarded Textual mouse event to exact widget source pixels.

Textual preserves floating pointer coordinates while its normal ``x`` / ``y``
properties remain terminal cells. This avoids mutable global pointer state and
also survives Textual's MouseMove translation and MouseDown event cloning.
"""
    region = widget.content_region
    return (
        round(event.pointer_screen_x * CELL_WIDTH) - region.x * CELL_WIDTH,
        round(event.pointer_screen_y * CELL_HEIGHT) - region.y * CELL_HEIGHT,
    )


def mouse_message(
    kind: type[events.MouseEvent],
    point: tuple[int, int],
    *,
    button: int = 1,
    shift: bool = False,
    ctrl: bool = False,
    meta: bool = False,
) -> events.MouseEvent:
    """Create ordinary Textual input with lossless source-pixel coordinates."""
    x, y = point[0] / CELL_WIDTH, point[1] / CELL_HEIGHT
    return kind(None, x, y, 0, 0, button, shift, meta, ctrl, screen_x=x, screen_y=y)


def _color(color: object, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if color is None or getattr(color, "is_default", False):
        return fallback
    return tuple(color.get_truecolor())


def _textual_surface(app: App):
    """Single version-bound bridge to Textual's already-composed screen."""
    with app._context():
        compositor = app.screen._compositor
        strips = compositor.render_strips()
        visible = list(compositor.visible_widgets.items())
        overlays = []
        for widget, (_, clip) in reversed(visible):
            renderer = getattr(widget, "native_frame", None)
            complete_overlay = getattr(widget, "native_complete_overlay", False)
            if (renderer is None and not complete_overlay) or not widget.visible:
                continue
            region = widget.region if complete_overlay else widget.content_region
            width, height = region.width * CELL_WIDTH, region.height * CELL_HEIGHT
            if not width or not height:
                continue
            if complete_overlay:
                # Textual's global strips may split a wide CJK glyph at an
                # underlying widget boundary. Its own full render_lines keep
                # the glyph intact and preserve Textual's styles and borders.
                lines = widget.render_lines(Region(0, 0, region.width, region.height))
                art = _rasterize_strips(lines, (width, height))
            else:
                art = renderer(width, height)
            overlays.append((region, clip, art))
    return strips, overlays


def _rasterize_strips(strips, size: tuple[int, int]) -> Image.Image:
    """One shared path for Textual colours, glyphs, backgrounds and underline."""
    frame = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(frame)
    for row, strip in enumerate(strips):
        y = row * CELL_HEIGHT
        x = 0
        for segment in strip:
            if segment.control:
                continue
            width = cell_len(segment.text) * CELL_WIDTH
            style = segment.style
            foreground = _color(style.color if style else None, FOREGROUND)
            background = _color(style.bgcolor if style else None, BACKGROUND)
            if style and style.reverse:
                foreground, background = background, foreground
            if width:
                draw.rectangle((x, y, x + width - 1, y + CELL_HEIGHT - 1), fill=background)
                draw_text(frame, (x, y), segment.text, foreground)
                if style and style.underline:
                    draw.line((x, y + CELL_HEIGHT - 1, x + width - 1, y + CELL_HEIGHT - 1), fill=foreground)
            x += width

    return frame


def compose_frame(app: App, logical_size: tuple[int, int]) -> Image.Image:
    """Compose a native-resolution frame usable by any embedding host.

The real Textual compositor supplies every ordinary widget. Widgets may expose
``native_frame(width, height) -> PIL.Image`` for pixel art inside their content
region. Only visible widgets are overlaid, clipped to their Textual viewport.
"""
    strips, overlays = _textual_surface(app)
    frame = _rasterize_strips(strips, logical_size)

    # Compositor visible_widgets is front-to-back; overlay in painter order.
    for region, clip, art in overlays:
        width, height = region.width * CELL_WIDTH, region.height * CELL_HEIGHT
        if art.size != (width, height):
            raise ValueError("native_frame must return exactly its requested source-pixel size")
        visible_region = region.intersection(clip)
        if not visible_region:
            continue
        left = (visible_region.x - region.x) * CELL_WIDTH
        top = (visible_region.y - region.y) * CELL_HEIGHT
        cropped = art.crop((left, top, left + visible_region.width * CELL_WIDTH, top + visible_region.height * CELL_HEIGHT))
        frame.paste(cropped, (visible_region.x * CELL_WIDTH, visible_region.y * CELL_HEIGHT))
    return frame


class PixelHost:
    """One borderless window around a Textual app; embedders can use compose_frame."""

    def __init__(self, app: App, resolution: str = "1280x720") -> None:
        self.app = app
        configure_native_colors(app)
        self.resolution_name = resolution
        self.resolution = RESOLUTIONS[resolution]
        self.running = False
        self._pygame = None
        self._display = None
        self._window = None
        self._drag = None
        self._geometry = None
        self._exit_requested = False

    def _request_exit(self) -> None:
        """All user exits cross the app boundary so its active game is saved."""
        if self._exit_requested:
            return
        self._exit_requested = True
        callback = getattr(self.app, "request_desktop_exit", None)
        if callback is not None:
            callback()
        else:
            self.app.exit()
        self.running = False

    def handle_action(self, action: str) -> None:
        """Small host capability boundary called by ordinary Textual buttons."""
        if action == "close":
            self._request_exit()
        elif action == "open_url":
            webbrowser.open(PROJECT_URL, new=2)
        elif action == "minimize":
            self._reset_pointer()
            self._pygame.display.iconify()
        elif action.startswith("resolution:"):
            self._set_resolution(action.split(":", 1)[1])
        else:
            raise ValueError(f"Unknown host action: {action}")

    @property
    def geometry(self):
        if self._geometry is None:
            self._geometry = DesktopGeometry(self._pygame)
        return self._geometry

    def _set_resolution(self, name: str, *, notify: bool = True) -> None:
        # Select the monitor using the OLD rectangle: a bigger new rectangle
        # could overlap an adjacent display and unexpectedly move there.
        previous = tuple(self._window.position) if self._window is not None else None
        old_size = (self.resolution.width, self.resolution.height)
        self._reset_pointer()
        self.resolution_name = name
        self.resolution = RESOLUTIONS[name]
        size = (self.resolution.width, self.resolution.height)
        self._display = self._pygame.display.set_mode(size, self._pygame.NOFRAME)
        self._window = self._pygame.Window.from_display_module()
        origin = previous if previous is not None else tuple(self._window.position)
        area = choose_work_area(self.geometry.work_areas(), (*origin, *old_size))
        self._window.position = place_window(size, area, previous)
        if notify:
            self.app.post_message(events.Resize.from_dimensions(self.resolution.terminal_size, self.resolution.logical_size))

    def _reset_pointer(self) -> None:
        self._drag = None
        if self._geometry is not None:
            self.geometry.capture_pointer(False)
        callback = getattr(self.app, "reset_pointer_state", None)
        if callback is not None:
            callback()

    def _start_drag(self, event, point) -> bool:
        region = getattr(self.app, "window_drag_region", None)
        if region is None or self._window is None:
            return False
        x, y, width, height = region
        if not (x <= point[0] < x + width and y <= point[1] < y + height):
            return False
        self._reset_pointer()
        self._drag = (self.geometry.global_pointer(), tuple(self._window.position))
        self.geometry.capture_pointer(True)
        return True

    def process_events(self, events_to_process) -> None:
        """Collapse passive pointer motion, without dropping clicks or drawing.

        Motion runs stop at every other event. Button/keyboard ordering and all
        held-button strokes remain lossless, including the map editor's paint.
        """
        pending = None
        pg = self._pygame
        for event in events_to_process:
            if event.type == pg.MOUSEMOTION and not any(event.buttons) and self._drag is None:
                pending = event
                continue
            if pending is not None:
                self.process_event(pending)
                pending = None
            self.process_event(event)
        if pending is not None:
            self.process_event(pending)

    def _key_message(self, event) -> events.Key | None:
        pg = self._pygame
        key = pg.key.name(event.key)
        names = {
            "return": "enter", "escape": "escape", "backspace": "backspace",
            "delete": "delete", "tab": "tab", "space": "space",
            "page up": "pageup", "page down": "pagedown",
            "left ctrl": "", "right ctrl": "", "left shift": "", "right shift": "",
            "left alt": "", "right alt": "", "left gui": "", "right gui": "",
        }
        key = names.get(key, key)
        if not key:
            return None
        ctrl = bool(event.mod & pg.KMOD_CTRL)
        alt = bool(event.mod & pg.KMOD_ALT)
        shift = bool(event.mod & pg.KMOD_SHIFT)
        character = event.unicode if event.unicode and event.unicode.isprintable() else None
        # SDL sends committed printable input separately as TEXTINPUT, including
        # Chinese IME commits. Using both events would duplicate ASCII input.
        if character and not ctrl and not alt:
            return None
        if ctrl:
            key = "ctrl+" + key
            character = None
        elif alt:
            key = "alt+" + key
            character = None
        elif shift and (character is None or key == "tab"):
            key = "shift+" + key
        elif character and key != "space":
            key = character
        return events.Key(key, character)

    def process_event(self, event) -> None:
        """Forward an SDL event; this method can be exercised without OS input."""
        pg = self._pygame
        if event.type == pg.QUIT:
            self._request_exit()
        elif event.type == pg.KEYDOWN:
            if event.key == pg.K_F4 and event.mod & pg.KMOD_ALT:
                self._request_exit()
                return
            if event.key == pg.K_v and event.mod & pg.KMOD_CTRL:
                text = pg.scrap.get_text()
                if text:
                    self.app.post_message(events.Paste(text))
                return
            message = self._key_message(event)
            if message is not None:
                self.app.post_message(message)
        elif event.type == pg.TEXTINPUT:
            for character in event.text:
                self.app.post_message(events.Key("space" if character == " " else character, character))
        elif event.type in (pg.WINDOWFOCUSLOST, pg.WINDOWLEAVE, pg.WINDOWMINIMIZED):
            self._reset_pointer()
            if event.type == pg.WINDOWFOCUSLOST:
                self.app.post_message(events.AppBlur())
        elif event.type in (pg.WINDOWFOCUSGAINED, pg.WINDOWRESTORED):
            self._reset_pointer()
            if event.type == pg.WINDOWFOCUSGAINED:
                self.app.post_message(events.AppFocus())
        elif event.type in (pg.MOUSEBUTTONDOWN, pg.MOUSEBUTTONUP, pg.MOUSEMOTION):
            point = tuple(coordinate // self.resolution.scale for coordinate in event.pos)
            if (event.type == pg.MOUSEBUTTONDOWN and event.button == 1
                    and self._start_drag(event, point)):
                return
            if self._drag is not None:
                if event.type == pg.MOUSEMOTION:
                    pointer_origin, window_origin = self._drag
                    pointer = self.geometry.global_pointer()
                    if pointer_origin is not None and pointer is not None:
                        self._window.position = (window_origin[0] + pointer[0] - pointer_origin[0],
                                                 window_origin[1] + pointer[1] - pointer_origin[1])
                    else:
                        # Wayland/headless fallback uses movement deltas, never
                        # stale window-local coordinates after moving a window.
                        x, y = self._window.position
                        self._window.position = (x + event.rel[0], y + event.rel[1])
                elif event.type == pg.MOUSEBUTTONUP and event.button == 1:
                    self._reset_pointer()
                return
            mods = pg.key.get_mods()
            if event.type == pg.MOUSEBUTTONDOWN:
                kind = {4: events.MouseScrollUp, 5: events.MouseScrollDown}.get(event.button, events.MouseDown)
                button = event.button
            elif event.type == pg.MOUSEBUTTONUP:
                if event.button in (4, 5):
                    return
                kind, button = events.MouseUp, event.button
            else:
                kind = events.MouseMove
                button = next((index + 1 for index, down in enumerate(event.buttons) if down), 0)
            self.app.post_message(mouse_message(kind, point, button=button, shift=bool(mods & pg.KMOD_SHIFT), ctrl=bool(mods & pg.KMOD_CTRL), meta=bool(mods & pg.KMOD_ALT)))

    async def run(self, *, screenshot_path: str | Path | None = None, quit_after: float | None = None) -> None:
        """Run Textual and the nonblocking SDL presentation loop in one asyncio loop."""
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        # Keep Windows display scaling from resampling our integer framebuffer.
        # https://wiki.libsdl.org/SDL2/SDL_HINT_WINDOWS_DPI_AWARENESS
        os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")
        import pygame

        self._pygame = pygame
        pygame.display.init()
        pygame.display.set_caption("一箭又一箭 / ARROW AFTER ARROW")
        self._set_resolution(self.resolution_name, notify=False)
        pygame.key.set_repeat(400, 35)
        pygame.key.start_text_input()
        self.app.host_action = self.handle_action
        self.running = True
        self._exit_requested = False
        ready = asyncio.Event()

        async def on_ready(pilot):
            await pilot.pause()
            ready.set()

        task = asyncio.create_task(self.app.run_async(headless=True, size=self.resolution.terminal_size, auto_pilot=on_ready))
        start = monotonic()
        last_frame = None
        try:
            while not ready.is_set() and not task.done():
                await asyncio.sleep(0.01)
            while self.running and not task.done():
                frame_start = monotonic()
                self.process_events(pygame.event.get())
                await asyncio.sleep(0)
                # ExitApp may empty the screen stack during this yield. The
                # immediate _exit flag is part of the pinned Textual adapter.
                if (not self.running or task.done() or not self.app.screen_stack
                        or self.app._exit):
                    break
                focused = self.app.focused
                if focused is not None:
                    r = focused.content_region
                    scale = self.resolution.scale
                    pygame.key.set_text_input_rect((r.x * CELL_WIDTH * scale, r.y * CELL_HEIGHT * scale,
                                                    r.width * CELL_WIDTH * scale, r.height * CELL_HEIGHT * scale))
                frame = compose_frame(self.app, self.resolution.logical_size)
                last_frame = frame.resize((self.resolution.width, self.resolution.height), Image.Resampling.NEAREST)
                surface = pygame.image.frombytes(last_frame.tobytes(), last_frame.size, "RGB")
                self._display.blit(surface, (0, 0))
                pygame.display.flip()
                if quit_after is not None and monotonic() - start >= quit_after:
                    self._request_exit()
                await asyncio.sleep(max(0, 1 / 60 - (monotonic() - frame_start)))
            if screenshot_path is not None and last_frame is not None:
                path = Path(screenshot_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                last_frame.save(path)
        finally:
            if not task.done():
                self._request_exit()
            await task
            pygame.key.stop_text_input()
            pygame.display.quit()


async def run_desktop(
    app: App,
    resolution: str = "1280x720",
    *,
    screenshot_path: str | Path | None = None,
    quit_after: float | None = None,
) -> None:
    await PixelHost(app, resolution).run(screenshot_path=screenshot_path, quit_after=quit_after)
