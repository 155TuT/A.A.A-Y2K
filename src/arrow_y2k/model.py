"""Game rules, independent of Textual, rendering, animation, and storage.

Coordinates are ``(x, y)``. A path is ordered from tail to head. Rays continue
through holes in the mask until they leave its rectangular bounding box.
"""

from dataclasses import dataclass, field
from enum import Enum

Cell = tuple[int, int]


class Direction(Enum):
    UP = (0, -1)
    RIGHT = (1, 0)
    DOWN = (0, 1)
    LEFT = (-1, 0)

    @property
    def delta(self) -> Cell:
        return self.value


@dataclass(frozen=True)
class Arrow:
    id: str
    cells: tuple[Cell, ...]
    direction: Direction

    def __post_init__(self) -> None:
        if not self.id or not self.cells:
            raise ValueError("An arrow needs an ID and at least one cell")
        if len(set(self.cells)) != len(self.cells):
            raise ValueError("An arrow cannot visit a cell twice")
        for a, b in zip(self.cells, self.cells[1:]):
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                raise ValueError("Arrow paths must be orthogonally contiguous")
        if len(self.cells) > 1:
            previous, head = self.cells[-2:]
            if (head[0] - previous[0], head[1] - previous[1]) != self.direction.delta:
                raise ValueError("Direction must agree with the last path segment")

    @property
    def head(self) -> Cell:
        return self.cells[-1]


@dataclass(frozen=True)
class Collision:
    cell: Cell
    arrow_id: str
    distance: int


@dataclass(frozen=True)
class Board:
    mask: frozenset[Cell]
    arrows: tuple[Arrow, ...] = ()

    def __post_init__(self) -> None:
        if not self.mask:
            raise ValueError("The board mask cannot be empty")
        if any(x < 0 or y < 0 for x, y in self.mask):
            raise ValueError("Board coordinates must be nonnegative")
        ids = [arrow.id for arrow in self.arrows]
        if len(set(ids)) != len(ids):
            raise ValueError("Arrow IDs must be unique")
        occupied: set[Cell] = set()
        for arrow in self.arrows:
            if not set(arrow.cells) <= self.mask:
                raise ValueError("Every arrow cell must belong to the board mask")
            if occupied.intersection(arrow.cells):
                raise ValueError("Each cell can belong to only one arrow")
            occupied.update(arrow.cells)

    @property
    def width(self) -> int:
        return max(x for x, _ in self.mask) + 1

    @property
    def height(self) -> int:
        return max(y for _, y in self.mask) + 1

    @property
    def occupancy(self) -> dict[Cell, str]:
        return {cell: arrow.id for arrow in self.arrows for cell in arrow.cells}

    def arrow_at(self, cell: Cell) -> Arrow | None:
        arrow_id = self.occupancy.get(cell)
        return next((arrow for arrow in self.arrows if arrow.id == arrow_id), None)

    def first_collision(self, arrow_id: str) -> Collision | None:
        arrow = next(arrow for arrow in self.arrows if arrow.id == arrow_id)
        dx, dy = arrow.direction.delta
        x, y = arrow.head
        occupied = self.occupancy
        width, height = self.width, self.height
        distance = 0
        while True:
            x, y = x + dx, y + dy
            distance += 1
            if not (0 <= x < width and 0 <= y < height):
                return None
            if (x, y) in occupied:
                return Collision((x, y), occupied[x, y], distance)


@dataclass(frozen=True)
class MoveResult:
    kind: str
    arrow: Arrow | None
    collision: Collision | None
    lives: int


@dataclass
class GameSession:
    """One mutable game; ``board`` stays original, ``current_board`` is a snapshot.

    Clicks commit the rule outcome immediately. The presentation layer can animate
    ``MoveResult.arrow`` after it has been removed, and should lock input until
    that animation finishes. A failed click leaves the arrow in place.
    """

    board: Board
    remaining: dict[str, Arrow] = field(init=False)
    lives: int = field(init=False, default=3)
    status: str = field(init=False, default="playing")
    moves: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.restart()

    @property
    def current_board(self) -> Board:
        return Board(self.board.mask, tuple(self.remaining.values()))

    def restart(self) -> None:
        self.remaining = {arrow.id: arrow for arrow in self.board.arrows}
        self.lives = 3
        self.moves = 0
        self.status = "playing" if self.remaining else "won"

    def click(self, arrow_id: str) -> MoveResult:
        arrow = self.remaining.get(arrow_id)
        if self.status != "playing" or arrow is None:
            return MoveResult("ignored", arrow, None, self.lives)
        self.moves += 1
        collision = self.current_board.first_collision(arrow_id)
        if collision is not None:
            self.lives -= 1
            if self.lives == 0:
                self.status = "lost"
            return MoveResult("collision", arrow, collision, self.lives)
        del self.remaining[arrow_id]
        if not self.remaining:
            self.status = "won"
        return MoveResult("escaped", arrow, None, self.lives)
