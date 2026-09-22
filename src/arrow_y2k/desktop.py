"""SDL window, OS input and CRT presentation around the real Textual app.

Textual rendering and private framework access live in textual_bridge.
Game rules and page composition remain owned by the application.
"""
from __future__ import annotations

import asyncio
import os
import webbrowser
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from textual import events
from textual.errors import NoWidget

from . import PROJECT_URL as PROJECT_URL
from .display_config import RESOLUTIONS as RESOLUTIONS, Resolution as Resolution
from .display_config import DisplayPreferences
from .fonts import CELL_HEIGHT, CELL_WIDTH
from .windowing import DesktopGeometry, WindowShape, choose_work_area, place_window
from .crt import CASE, CrtShell, SHUTDOWN_DURATION
from .textual_bridge import (
    app_context, is_exiting,
    compose_frame as compose_frame,
    configure_native_colors as configure_native_colors,
    mouse_message as mouse_message,
    raster_point as raster_point,
    _rasterize_strips as _rasterize_strips,
)

if TYPE_CHECKING:
    from textual.app import App


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
        self._exit_finished = False
        self.shell = None
        self._pressed_control = None
        self._pointer_in_screen = False
        self._screen_mouse_buttons = set()
        self._shutdown_started = None
        self._last_content = None
        self.window_shape = None

    def _request_exit(self) -> None:
        """Save once, then let the display complete its nonblocking power-off."""
        if self._exit_requested:
            return
        self._exit_requested = True
        callback = getattr(self.app, "request_desktop_exit", None)
        if callback is not None:
            callback()
        if getattr(self.app, "finish_desktop_exit", None) is not None:
            self._shutdown_started = monotonic()
            self._reset_pointer()
        else:
            # A generic embedding App need not implement the two-phase exit.
            if callback is None:
                self.app.exit()
            self.running = False

    def _finish_exit(self) -> None:
        if self._exit_finished:
            return
        self._exit_finished = True
        callback = getattr(self.app, "finish_desktop_exit", self.app.exit)
        callback()
        self.running = False

    def screen_point(self, point):
        """Translate the screen inset and integer scale; glass never warps UI coordinates."""
        if self.shell is None:
            return tuple(coordinate // self.resolution.scale for coordinate in point)
        return self.shell.input_point(point)

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
        old_size = self.shell.outer_size if self.shell else (self.resolution.width, self.resolution.height)
        self._reset_pointer()
        self.resolution_name = name
        self.resolution = RESOLUTIONS[name]
        self.shell = CrtShell((self.resolution.width, self.resolution.height), self.resolution.scale)
        size = self.shell.outer_size
        self._display = self._pygame.display.set_mode(size, self._pygame.NOFRAME)
        self._window = self._pygame.Window.from_display_module()
        origin = previous if previous is not None else tuple(self._window.position)
        area = choose_work_area(self.geometry.work_areas(), (*origin, *old_size))
        self._window.position = place_window(size, area, previous)
        self.window_shape = WindowShape(self._pygame)
        self.window_shape.apply(self.shell.outer_mask)
        if notify:
            self.app.post_message(events.Resize.from_dimensions(self.resolution.terminal_size, self.resolution.logical_size))

    def _reset_pointer(self) -> None:
        self._drag = None
        self._pressed_control = None
        self._pointer_in_screen = False
        self._screen_mouse_buttons.clear()
        if self._geometry is not None:
            self.geometry.capture_pointer(False)
        callback = getattr(self.app, "reset_pointer_state", None)
        if callback is not None:
            callback()

    def _start_drag(self, event, point) -> bool:
        region = getattr(self.app, "window_drag_region", None)
        if point is None or region is None or self._window is None:
            return False
        x, y, width, height = region
        if not (x <= point[0] < x + width and y <= point[1] < y + height):
            return False
        # A header can contain real controls. Hit-test Textual's topmost
        # widget (and its parents) before treating the empty/title area as a
        # window handle, so nested labels and buttons keep their clicks.
        if self.app.screen_stack:
            try:
                widget, _ = self.app.screen.get_widget_at(
                    point[0] // CELL_WIDTH, point[1] // CELL_HEIGHT)
            except NoWidget:
                pass
            else:
                if any(getattr(node, "can_focus", False) for node in widget.ancestors_with_self):
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
        if ctrl or alt:
            modifiers = [name for name, enabled in (("ctrl", ctrl), ("alt", alt), ("shift", shift)) if enabled]
            key = "+".join((*modifiers, key))
            character = None
        elif shift and (character is None or key == "tab"):
            key = "shift+" + key
        elif character and key != "space":
            key = character
        return events.Key(key, character)

    def process_event(self, event) -> None:
        """Forward an SDL event; this method can be exercised without OS input."""
        pg = self._pygame
        if self._exit_requested:
            return
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
            point = self.screen_point(event.pos)
            control = self.shell.control_at(event.pos) if self.shell else None
            if self._pressed_control is not None:
                if event.type == pg.MOUSEBUTTONUP and event.button == 1:
                    pressed, self._pressed_control = self._pressed_control, None
                    self.geometry.capture_pointer(False)
                    if pressed == control:
                        if control == "power":
                            self._request_exit()
                        elif control in ("plus", "minus"):
                            callback = getattr(self.app, "adjust_master_volume", None)
                            if callback is not None:
                                with app_context(self.app):
                                    callback(5 if control == "plus" else -5)
                        elif control == "menu":
                            callback = getattr(self.app, "toggle_display_mode", None)
                            if callback is not None:
                                with app_context(self.app):
                                    callback()
                return
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                if control is not None:
                    self._reset_pointer()
                    self._pressed_control = control
                    self.geometry.capture_pointer(True)
                    return
                if point is None and self.shell is not None:
                    # Only visible plastic is a handle; transparent corners
                    # must never capture a pointer from the desktop behind it.
                    x, y = event.pos
                    w, h = self.shell.outer_size
                    if not (0 <= x < w and 0 <= y < h) or not self.shell.outer_mask.getpixel((x, y)):
                        return
                    self._reset_pointer()
                    self._drag = (self.geometry.global_pointer(), tuple(self._window.position))
                    self.geometry.capture_pointer(True)
                    return
                if self._start_drag(event, point):
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
            if point is None:
                if self._pointer_in_screen:
                    self._reset_pointer()
                return
            self._pointer_in_screen = True
            mods = pg.key.get_mods()
            if event.type == pg.MOUSEBUTTONDOWN:
                kind = {4: events.MouseScrollUp, 5: events.MouseScrollDown}.get(event.button, events.MouseDown)
                button = event.button
                if event.button not in (4, 5):
                    self._screen_mouse_buttons.add(event.button)
            elif event.type == pg.MOUSEBUTTONUP:
                # A cancelled shell/drag press has no matching TUI down.
                # Gate here too: queued Textual down events may run only after
                # an SDL batch has already reset its pointer state.
                if event.button not in self._screen_mouse_buttons:
                    return
                self._screen_mouse_buttons.remove(event.button)
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
        task = None
        try:
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
            last_active_frame = None
            while not ready.is_set() and not task.done():
                await asyncio.sleep(0.01)
            while self.running and not task.done():
                frame_start = monotonic()
                self.process_events(pygame.event.get())
                await asyncio.sleep(0)
                # ExitApp may empty the screen stack during this yield. The
                # immediate _exit flag is part of the pinned Textual adapter.
                if (not self.running or task.done() or not self.app.screen_stack
                        or is_exiting(self.app)):
                    break
                focused = self.app.focused
                if focused is not None:
                    r = focused.content_region
                    scale = self.resolution.scale
                    ox, oy = self.shell.viewport[:2]
                    pygame.key.set_text_input_rect((ox + r.x * CELL_WIDTH * scale, oy + r.y * CELL_HEIGHT * scale,
                                                    r.width * CELL_WIDTH * scale, r.height * CELL_HEIGHT * scale))
                shutdown_elapsed = None if self._shutdown_started is None else monotonic() - self._shutdown_started
                if shutdown_elapsed is not None and shutdown_elapsed >= SHUTDOWN_DURATION:
                    self._finish_exit()
                    break
                if shutdown_elapsed is None or self._last_content is None:
                    self._last_content = compose_frame(self.app, self.resolution.logical_size)
                preferences = getattr(self.app, "display_preferences", DisplayPreferences())
                last_frame = self.shell.render(self._last_content, monotonic() - start,
                                               pressed=self._pressed_control, shutdown_elapsed=shutdown_elapsed,
                                               reduced_motion=preferences.reduced_motion,
                                               monochrome=preferences.monochrome)
                if shutdown_elapsed is None:
                    last_active_frame = last_frame
                surface = pygame.image.frombytes(last_frame.tobytes(), last_frame.size, last_frame.mode)
                self._display.fill(CASE)
                self._display.blit(surface, (0, 0))
                pygame.display.flip()
                if quit_after is not None and monotonic() - start >= quit_after:
                    self._request_exit()
                await asyncio.sleep(max(0, 1 / 60 - (monotonic() - frame_start)))
            if screenshot_path is not None and last_active_frame is not None:
                path = Path(screenshot_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                last_active_frame.save(path)
        finally:
            try:
                if task is not None:
                    if not task.done():
                        self._request_exit()
                        self._finish_exit()
                    await task
            finally:
                self.running = False
                self.app.host_action = None
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
