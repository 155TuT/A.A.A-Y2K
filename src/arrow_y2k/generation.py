"""Seeded mask filling with a constructive and independently checked solution.

The generator first selects exactly the requested number of occupied cells.
It peels an exposed head and grows a tail through the remaining cells, then
repeats. The ray was empty before the tail grew, so it cannot hit that tail.
Every finite nonempty cell set has an exposed cell (e.g. its topmost cell),
so the process always finishes, even for disconnected masks and isolated cells.
The recorded peeling order is a complete zero-loss certificate.
"""

from dataclasses import dataclass
from random import Random
import math

from .model import Arrow, Board, Cell, Direction
from .solver import Solution, solve, validate_certificate


@dataclass(frozen=True)
class GenerateConfig:
    seed: str = "2026"
    density: float = 0.75
    max_length: int = 7
    turn_bias: float = 0.6
    min_length: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.density <= 1:
            raise ValueError("density must be in (0, 1]")
        if not 1 <= self.min_length <= self.max_length:
            raise ValueError("lengths must satisfy 1 <= min_length <= max_length")
        if not 0 <= self.turn_bias <= 1:
            raise ValueError("turn_bias must be in [0, 1]")


@dataclass(frozen=True)
class GeneratedLevel:
    board: Board
    solution: Solution
    seed: str
    name: str = "种子关卡"
    description: str = "观察箭头末端方向，按顺序清空棋盘。"


