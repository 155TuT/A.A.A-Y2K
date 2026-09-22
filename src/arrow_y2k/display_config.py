"""Shared display presets without importing the GUI or persistence layer."""

from dataclasses import dataclass

CELL_WIDTH = 6
CELL_HEIGHT = 12


@dataclass(frozen=True)
class DisplayPreferences:
    reduced_motion: bool = False
    monochrome: bool = False


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
