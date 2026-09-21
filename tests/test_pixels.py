"""Pixel geometry, path motion, and life-loss regressions."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from arrow_y2k.pixels import (
    Animation,
    BACKGROUND,
    MINT,
    RED,
    HEART_RED,
    HEART_SHADOW,
    HEART_LIGHT,
    _stroke_pixels,
    WHITE,
    _animated_path,
    _arrow_path,
    board_metrics,
    hit_test,
    render_board,
    render_hearts,
    render_mask_editor,
)


@dataclass(frozen=True)
class ArrowStub:
    id: str
    cells: tuple[tuple[int, int], ...]
    direction: object


def arrow(cells=((0, 0),), delta=(1, 0), id="a"):
    return ArrowStub(id, cells, SimpleNamespace(delta=delta))


def board(arrows=(), mask=frozenset({(0, 0)})):
    return SimpleNamespace(arrows=arrows, mask=mask)


def palette(image):
    return {color for _, color in image.getcolors(image.width * image.height)}


def test_fifteen_pixel_cells_share_one_boundary_and_integer_hit_geometry():
    mask = frozenset({(3, 5), (4, 5), (3, 6)})
    image = render_board(board(mask=mask))
    assert image.size == (33, 33)
    metrics = board_metrics(103, 120, mask)
    assert metrics.scale == 2
    assert metrics.origin_x == 18
    assert metrics.origin_y == 27
    assert hit_test(*metrics.cell_center((3, 5)), 103, 120, mask) == (3, 5)
    assert hit_test(*metrics.cell_center((4, 6)), 103, 120, mask) is None
    assert hit_test(metrics.origin_x, metrics.origin_y + 12, 103, 120, mask) is None
    assert hit_test(0, 0, 103, 120, mask) is None


def test_display_upscaling_preserves_exact_blocks_without_interpolation():
    example = board((arrow(),))
    native = render_board(example)
    scaled = render_board(example, size=(34, 34))
    assert scaled.mode == "RGB"
    for y in range(native.height):
        for x in range(native.width):
            pixel = native.getpixel((x, y))
            assert palette(scaled.crop((x * 2, y * 2, x * 2 + 2, y * 2 + 2))) == {pixel}


def test_tiny_custom_map_keeps_pixel_scale_compatible_with_life_icons():
    assert board_metrics(444, 264, {(0, 0)}).scale == 2
    assert board_metrics(444, 264, {(2, 3), (3, 3)}).scale == 2


def test_hover_only_changes_selected_arrow_pixels():
    example = board((arrow(),))
    normal = render_board(example)
    hovered = render_board(example, hovered="a")
    assert MINT not in palette(normal)
    assert MINT in palette(hovered)
    assert WHITE not in palette(hovered)


def test_snake_motion_keeps_old_corners_until_tail_reaches_them():
    bent = arrow(((0, 0), (1, 0), (1, 1)), delta=(0, 1))
    original = _arrow_path(bent, 0, 0)
    moved, _, _ = _animated_path(bent, original, Animation(bent, "collision", .30, 1), (49, 49))
    assert moved[0] == (10, 8)  # six pixels along the old horizontal segment
    assert (24, 8) in moved    # original corner stays fixed, never translates
    assert moved[-1] == (24, 35)
    assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(moved, moved[1:]))
    returned, color, shake = _animated_path(bent, original, Animation(bent, "collision", 1, 1), (49, 49))
    assert returned[0] == original[0]
    assert returned[-1] == original[-1]
    assert color == RED
    assert shake == (0, 0)


def test_exiting_arrow_can_be_rendered_after_logical_removal():
    moving = arrow()
    empty = board()
    assert WHITE in palette(render_board(empty, animation=Animation(moving, "exit", 0)))
    assert WHITE not in palette(render_board(empty, animation=Animation(moving, "exit", 1)))


def test_lost_heart_keeps_outline_and_red_fragments_fall_then_disappear():
    before = render_hearts(3)
    falling = render_hearts(2, progress=.65, lost_index=2)
    finished = render_hearts(2, progress=1, lost_index=2)
    assert before.size == falling.size == finished.size == (47, 23)
    outline = [(x, y) for y in range(23) for x in range(33, 47) if before.getpixel((x, y)) == WHITE]
    assert all(falling.getpixel(point) == WHITE == finished.getpixel(point) for point in outline)
    assert {HEART_RED, HEART_SHADOW} & palette(falling.crop((31, 12, 47, 23)))
    assert not {HEART_RED, HEART_SHADOW, HEART_LIGHT} & palette(finished.crop((32, 0, 47, 23)))
    assert before.getpixel((35, 3)) == HEART_LIGHT
    assert finished.getpixel((35, 3)) == BACKGROUND


def test_editor_canvas_has_stable_dimensions_even_when_mask_empty():
    assert render_mask_editor(set(), 12, 10).size == (193, 161)
    assert render_mask_editor({(2, 2)}, 12, 10).getpixel((40, 40)) == MINT


@pytest.mark.parametrize("lives", [-1, 4])
def test_invalid_life_count_is_a_programming_error(lives):
    with pytest.raises(ValueError):
        render_hearts(lives)


def test_all_arrow_orientations_are_exact_quarter_rotations():
    def ink(direction):
        image = render_board(board((arrow(delta=direction),)))
        return {(x, y) for x in range(17) for y in range(17) if image.getpixel((x, y)) == WHITE}
    expected = ink((1, 0))
    assert {y for x, y in expected if x == 5} == {8, 9}
    for direction in ((0, 1), (-1, 0), (0, -1), (1, 0)):
        expected = {(16 - y, x) for x, y in expected}
        assert ink(direction) == expected


def test_thin_path_corner_has_single_pixel_bevel_not_diagonal_shortcut():
    ink = _stroke_pixels([(4, 8), (8, 8), (8, 12)])
    assert (8, 8) not in ink
    assert (7, 8) in ink and (8, 9) in ink
    assert {(8, 10), (7, 10)} <= ink
    assert {(5, 8), (5, 9)} <= ink


def test_heart_shading_is_discrete_and_keeps_outline_identical():
    alive = render_hearts(3)
    empty = render_hearts(0)
    assert {HEART_RED, HEART_SHADOW, HEART_LIGHT} <= palette(alive)
    assert palette(alive) <= {BACKGROUND, WHITE, HEART_RED, HEART_SHADOW, HEART_LIGHT}
    white = lambda image: {(x, y) for x in range(47) for y in range(23) if image.getpixel((x, y)) == WHITE}
    assert white(alive) == white(empty)