def template_mask(name: str, width: int = 9, height: int = 8) -> frozenset[Cell]:
    """Build a mask; named templates scale to the supplied canvas dimensions."""
    if width < 1 or height < 1:
        raise ValueError("Template dimensions must be positive")
    if name == "square":
        width = height = min(width, height)
    if name in ("square", "rectangle"):
        return frozenset((x, y) for y in range(height) for x in range(width))
    if name == "heart":
        # A raster template gives crisp, symmetric lobes and a single-cell tip.
        rows = (".###.###.", "#########", "#########", "#########",
                ".#######.", "..#####..", "...###...", "....#....")
        return frozenset((x, y) for y in range(height) for x in range(width)
                         if rows[min(7, int((y + 0.5) * 8 / height))]
                                [min(8, int((x + 0.5) * 9 / width))] == "#")
    cx, cy = (width - 1) / 2, (height - 1) / 2
    if name == "diamond":
        return frozenset((x, y) for y in range(height) for x in range(width)
                         if abs(x - cx) / max(1, width / 2) + abs(y - cy) / max(1, height / 2) <= 1)
    if name == "ring":
        thickness = max(1, min(width, height) // 4)
        return frozenset((x, y) for y in range(height) for x in range(width)
                         if min(x, y, width - 1 - x, height - 1 - y) < thickness)
    if name == "cross":
        return frozenset((x, y) for y in range(height) for x in range(width)
                         if abs(x - cx) <= max(0.5, width / 6) or abs(y - cy) <= max(0.5, height / 6))
    raise ValueError(f"Unknown template: {name}")


def _ray(cell: Cell, direction: Direction, width: int, height: int) -> list[Cell]:
    x, y = cell
    dx, dy = direction.delta
    result: list[Cell] = []
    x, y = x + dx, y + dy
    while 0 <= x < width and 0 <= y < height:
        result.append((x, y))
        x, y = x + dx, y + dy
    return result


def generate(mask: frozenset[Cell], config: GenerateConfig) -> GeneratedLevel:
    """Generate exact-density occupancy; min_length is a preferred tail length.

    A short branch or isolated cell may force a shorter arrow. ``max_length``
    is always a hard cap; ``turn_bias=0`` guarantees straight paths. Higher
    turn bias favors corners when both straight and bent continuations exist.
    """
    empty_board = Board(mask)
    width, height = empty_board.width, empty_board.height
    rng = Random(str(config.seed))
    count = max(1, math.floor(len(mask) * config.density + 0.5))
    selected = set(rng.sample(sorted(mask), count))
    remaining = selected.copy()
    arrows: list[Arrow] = []
    while remaining:
        candidates: list[tuple[Cell, Direction]] = []
        weights: list[float] = []
        for head in sorted(remaining):
            for direction in Direction:
                ray = _ray(head, direction, width, height)
                if remaining.intersection(ray):
                    continue
                dx, dy = direction.delta
                predecessor = (head[0] - dx, head[1] - dy)
                # Favor useful length and dependencies on earlier removals.
                dependency = len(selected.intersection(ray))
                candidates.append((head, direction))
                weights.append(1 + min(dependency, 5) * 2 + (3 if predecessor in remaining else 0))
        head, direction = rng.choices(candidates, weights=weights, k=1)[0]
        target_length = rng.randint(config.min_length, config.max_length)
        reverse_path = [head]
        dx, dy = direction.delta
        step = (-dx, -dy)
        while len(reverse_path) < target_length:
            tail = reverse_path[-1]
            options: list[tuple[Cell, Cell]] = []
            for extension in Direction:
                ex, ey = extension.delta
                neighbor = (tail[0] + ex, tail[1] + ey)
                if neighbor not in remaining or neighbor in reverse_path:
                    continue
                # The first tail segment defines the direction of the head.
                if len(reverse_path) == 1 and extension.delta != step:
                    continue
                if config.turn_bias == 0 and extension.delta != step:
                    continue
                options.append((neighbor, extension.delta))
            if not options:
                break
            straight = [option for option in options if option[1] == step]
            corners = [option for option in options if option[1] != step]
            pool = corners if corners and (not straight or rng.random() < config.turn_bias) else straight
            if not pool:
                pool = options
            neighbor, step = rng.choice(pool)
            reverse_path.append(neighbor)
        arrow = Arrow(f"a{len(arrows) + 1:03}", tuple(reversed(reverse_path)), direction)
        arrows.append(arrow)
        remaining.difference_update(arrow.cells)
    board = Board(mask, tuple(arrows))
    certificate = tuple(arrow.id for arrow in arrows)
    if not validate_certificate(board, certificate):
        raise AssertionError("Constructive generator produced an invalid certificate")
    solution = solve(board)
    if not solution.solvable:
        raise AssertionError("Independent solver rejected generated board")
    return GeneratedLevel(board, solution, str(config.seed))


def _curated(mask: frozenset[Cell], fixed: tuple[Arrow, ...], config: GenerateConfig,
             name: str, description: str) -> GeneratedLevel:
    reserved = {cell for arrow in fixed for cell in arrow.cells}
    remaining_mask = mask.difference(reserved)
    filler = generate(remaining_mask, config) if remaining_mask else None
    arrows = fixed + (tuple(Arrow(f"fill-{arrow.id}", arrow.cells, arrow.direction)
                            for arrow in filler.board.arrows) if filler else ())
    board = Board(mask, arrows)
    solution = solve(board)
    if not solution.solvable:
        raise AssertionError("Curated level must be solvable")
    return GeneratedLevel(board, solution, str(config.seed), name, description)


def make_level(index: int, seed: str = "2026") -> GeneratedLevel:
    """One-based campaign progression; later entries use seeded template masks."""
    if index < 1:
        raise ValueError("Level numbers begin at one")
    if index == 1:
        mask = template_mask("square", 6, 6)
        fixed = (
            Arrow("guide-exit", ((5, 0),), Direction.RIGHT),
            Arrow("guide-line", ((2, 0), (3, 0), (4, 0)), Direction.RIGHT),
            Arrow("guide-up", ((0, 2), (0, 1), (0, 0)), Direction.UP),
        )
        return _curated(mask, fixed, GenerateConfig(seed, 0.68, 1, 0),
                        "01 / 初见方向", "先观察箭头指向；只有前方没有遮挡，才能飞出。")
    if index == 2:
        mask = template_mask("rectangle", 9, 6)
        snake = Arrow("first-snake", ((3, 2), (3, 1), (2, 1), (1, 1), (1, 0), (0, 0)), Direction.LEFT)
        return _curated(mask, (snake,), GenerateConfig(seed, 0.82, 7, 0.68, 2),
                        "02 / 曲折之间", "折线只有头部决定方向；点击尾部也能选中整支箭头。")
    if index == 3:
        mask = template_mask("heart", 9, 8)
        top = tuple(Arrow(f"top-{x}", ((x, 0),), Direction.UP) for x in (1, 2, 3))
        outer = Arrow("heart-outer", (
            (0, 1), (0, 2), (0, 3), (1, 3), (1, 4), (2, 4), (2, 5),
            (3, 5), (4, 5), (5, 5), (6, 5), (6, 4), (7, 4), (7, 3),
            (8, 3), (8, 2), (8, 1), (7, 1), (7, 0), (6, 0), (5, 0)), Direction.LEFT)
        inner = Arrow("heart-inner", (
            (3, 1), (2, 1), (2, 2), (2, 3), (3, 3), (4, 3),
            (5, 3), (6, 3), (6, 2), (6, 1)), Direction.UP)
        return _curated(mask, top + (outer, inner), GenerateConfig(seed, 1, 4, 0.8),
                        "03 / 心有回环", "从外向内寻找出口；环绕的路径也会挡住其他箭头。")
    template = ("diamond", "ring", "cross", "heart")[(index - 4) % 4]
    level = generate(template_mask(template, 9, 8), GenerateConfig(seed, 0.90, 10, 0.8, 2))
    return GeneratedLevel(level.board, level.solution, level.seed,
                          f"{index:02} / 自由变奏", "尝试不同模板和种子，寻找新的解题顺序。")
