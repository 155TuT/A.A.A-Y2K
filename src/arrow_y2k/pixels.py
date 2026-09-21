"""Shared, integer-only pixel art for the Textual view and its window host.

A map cell has a 15 × 15 pixel interior.  Adjacent interiors share a one-pixel
dashed boundary, so cell centres are sixteen pixels apart.  Raster pixels are
never smoothed; the optional display canvas uses nearest-neighbour integer
scaling.  Game rules deliberately do not live in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, floor, pi, sin
from typing import TYPE_CHECKING, Iterable

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from .model import Arrow, Board

Cell = tuple[int, int]
RGB = tuple[int, int, int]
CELL_PIXELS = 15
STRIDE = CELL_PIXELS + 1
MAX_ART_SCALE = 2
BACKGROUND: RGB = (16, 23, 27)
TILE: RGB = (20, 29, 34)
GRID: RGB = (167, 184, 182)
WHITE: RGB = (239, 246, 232)
MINT: RGB = (114, 214, 156)
RED: RGB = (217, 107, 158)
HEART_RED: RGB = (204, 67, 95)
HEART_SHADOW: RGB = (117, 45, 66)
HEART_LIGHT: RGB = (246, 157, 171)
MUTED: RGB = (46, 62, 67)


@dataclass(frozen=True, slots=True)
class Animation:
    """An arrow's visual state; ``collision_distance`` is in grid cells.

    ``kind`` is ``"exit"`` or ``"collision"`` and ``progress`` runs from zero
    to one.  Animation never changes board occupancy or the original arrow.
    """

    arrow: Arrow
    kind: str
    progress: float
    collision_distance: int | None = None


@dataclass(frozen=True, slots=True)
class BoardGeometry:
    """Placement shared by rendering and mouse hit testing."""

    origin_x: int
    origin_y: int
    scale: int
    min_x: int
    min_y: int
    columns: int
    rows: int
    image_width: int
    image_height: int

    def cell_center(self, cell: Cell) -> Cell:
        """Return a cell centre in display-canvas pixel coordinates."""
        x, y = cell
        return (
            self.origin_x + ((x - self.min_x) * STRIDE + 8) * self.scale,
            self.origin_y + ((y - self.min_y) * STRIDE + 8) * self.scale,
        )


def _bounds(mask: Iterable[Cell]) -> tuple[int, int, int, int]:
    cells = tuple(mask)
    if not cells:
        return 0, 0, 0, 0
    xs, ys = zip(*cells)
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def board_metrics(width: int, height: int, mask: Iterable[Cell]) -> BoardGeometry:
    """Fit a board with integer scaling and centred, whole-pixel placement.

    Canvases smaller than a native board clip it at scale one.  They never
    shrink its pixels or silently introduce fractional scaling.
    """
    if width < 1 or height < 1:
        raise ValueError("Display dimensions must be positive")
    min_x, min_y, columns, rows = _bounds(mask)
    native_w, native_h = columns * STRIDE + 1, rows * STRIDE + 1
    # Tiny custom maps must not become giant pixels compared with life icons.
    scale = max(1, min(MAX_ART_SCALE, width // native_w, height // native_h))
    return BoardGeometry(
        (width - native_w * scale) // 2,
        (height - native_h * scale) // 2,
        scale,
        min_x,
        min_y,
        columns,
        rows,
        native_w,
        native_h,
    )


def hit_test(
    pixel_x: int,
    pixel_y: int,
    width: int,
    height: int,
    mask: Iterable[Cell],
) -> Cell | None:
    """Map display pixels to active cells; boundaries and holes return None."""
    active = frozenset(mask)
    geometry = board_metrics(width, height, active)
    x = (pixel_x - geometry.origin_x) // geometry.scale
    y = (pixel_y - geometry.origin_y) // geometry.scale
    if not (0 <= x < geometry.image_width and 0 <= y < geometry.image_height):
        return None
    if x % STRIDE == 0 or y % STRIDE == 0:
        return None
    cell = x // STRIDE + geometry.min_x, y // STRIDE + geometry.min_y
    return cell if cell in active else None


def _draw_grid(
    draw: ImageDraw.ImageDraw,
    mask: Iterable[Cell],
    min_x: int,
    min_y: int,
) -> None:
    for cell_x, cell_y in sorted(mask):
        x, y = (cell_x - min_x) * STRIDE, (cell_y - min_y) * STRIDE
        draw.rectangle((x + 1, y + 1, x + 15, y + 15), fill=TILE)
    # Draw fills first: a neighbouring cell must not erase shared boundaries.
    for cell_x, cell_y in sorted(mask):
        x, y = (cell_x - min_x) * STRIDE, (cell_y - min_y) * STRIDE
        for step in range(STRIDE + 1):
            if step % 4 < 2:
                for point in ((x + step, y), (x + step, y + STRIDE),
                              (x, y + step), (x + STRIDE, y + step)):
                    draw.point(point, fill=GRID)


def _length(points: list[Cell]) -> int:
    return sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(points, points[1:]))


def _point_at(points: list[Cell], distance: int) -> Cell:
    """Sample an axis-aligned polyline by Manhattan arc length."""
    distance = max(0, distance)
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = abs(dx) + abs(dy)
        if distance <= length:
            return (
                start[0] + (0 if dx == 0 else (1 if dx > 0 else -1) * distance),
                start[1] + (0 if dy == 0 else (1 if dy > 0 else -1) * distance),
            )
        distance -= length
    return points[-1]


def _slice_path(points: list[Cell], start: int, end: int) -> list[Cell]:
    """Keep the corners between two arc positions, rather than cutting chords."""
    result = [_point_at(points, start)]
    walked = 0
    for a, b in zip(points, points[1:]):
        walked += abs(b[0] - a[0]) + abs(b[1] - a[1])
        if start < walked < end:
            result.append(b)
    result.append(_point_at(points, end))
    return result


def _arrow_path(arrow: Arrow, min_x: int, min_y: int) -> list[Cell]:
    points = [((x - min_x) * STRIDE + 8, (y - min_y) * STRIDE + 8)
              for x, y in arrow.cells]
    dx, dy = arrow.direction.delta
    if len(points) > 1:
        sx = (points[1][0] - points[0][0]) // STRIDE
        sy = (points[1][1] - points[0][1]) // STRIDE
    else:
        sx, sy = dx, dy
    tail = points[0][0] - sx * 4, points[0][1] - sy * 4
    tip = points[-1][0] + dx * 5, points[-1][1] + dy * 5
    return [tail, *points, tip]


def _animated_path(
    arrow: Arrow,
    points: list[Cell],
    animation: Animation,
    image_size: tuple[int, int],
) -> tuple[list[Cell], RGB | None, Cell]:
    p = max(0.0, min(1.0, animation.progress))
    dx, dy = arrow.direction.delta
    length = _length(points)
    shake = (0, 0)
    color = None
    if animation.kind == "exit":
        # It is sufficient to move the tail beyond the entire viewport.
        distance = image_size[0] + image_size[1] + length + STRIDE
        travel = round(distance * p * p)
    elif animation.kind == "collision":
        reach = max(1, (animation.collision_distance or 1) * STRIDE - 10)
        if p < 0.30:
            travel = round(reach * sin((p / 0.30) * pi / 2))
        elif p < 0.58:
            travel = reach
            frame = floor((p - 0.30) * 60)
            amount = (1, -1, 2, -2, 0)[frame % 5]
            shake = -dy * amount, dx * amount
        else:
            travel = round(reach * (1 + cos((p - 0.58) / 0.42 * pi)) / 2)
        if p >= 0.30:
            color = RED
    else:
        raise ValueError(f"Unknown animation kind: {animation.kind}")
    end = points[-1]
    extended = [*points, (end[0] + dx * (travel + STRIDE), end[1] + dy * (travel + STRIDE))]
    return _slice_path(extended, travel, travel + length), color, shake


def _stroke_pixels(points: list[Cell]) -> set[Cell]:
    """Two-pixel directed orthogonal stroke with one-pixel bevelled corners.

    The second pixel sits on the segment's right-hand normal. Rotating the
    path therefore rotates its exact binary raster, including even-width
    strokes. Pillow's direction-dependent thick diagonal lines are avoided.
    """
    ink: set[Cell] = set()
    for a, b in zip(points, points[1:]):
        length = abs(b[0] - a[0]) + abs(b[1] - a[1])
        if not length:
            continue
        dx, dy = (b[0] - a[0]) // length, (b[1] - a[1]) // length
        for step in range(length + 1):
            x, y = a[0] + dx * step, a[1] + dy * step
            ink.add((x, y))
            ink.add((x - dy, y + dx))
    for a, corner, b in zip(points, points[1:], points[2:]):
        cross = ((corner[0] - a[0]) * (b[1] - corner[1])
                 - (corner[1] - a[1]) * (b[0] - corner[0]))
        if cross > 0:
            # The outside pixel is clipped, not interpolated or rounded by a
            # vector renderer. The underlying motion path remains orthogonal.
            ink.discard(corner)
    return ink


def _head_pixels(tip: Cell, direction: Cell) -> set[Cell]:
    """Rotate one canonical, symmetric chevron into any cardinal direction."""
    dx, dy = direction
    ink = set()
    for back in range(5):
        for across in (-back, 1 - back, back, back + 1):
            ink.add((tip[0] - dx * back - dy * across,
                     tip[1] - dy * back + dx * across))
    return ink


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    points: list[Cell],
    direction: Cell,
    color: RGB,
    offset: Cell = (0, 0),
) -> None:
    shifted = [(x + offset[0], y + offset[1]) for x, y in points]
    ink = _stroke_pixels(shifted) | _head_pixels(shifted[-1], direction)
    # A one-pixel moat clears grid dashes without making the thin body fuzzy.
    gutter = {(x + dx, y + dy) for x, y in ink
              for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))}
    draw.point(list(gutter), fill=BACKGROUND)
    draw.point(list(ink), fill=color)


def render_board(
    board: Board,
    size: tuple[int, int] | None = None,
    hovered: str | None = None,
    hint: str | None = None,
    animation: Animation | None = None,
    cursor: Cell | None = None,
    red_ids: Iterable[str] = (),
) -> Image.Image:
    """Render a board as RGB pixels, optionally fitted to a display canvas."""
    min_x, min_y, columns, rows = _bounds(board.mask)
    image = Image.new("RGB", (columns * STRIDE + 1, rows * STRIDE + 1), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_grid(draw, board.mask, min_x, min_y)
    if cursor is not None and cursor in board.mask:
        cx, cy = (cursor[0] - min_x) * STRIDE, (cursor[1] - min_y) * STRIDE
        draw.rectangle((cx + 2, cy + 2, cx + 14, cy + 14), outline=MINT, width=1)
    animated_id = animation.arrow.id if animation else None
    arrows = list(board.arrows)
    # An exiting arrow may already have been removed from logical occupancy.
    if animation is not None and not any(a.id == animated_id for a in arrows):
        arrows.append(animation.arrow)
    arrows.sort(key=lambda arrow: arrow.id == animated_id)
    for arrow in arrows:
        color = MINT if arrow.id in (hovered, hint) else RED if arrow.id in red_ids else WHITE
        points = _arrow_path(arrow, min_x, min_y)
        offset = (0, 0)
        if animation is not None and arrow.id == animated_id:
            points, override, offset = _animated_path(arrow, points, animation, image.size)
            color = override or color
        _draw_arrow(draw, points, arrow.direction.delta, color, offset)
    if size is None:
        return image
    geometry = board_metrics(*size, board.mask)
    canvas = Image.new("RGB", size, BACKGROUND)
    if geometry.scale != 1:
        image = image.resize((image.width * geometry.scale, image.height * geometry.scale), Image.Resampling.NEAREST)
    canvas.paste(image, (geometry.origin_x, geometry.origin_y))
    return canvas


_HEART = (
    "..###...###..",
    ".#####.#####.",
    "#############",
    "#############",
    "#############",
    ".###########.",
    "..#########..",
    "...#######...",
    "....#####....",
    ".....###.....",
    "......#......",
)
_HEART_PIXELS = frozenset((x, y) for y, row in enumerate(_HEART) for x, char in enumerate(row) if char == "#")
_HEART_FILL = frozenset((x, y) for x, y in _HEART_PIXELS if all((x + dx, y + dy) in _HEART_PIXELS
                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))))
_HEART_OUTLINE = _HEART_PIXELS - _HEART_FILL
HEART_IMAGE_SIZE = (47, 23)


def _heart_color(x: int, y: int) -> RGB:
    """Small fixed highlights and lower/right shadow, with no smooth shading."""
    if (x, y) in {(2, 2), (3, 2), (2, 3), (9, 2)}:
        return HEART_LIGHT
    if y >= 7 or (x >= 9 and y >= 4):
        return HEART_SHADOW
    return HEART_RED


def render_hearts(
    lives: int,
    progress: float | None = None,
    lost_index: int | None = None,
) -> Image.Image:
    """Draw three shaded, white-outline hearts and falling, split interiors.

    ``lives`` is the post-hit count. ``lost_index`` is zero based, normally
    equal to lives. The original outline is painted last and remains intact
    while the two red fragments split by up to two pixels and fall eight.
    """
    if not 0 <= lives <= 3:
        raise ValueError("Lives must be between zero and three")
    if lost_index is not None and not 0 <= lost_index < 3:
        raise ValueError("Heart index must be zero, one, or two")
    image = Image.new("RGB", HEART_IMAGE_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    p = None if progress is None else max(0.0, min(1.0, progress))
    for index in range(3):
        ox, oy = 1 + 16 * index, 1
        if index < lives:
            for x, y in _HEART_FILL:
                draw.point((ox + x, oy + y), fill=_heart_color(x, y))
        elif index == lost_index and p is not None and p < 0.92:
            separation = round(2 * p)
            drop = round(8 * p * p)
            for x, y in _HEART_FILL:
                crack_x = 6 + (1 if y % 4 < 2 else 0)
                if x == crack_x:
                    continue
                side = -1 if x < crack_x else 1
                # The final fragment pixels disappear in a deterministic
                # checker pattern instead of introducing alpha / blur.
                if p > 0.70 and (x + y) % 3 < floor((p - 0.70) * 14):
                    continue
                draw.point((ox + x + side * separation, oy + y + drop), fill=_heart_color(x, y))
        for x, y in _HEART_OUTLINE:
            draw.point((ox + x, oy + y), fill=WHITE)
    return image


def render_mask_editor(
    mask: Iterable[Cell],
    width: int = 12,
    height: int = 10,
    hover: Cell | None = None,
) -> Image.Image:
    """Render an editable mask on a fixed-size canvas in the same pixel unit."""
    if width < 1 or height < 1:
        raise ValueError("Editor dimensions must be positive")
    image = Image.new("RGB", (width * STRIDE + 1, height * STRIDE + 1), BACKGROUND)
    draw = ImageDraw.Draw(image)
    active = frozenset(mask)
    for y in range(height):
        for x in range(width):
            ox, oy = x * STRIDE, y * STRIDE
            selected = (x, y) in active
            if selected:
                draw.rectangle((ox + 1, oy + 1, ox + 15, oy + 15), fill=(37, 66, 54))
            for step in range(0, STRIDE + 1, 4):
                color = GRID if selected else MUTED
                for point in ((ox + step, oy), (ox + step, oy + STRIDE),
                              (ox, oy + step), (ox + STRIDE, oy + step)):
                    draw.point(point, fill=color)
            if selected:
                draw.rectangle((ox + 7, oy + 7, ox + 9, oy + 9), fill=MINT)
            if (x, y) == hover:
                draw.rectangle((ox + 2, oy + 2, ox + 14, oy + 14), outline=WHITE)
    return image
