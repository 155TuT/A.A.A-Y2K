"""Real progression, snapshots, and countdown/reward regression tests."""
from copy import deepcopy
import math
import pytest
from arrow_y2k import campaign
from arrow_y2k.campaign import GameRun, difficulty_for_level
from arrow_y2k.catalog import preset_maps
from arrow_y2k.generation import GenerateConfig, template_mask
from arrow_y2k.model import Arrow, Board, Direction, GameSession
from arrow_y2k.solver import solve, validate_certificate

def clear(run):
    for arrow_id in solve(run.session.current_board).order:
        if run.outcome != "playing":
            break
        assert run.click(arrow_id).kind == "escaped"

def many_arrows(count=120):
    mask = template_mask("rectangle", 20, 6)
    cells = sorted(mask, key=lambda c: (c[1], c[0]))[:count]
    return Board(mask, tuple(Arrow(str(i), (cell,), Direction.UP) for i, cell in enumerate(cells)))

def test_catalog_connected_and_sized():
    maps = preset_maps()
    assert len({m.id for m in maps}) == 15
    for item in maps:
        assert all(0 <= x < 20 and 0 <= y < 16 for x, y in item.mask)
        if item.difficulty == "medium":
            assert 80 <= len(item.mask) <= 150
        if item.difficulty == "hard":
            assert 150 <= len(item.mask) <= 250
        remaining = set(item.mask)
        frontier = [remaining.pop()]
        while frontier:
            x, y = frontier.pop()
            for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if cell in remaining:
                    remaining.remove(cell)
                    frontier.append(cell)
        assert not remaining

@pytest.mark.parametrize("mode,seconds", [("easy",None),("medium",240),("hard",120),("endless",30)])
def test_new_modes_start_at_one_and_snapshot_roundtrip(mode,seconds):
    for seed in range(8):
        run = GameRun.new(mode,str(seed))
        assert (run.level_index,run.difficulty,run.seconds_left) == (1,mode,seconds)
        assert run.session.lives == (1 if mode == "endless" else 3)
        assert GameRun.from_dict(run.to_dict()).to_dict() == run.to_dict()
        assert validate_certificate(run.session.board,solve(run.session.board).order)

@pytest.mark.parametrize("mode", ["easy","medium","hard"])
def test_full_fifty_level_progression(mode):
    run = GameRun.new(mode,"sweep")
    run_id = run.run_id
    for index in range(1,51):
        expected = ("hard" if mode == "hard" or index >= 11 else
                    "medium" if mode == "medium" or index >= 4 else "easy")
        assert run.level_index == index and run.difficulty == expected
        assert difficulty_for_level(index,mode) == expected
        assert run.seconds_left == {"easy":None,"medium":240,"hard":120}[expected]
        assert run.elapsed_seconds == 0 and not run.counted
        run.tick(.25)
        clear(run)
        run.counted = True
        if index < 50:
            assert run.outcome == "level_won" and run.advance()
            assert run.run_id == run_id
        else:
            assert run.outcome == "campaign_won" and not run.advance()
            assert GameRun.from_dict(run.to_dict()).to_dict() == run.to_dict()

def test_tutorial_seed_randomness_and_shapes():
    for index,shape in ((1,(6,6)),(2,(9,6)),(3,(9,8))):
        first = GameRun._level("easy","alpha",index,True)
        assert first.session.board == GameRun._level("easy","alpha",index,True).session.board
        assert first.session.board != GameRun._level("easy","beta",index,True).session.board
        assert (first.session.board.width,first.session.board.height) == shape
        assert all(a.id.startswith("a") for a in first.session.board.arrows)
        if index == 1:
            assert all(len(a.cells) <= 2 for a in first.session.board.arrows)

