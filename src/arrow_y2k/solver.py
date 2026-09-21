"""Deterministic solver for removal-only arrow puzzles.

Removing an arrow can only remove blockers. Consequently any currently legal
move is safe: if no legal arrow remains, the board cannot be completed. There
is no search tree, heuristic guess, or external model involved.
"""

from dataclasses import dataclass
from collections.abc import Iterable

from .model import Board


@dataclass(frozen=True)
class Solution:
    order: tuple[str, ...]
    solvable: bool
    blocked: tuple[str, ...]


def solve(board: Board) -> Solution:
    remaining = {arrow.id: arrow for arrow in board.arrows}
    order: list[str] = []
    while remaining:
        snapshot = Board(board.mask, tuple(remaining.values()))
        legal = [arrow_id for arrow_id in remaining if snapshot.first_collision(arrow_id) is None]
        if not legal:
            return Solution(tuple(order), False, tuple(remaining))
        for arrow_id in legal:
            del remaining[arrow_id]
            order.append(arrow_id)
    return Solution(tuple(order), True, ())


def validate_certificate(board: Board, order: Iterable[str]) -> bool:
    """Independently replay a complete sequence, rejecting partial/illegal moves."""
    remaining = {arrow.id: arrow for arrow in board.arrows}
    for arrow_id in order:
        if arrow_id not in remaining:
            return False
        snapshot = Board(board.mask, tuple(remaining.values()))
        if snapshot.first_collision(arrow_id) is not None:
            return False
        del remaining[arrow_id]
    return not remaining
