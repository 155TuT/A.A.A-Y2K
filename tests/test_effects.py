"""Concurrent feedback timelines use the same ordered rule results as play."""
from PIL import ImageChops
from arrow_y2k.effects import GameplayEffects, IMPACT_DELAY
from arrow_y2k.model import Arrow, Board, Direction, GameSession
from arrow_y2k.pixels import render_board, render_hearts


def test_exits_keep_independent_age_and_pixels_after_leaving_occupancy():
    arrows = (Arrow("a", ((0, 0),), Direction.UP), Arrow("b", ((1, 0),), Direction.UP))
    game = GameSession(Board(frozenset({(0, 0), (1, 0)}), arrows))
    effects = GameplayEffects()
    effects.start(game.click("a"))
    effects.advance(.1)
    effects.start(game.click("b"))
    assert not game.remaining and len(effects.animations) == 2
    a, b = effects.animations
    assert a.progress > b.progress == 0
    both = render_board(game.current_board, animations=effects.animations)
    only_a = render_board(game.current_board, animations=(a,))
    only_b = render_board(game.current_board, animations=(b,))
    assert ImageChops.difference(both, only_a).getbbox()
    assert ImageChops.difference(both, only_b).getbbox()
    effects.advance(.56)
    assert not effects.busy("a") and effects.busy("b")
    effects.advance(.1)
    assert not effects.active


def test_parallel_collision_and_fragment_timelines_preserve_each_lost_heart():
    arrows = tuple(Arrow(str(i), ((i, 0),), Direction.RIGHT) for i in range(3))
    game = GameSession(Board(frozenset((i, 0) for i in range(3)), arrows))
    effects = GameplayEffects()
    effects.start(game.click("0"))
    effects.advance(.1)
    effects.start(game.click("1"))
    assert game.lives == 1 and effects.busy("0") and effects.busy("1")
    assert set(effects.heart_frames) == {1, 2}
    assert effects.heart_frames[2] > effects.heart_frames[1]
    before = render_hearts(game.lives, damage=effects.heart_frames)
    assert ImageChops.difference(before, render_hearts(3)).getbbox() is None
    effects.advance(IMPACT_DELAY + .2)
    falling = render_hearts(game.lives, damage=effects.heart_frames)
    assert ImageChops.difference(falling, render_hearts(1)).getbbox()
    ended = effects.advance(2)
    assert ended == {"0", "1"} and not effects.active
    assert ImageChops.difference(render_hearts(1, damage=effects.heart_frames), render_hearts(1)).getbbox() is None


def test_clear_discards_pending_visuals_on_restart_or_load():
    board = Board(frozenset({(0, 0)}), (Arrow("a", ((0, 0),), Direction.UP),))
    effects = GameplayEffects()
    effects.start(GameSession(board).click("a"))
    assert effects.active
    effects.clear()
    assert not effects.active and effects.remaining_seconds == 0 and not effects.animations
