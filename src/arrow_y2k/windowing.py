"""OS display geometry and pointer capture, independent of game/UI state."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkArea:
    x: int
    y: int
    width: int
    height: int


def choose_work_area(areas: list[WorkArea], window: tuple[int, int, int, int]) -> WorkArea:
    """Use overlap first, then nearest centre; negative monitor origins are valid."""
    x, y, width, height = window
    def score(area):
        overlap = max(0, min(x + width, area.x + area.width) - max(x, area.x)) * max(
            0, min(y + height, area.y + area.height) - max(y, area.y))
        distance = (x + width / 2 - area.x - area.width / 2) ** 2 + (
            y + height / 2 - area.y - area.height / 2) ** 2
        return overlap, -distance
    return max(areas, key=score)


def place_window(size: tuple[int, int], area: WorkArea,
                 previous: tuple[int, int] | None = None) -> tuple[int, int]:
    """Keep exact pixel dimensions, and always expose the top-left drag strip.

    A window larger than the work area anchors at its origin. Fractional scaling
    would blur the artwork; moving this window remains possible by its top strip.
    """
    width, height = size
    x, y = previous if previous is not None else (
        area.x + (area.width - width) // 2, area.y + (area.height - height) // 2)
    return (min(max(x, area.x), area.x + max(0, area.width - width)),
            min(max(y, area.y), area.y + max(0, area.height - height)))


class _SDLRect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("x", "y", "w", "h")]


class DesktopGeometry:
    """Read the SDL library already shipped with pygame, including usable bounds.

    SDL supplies taskbar/dock-aware monitor rectangles and true desktop pointer
    coordinates. No additional binary or display backend is installed.
    """
    def __init__(self, pygame):
        self.pygame = pygame
        package = Path(pygame.__file__).parent
        candidates = [package / "SDL2.dll", package / "libSDL2.dylib",
                      Path(pygame.base.__file__)]
        self.sdl = None
        for candidate in candidates:
            try:
                library = ctypes.CDLL(str(candidate))
                library.SDL_GetNumVideoDisplays.argtypes = []
                library.SDL_GetNumVideoDisplays.restype = ctypes.c_int
                library.SDL_GetDisplayUsableBounds.argtypes = [ctypes.c_int, ctypes.POINTER(_SDLRect)]
                library.SDL_GetDisplayUsableBounds.restype = ctypes.c_int
                library.SDL_GetDisplayBounds.argtypes = [ctypes.c_int, ctypes.POINTER(_SDLRect)]
                library.SDL_GetDisplayBounds.restype = ctypes.c_int
                library.SDL_GetGlobalMouseState.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
                library.SDL_GetGlobalMouseState.restype = ctypes.c_uint32
                library.SDL_CaptureMouse.argtypes = [ctypes.c_int]
                library.SDL_CaptureMouse.restype = ctypes.c_int
            except (OSError, AttributeError):
                continue
            self.sdl = library
            break

    def work_areas(self) -> list[WorkArea]:
        areas = []
        if self.sdl is not None:
            for index in range(self.sdl.SDL_GetNumVideoDisplays()):
                rect = _SDLRect()
                result = self.sdl.SDL_GetDisplayUsableBounds(index, ctypes.byref(rect))
                if result < 0:
                    result = self.sdl.SDL_GetDisplayBounds(index, ctypes.byref(rect))
                if result == 0 and rect.w > 0 and rect.h > 0:
                    areas.append(WorkArea(rect.x, rect.y, rect.w, rect.h))
        if not areas:
            # Headless SDL drivers have no usable desktop. This is only the
            # fallback for a backend without monitor geometry, not a guessed
            # arrangement of multiple monitors.
            width, height = self.pygame.display.get_desktop_sizes()[0]
            areas.append(WorkArea(0, 0, width, height))
        return areas

    def global_pointer(self) -> tuple[int, int] | None:
        if self.sdl is None or self.pygame.display.get_driver() in ("dummy", "wayland"):
            return None
        x, y = ctypes.c_int(), ctypes.c_int()
        self.sdl.SDL_GetGlobalMouseState(ctypes.byref(x), ctypes.byref(y))
        return x.value, y.value

    def capture_pointer(self, enabled: bool) -> None:
        if self.sdl is not None:
            self.sdl.SDL_CaptureMouse(int(enabled))
