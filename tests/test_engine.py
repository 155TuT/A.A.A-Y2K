"""Rule, certificate, progression and arbitrary-mask generation regressions."""

import json
import math
from random import Random

import pytest

from arrow_y2k.generation import GenerateConfig, generate, template_mask
from arrow_y2k.model import Arrow, Board, Direction, GameSession
from arrow_y2k.persistence import load_map, save_map
from arrow_y2k.solver import solve, validate_certificate


def rectangular(width=5, height=5):
    return template_mask("rectangle", width, height)


def bends(arrow):
    steps = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(arrow.cells, arrow.cells[1:])]
    return sum(a != b for a, b in zip(steps, steps[1:]))


@pytest.mark.parametrize("direction,head,blocker", [
    (Direction.UP, (2, 3), (2, 0)),
    (Direction.RIGHT, (1, 2), (4, 2)),
    (Direction.DOWN, (2, 1), (2, 4)),
    (Direction.LEFT, (3, 2), (0, 2)),
])
def test_four_directions_and_nearest_blocker(direction, head, blocker):
    arrow = Arrow("moving", (head,), direction)
    obstacle = Arrow("blocker", (blocker,), Direction.UP)
    board = Board(rectangular(), (arrow, obstacle))
    collision = board.first_collision("moving")
    assert collision.cell == blocker
    assert collision.arrow_id == "blocker"
    assert collision.distance == 3
    assert Board(board.mask, (arrow,)).first_collision("moving") is None


def test_collision_uses_nearest_occupied_cell_and_whole_other_path():
    a = Arrow("a", ((0, 2),), Direction.RIGHT)
    near = Arrow("near", ((2, 2), (2, 1), (3, 1)), Direction.RIGHT)
    far = Arrow("far", ((4, 2),), Direction.RIGHT)
    collision = Board(rectangular(), (a, far, near)).first_collision("a")
    assert (collision.arrow_id, collision.cell, collision.distance) == ("near", (2, 2), 2)


def test_rays_cross_mask_holes_and_disconnected_islands():
    a = Arrow("a", ((0, 0),), Direction.RIGHT)
    b = Arrow("b", ((4, 0),), Direction.RIGHT)
    board = Board(frozenset({(0, 0), (4, 0)}), (a, b))
    assert board.width == 5
    assert board.first_collision("a").distance == 4
    assert solve(board).order == ("b", "a")


def test_self_collision_is_an_actual_blocker():
    hook = Arrow("hook", ((3, 1), (3, 2), (2, 2), (1, 2), (1, 1), (2, 1)), Direction.RIGHT)
    board = Board(rectangular(), (hook,))
    collision = board.first_collision("hook")
    assert collision.arrow_id == "hook"
    assert collision.cell == (3, 1)
    assert not solve(board).solvable
    assert not validate_certificate(board, ("hook",))


def test_only_head_final_ray_matters_not_translated_body():
    snake = Arrow("snake", ((0, 1), (1, 1), (1, 2), (2, 2)), Direction.RIGHT)
    obstacle = Arrow("obstacle", ((2, 1),), Direction.UP)
    board = Board(rectangular(), (snake, obstacle))
    # Rigid translation would strike (2, 1), but the actual head ray is clear.
    assert board.first_collision("snake") is None
    assert board.arrow_at((0, 1)) == snake


@pytest.mark.parametrize("cells,direction", [
    ((), Direction.UP),
    (((0, 0), (0, 0)), Direction.UP),
    (((0, 0), (1, 1)), Direction.RIGHT),
    (((0, 0), (0, 2)), Direction.DOWN),
    (((0, 0), (0, 1)), Direction.UP),
])
def test_invalid_arrow_paths_fail_at_construction(cells, direction):
    with pytest.raises(ValueError):
        Arrow("invalid", cells, direction)


def test_board_rejects_overlaps_duplicate_ids_outside_mask_and_empty_mask():
    a = Arrow("a", ((0, 0),), Direction.RIGHT)
    overlap = Arrow("b", ((0, 0),), Direction.UP)
    same_id = Arrow("a", ((1, 0),), Direction.RIGHT)
    outside = Arrow("outside", ((5, 0),), Direction.RIGHT)
    for arrows in ((a, overlap), (a, same_id), (a, outside)):
        with pytest.raises(ValueError):
            Board(rectangular(), arrows)
    with pytest.raises(ValueError):
        Board(frozenset())


def known_board():
    a = Arrow("a", ((0, 0),), Direction.RIGHT)
    b = Arrow("b", ((2, 0),), Direction.RIGHT)
    return Board(rectangular(3, 2), (a, b))


def test_three_lives_loss_lock_and_restart_restores_exact_board():
    board = known_board()
    session = GameSession(board)
    for life in (2, 1, 0):
        result = session.click("a")
        assert (result.kind, result.lives, session.lives) == ("collision", life, life)
        assert session.current_board == board
    assert session.status == "lost"
    assert session.click("b").kind == "ignored"
    assert session.click("missing").kind == "ignored"
    assert session.lives == 0
    session.restart()
    assert (session.status, session.lives, session.moves) == ("playing", 3, 0)
    assert session.current_board == session.board == board