def test_timeout_restart_and_invalid_ticks():
    run = GameRun.new("medium","timer")
    initial = run.session.board
    run.tick(239.75)
    assert run.seconds_left == .25
    run.tick(50)
    assert (run.seconds_left,run.elapsed_seconds,run.outcome,run.failure_reason) == (0,240,"lost","timeout")
    assert run.session.lives == 3 and run.session.status == "lost"
    assert run.click(next(iter(run.session.remaining))).kind == "ignored"
    assert GameRun.from_dict(run.to_dict()).to_dict() == run.to_dict()
    run.restart()
    assert run.session.current_board == initial
    assert (run.seconds_left,run.elapsed_seconds,run.combo,run.best_combo) == (240,0,0,0)
    assert run.outcome == "playing" and not run.failure_reason
    for value in (-1,math.inf,math.nan,"1"):
        with pytest.raises(ValueError):
            run.tick(value)
    easy = GameRun.new("easy","clock")
    easy.tick(1234.5)
    assert easy.seconds_left is None and easy.elapsed_seconds == 1234.5

def test_endless_bonus_collision_and_life_loss():
    run = GameRun.new("endless","bonus")
    run.session = GameSession(many_arrows())
    expected = 30
    for combo,arrow_id in enumerate(solve(run.session.board).order[:25],1):
        assert run.click(arrow_id).kind == "escaped"
        expected += 3 + min(7,combo//10)
        assert run.seconds_left == expected and run.combo == run.best_combo == combo
        assert run.click(arrow_id).kind == "ignored" and run.seconds_left == expected
    run.session = GameSession(Board(frozenset({(0,0),(1,0)}),(
        Arrow("blocked",((0,0),),Direction.RIGHT),Arrow("free",((1,0),),Direction.UP))))
    for life in (2,1,0):
        assert run.click("blocked").kind == "collision"
        expected -= 20
        assert run.combo == 0 and run.session.lives == life and run.seconds_left == expected
    assert (run.outcome,run.failure_reason) == ("lost","lives")

@pytest.mark.parametrize("condition",["combo","time"])
def test_endless_win_midboard_and_exact_time_boundary(condition):
    run = GameRun.new("endless",condition)
    run.session = GameSession(many_arrows())
    order = solve(run.session.board).order
    if condition == "combo":
        run.combo = run.best_combo = 99
        run.seconds_left = 10
        run.click(order[0])
        assert run.combo == 100 and run.seconds_left == 20
    else:
        run.seconds_left = 897
        run.click(order[0])
        assert run.seconds_left == 900 and run.outcome == "playing"
        run.click(order[1])
        assert run.seconds_left == 903
    assert run.outcome == "endless_won" and run.session.remaining
    saved = run.to_dict()
    run.tick(50)
    assert run.click(order[2]).kind == "ignored" and run.to_dict() == saved
    assert GameRun.from_dict(saved).to_dict() == saved

@pytest.mark.parametrize("lives,next_lives", [(1,2),(2,3),(3,3)])
def test_endless_carries_clock_combo_elapsed_and_adds_one_life(lives, next_lives):
    run = GameRun.new("endless","carry")
    run.session = GameSession(many_arrows(2))
    run.tick(4.25)
    run.session.lives = lives
    clear(run)
    before = (run.seconds_left,run.combo,run.best_combo,run.elapsed_seconds,run.run_id)
    assert run.outcome == "level_won" and run.advance()
    assert run.level_index == 2 and run.session.lives == next_lives
    assert (run.seconds_left,run.combo,run.best_combo,run.elapsed_seconds,run.run_id) == before
    run.restart()
    assert (run.seconds_left,run.combo,run.best_combo,run.elapsed_seconds,run.session.lives) == (30,0,0,0,1)

def test_custom_maps_never_advance_campaign():
    run = GameRun.from_custom(frozenset({(0,0),(2,0),(2,2)}),GenerateConfig("custom",1,3,.8),"hard")
    assert run.custom and run.seconds_left == 120
    assert GameRun.from_dict(run.to_dict()).to_dict() == run.to_dict()
    clear(run)
    assert run.outcome == "level_won" and not run.advance()

def test_restore_does_not_regenerate(monkeypatch):
    run = GameRun.new("medium","exact")
    run.click(solve(run.session.board).order[0])
    run.tick(7.125)
    run.assisted = True
    saved = run.to_dict()
    def forbidden(*args,**kwargs): raise AssertionError("Snapshot restore regenerated")
    monkeypatch.setattr(campaign,"generate",forbidden)
    restored = GameRun.from_dict(saved)
    assert restored.to_dict() == saved and restored.completion_id == run.completion_id

@pytest.mark.parametrize("mutation",[
    lambda d:d.update(version=2),
    lambda d:d["run"].update(seconds_left=math.nan),
    lambda d:d["run"].update(elapsed_seconds=-1),
    lambda d:d["run"].update(difficulty="easy"),
    lambda d:d["run"].update(level_index=0),
    lambda d:d["run"].update(outcome="campaign_won"),
    lambda d:d.update(lives=4),
    lambda d:d.update(remaining_ids=["unknown"]),
    lambda d:d["remaining_ids"].append(d["remaining_ids"][0]),
    lambda d:d["board"]["mask"].append(d["board"]["mask"][0]),
    lambda d:d["board"]["mask"][0].__setitem__(0,1.5),
    lambda d:d["board"]["arrows"][0].update(direction="DIAGONAL"),
])
def test_invalid_snapshots_fail_with_value_error(mutation):
    data = deepcopy(GameRun.new("medium","validation").to_dict())
    mutation(data)
    with pytest.raises(ValueError):
        GameRun.from_dict(data)


def collision_run(mode, *, lives=3, seconds=None):
    board = Board(frozenset({(0,0),(1,0)}), (
        Arrow("blocked", ((0,0),), Direction.RIGHT),
        Arrow("free", ((1,0),), Direction.UP),
    ))
    run = GameRun.new(mode, "collision-penalty")
    run.session = GameSession(board)
    run.session.lives = lives
    if seconds is not None:
        run.seconds_left = seconds
    run.combo = run.best_combo = 9
    return run


@pytest.mark.parametrize("mode,penalty", [("easy",0),("medium",10),("hard",20),("endless",20)])
def test_collision_penalty_counts_time_once_and_preserves_wall_time(mode, penalty):
    run = collision_run(mode)
    run.tick(2.25)
    before = run.seconds_left
    assert run.collision_penalty_seconds == penalty
    result = run.click("blocked")
    assert result.kind == "collision" and result.lives == run.session.lives == 2
    assert run.seconds_left == (None if before is None else before - penalty)
    assert run.elapsed_seconds == 2.25
    assert run.combo == 0 and run.best_combo == 9 and run.outcome == "playing"
    after = run.seconds_left
    assert run.click("missing").kind == "ignored" and run.seconds_left == after
    assert GameRun.from_dict(run.to_dict()).to_dict() == run.to_dict()


@pytest.mark.parametrize("mode,penalty", [("medium",10),("hard",20),("endless",20)])
@pytest.mark.parametrize("fraction", [0.5, 1.0])
@pytest.mark.parametrize("lives,reason", [(1,"lives"),(2,"timeout")])
def test_collision_clamps_clock_and_life_loss_precedes_timeout(mode, penalty, fraction, lives, reason):
    run = collision_run(mode, lives=lives, seconds=penalty * fraction)
    assert run.click("blocked").kind == "collision"
    assert (run.seconds_left, run.session.lives, run.session.status, run.outcome, run.failure_reason) == (
        0, lives - 1, "lost", "lost", reason)
    snapshot = run.to_dict()
    assert GameRun.from_dict(snapshot).to_dict() == snapshot
    assert run.click("free").kind == "ignored"
    run.tick(50)
    assert run.to_dict() == snapshot


@pytest.mark.parametrize("mode,seconds,lives,restart_seconds,restart_lives", [
    ("medium", 597.25, 2, 240, 3),
    ("hard", 473.5, 1, 120, 3),
    ("endless", 111.125, 3, 30, 1),
])
def test_legacy_snapshot_preserves_exact_clock_and_lives_until_restart(
    mode, seconds, lives, restart_seconds, restart_lives,
):
    old = GameRun.new(mode, "legacy-run").to_dict()
    old["run"]["seconds_left"] = seconds
    old["lives"] = lives
    restored = GameRun.from_dict(old)
    assert restored.to_dict() == old
    restored.restart()
    assert (restored.seconds_left, restored.session.lives) == (restart_seconds, restart_lives)