def test_successful_removal_returned_for_animation_and_clear_win():
    board = known_board()
    session = GameSession(board)
    outcome = session.click("b")
    assert outcome.kind == "escaped"
    assert outcome.arrow == board.arrows[1]
    assert "b" not in session.remaining
    assert len(session.board.arrows) == 2
    assert len(session.current_board.arrows) == 1
    assert session.click("b").kind == "ignored"
    session.click("a")
    assert (session.status, session.lives, session.moves) == ("won", 3, 2)
    assert session.click("a").kind == "ignored"
    assert session.click("unknown").arrow is None


def test_solver_detects_dependency_cycle_and_returns_only_legal_prefix():
    left = Arrow("left", ((1, 1),), Direction.RIGHT)
    right = Arrow("right", ((3, 1),), Direction.LEFT)
    free = Arrow("free", ((0, 0),), Direction.UP)
    solution = solve(Board(rectangular(), (left, right, free)))
    assert not solution.solvable
    assert solution.order == ("free",)
    assert set(solution.blocked) == {"left", "right"}


def test_certificate_rejects_wrong_order_duplicate_missing_and_unknown():
    board = known_board()
    assert validate_certificate(board, ("b", "a"))
    for order in (("a", "b"), ("b",), ("b", "b", "a"), ("unknown",), ()):
        assert not validate_certificate(board, order)
    assert validate_certificate(Board(board.mask), ())


@pytest.mark.parametrize("name", ["square", "rectangle", "heart", "diamond", "ring", "cross"])
@pytest.mark.parametrize("size", [(1, 1), (9, 8), (12, 10)])
def test_templates_fit_canvas_and_produce_nonempty_masks(name, size):
    width, height = size
    mask = template_mask(name, width, height)
    assert mask
    assert all(0 <= x < width and 0 <= y < height for x, y in mask)


@pytest.mark.parametrize("name", ["square", "rectangle", "heart", "diamond", "ring", "cross"])
def test_generations_have_certificates_exact_density_and_obey_hard_length_cap(name):
    mask = template_mask(name, 9, 8)
    for seed in range(20):
        density = (0.25, 0.6, 0.85, 1.0)[seed % 4]
        config = GenerateConfig(f"seed-{seed}", density, 8, 0.7, 2)
        level = generate(mask, config)
        assert len(level.board.occupancy) == max(1, math.floor(len(mask) * density + 0.5))
        assert all(1 <= len(arrow.cells) <= 8 for arrow in level.board.arrows)
        assert level.solution.solvable
        assert validate_certificate(level.board, level.solution.order)
        session = GameSession(level.board)
        for arrow_id in level.solution.order:
            assert session.click(arrow_id).kind == "escaped"
        assert session.status == "won" and session.lives == 3


def test_disconnected_random_masks_and_isolated_cells_always_terminate_with_solution():
    rng = Random(104)
    for seed in range(60):
        cells = [(x, y) for y in range(10) for x in range(12)]
        mask = frozenset(rng.sample(cells, 1 + seed % 80))
        level = generate(mask, GenerateConfig(str(seed), 1, 15, 1, 5))
        assert level.board.occupancy.keys() == mask
        assert validate_certificate(level.board, level.solution.order)


def test_same_seed_is_reproducible_and_zero_turn_bias_means_no_corners():
    mask = rectangular(9, 8)
    config = GenerateConfig("同一个 seed", 0.9, 9, 0)
    first = generate(mask, config)
    assert first == generate(mask, config)
    assert first.board != generate(mask, GenerateConfig("different", 0.9, 9, 0)).board
    assert all(bends(arrow) == 0 for arrow in first.board.arrows)




def test_json_round_trip_preserves_mask_seed_and_parameters(tmp_path):
    path = tmp_path / "nested" / "我的地图.json"
    mask = frozenset({(0, 0), (2, 0), (5, 3), (2, 4)})
    config = GenerateConfig("心形 / 2026", 0.75, 11, 0.4, 2)
    save_map(path, mask, config)
    assert load_map(path) == (mask, config)
    loaded_mask, loaded_config = load_map(path)
    assert generate(mask, config) == generate(loaded_mask, loaded_config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_map(path)


@pytest.mark.parametrize("coordinate", [1.9, float("inf"), True, "2", None])
def test_map_loader_rejects_non_integer_coordinates_without_coercion(tmp_path, coordinate):
    path = tmp_path / "bad.json"
    save_map(path, frozenset({(0, 0)}), GenerateConfig())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cells"] = [[coordinate, 0]]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_map(path)


@pytest.mark.parametrize("kwargs", [
    {"density": 0}, {"density": 1.1}, {"max_length": 0},
    {"min_length": 8, "max_length": 7}, {"turn_bias": -0.1}, {"turn_bias": 1.1},
])
def test_generator_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        GenerateConfig(**kwargs)
