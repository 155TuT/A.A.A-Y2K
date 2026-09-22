"""Campaign progression, countdowns, endless rewards, and exact run snapshots."""
from dataclasses import dataclass, field
import math
from random import Random
from uuid import uuid4

from .catalog import maps_for
from .canvas import validate_canvas
from .generation import GenerateConfig, generate
from .model import Arrow, Board, Cell, Direction, GameSession, MoveResult
from .solver import solve

MODES = ("easy", "medium", "hard", "endless")
OUTCOMES = ("playing", "level_won", "lost", "campaign_won", "endless_won")
SNAPSHOT_VERSION = 1


def difficulty_for_level(index: int, mode: str = "easy") -> str:
    if not 1 <= index <= 50:
        raise ValueError("Campaign level must be between 1 and 50")
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")
    if mode in ("hard", "endless"):
        return mode
    if mode == "medium":
        return "medium" if index <= 10 else "hard"
    return "easy" if index <= 3 else "medium" if index <= 10 else "hard"


def countdown(difficulty: str) -> float | None:
    return {"easy": None, "medium": 240.0, "hard": 120.0, "endless": 30.0}[difficulty]


@dataclass
class GameRun:
    session: GameSession
    mode: str
    difficulty: str
    level_index: int
    seed: str
    seconds_left: float | None
    elapsed_seconds: float = 0.0
    combo: int = 0
    best_combo: int = 0
    outcome: str = "playing"
    failure_reason: str = ""
    custom: bool = False
    counted: bool = False
    name: str = ""
    description: str = ""
    tutorial: bool = True
    assisted: bool = False
    run_id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def combo_bonus_seconds(self) -> int:
        return 3 + min(7, self.combo // 10)

    @property
    def collision_penalty_seconds(self) -> int:
        return {"easy": 0, "medium": 10, "hard": 20, "endless": 20}[self.difficulty]

    @property
    def completion_id(self) -> str:
        return f"{self.run_id}:{self.level_index}"

    @classmethod
    def new(cls, mode: str, seed: str, tutorial: bool = True) -> "GameRun":
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}")
        return cls._level(mode, str(seed), 1, tutorial)

    @classmethod
    def _level(cls, mode: str, seed: str, index: int, tutorial: bool) -> "GameRun":
        difficulty = "endless" if mode == "endless" else difficulty_for_level(index, mode)
        tier = "hard" if mode == "endless" else difficulty
        templates = maps_for(tier)
        if tier == "easy":
            template = templates[index - 1]
            density, length, turns = ((0.55, 2, 0.0), (0.62, 6, 0.6), (0.70, 10, 0.8))[index - 1]
        else:
            template = Random(f"{seed}|{mode}|{index}|template").choice(templates)
            density, length, turns = (0.83, 10, 0.65) if tier == "medium" else (0.94, 18, 0.8)
        # A board never repeats merely because the run's seed stays constant.
        config = GenerateConfig(f"{seed}|{mode}|{index}", density, length, turns)
        level = generate(template.mask, config)
        label = f"无尽 {index:02d}" if mode == "endless" else f"{index:02d}"
        descriptions = {
            1: "观察箭头指向；头部前方没有遮挡时即可飞出。",
            2: "折线的最后一段决定方向，点击路径任意一格都能选中。",
            3: "心形棋盘中的空白不会截断射线，先移除外层遮挡。",
        }
        description = (descriptions[index] if tier == "easy" and tutorial else
                       "寻找畅通的头部射线，依次清空棋盘。")
        if mode == "endless":
            description = "连消增加时间；100 连击或剩余时间超过 15 分钟即可通关。"
        session = GameSession(level.board)
        if mode == "endless":
            session.lives = 1
        return cls(session, mode, difficulty, index, seed, countdown(difficulty),
                   name=f"{label} / {template.name}", description=description, tutorial=tutorial)

    @classmethod
    def from_custom(cls, mask: frozenset[Cell], config: GenerateConfig, difficulty: str) -> "GameRun":
        if difficulty not in ("easy", "medium", "hard"):
            raise ValueError("Custom maps support easy, medium, or hard difficulty")
        validate_canvas(mask)
        level = generate(mask, config)
        return cls(GameSession(level.board), difficulty, difficulty, 1, str(config.seed),
                   countdown(difficulty), custom=True, tutorial=False, name="自制地图 / 自由拼图",
                   description="自制地图已验证有解；本局不计入战役解锁。")

    def click(self, arrow_id: str) -> MoveResult:
        if self.outcome != "playing":
            return MoveResult("ignored", self.session.remaining.get(arrow_id), None, self.session.lives)
        result = self.session.click(arrow_id)
        if result.kind == "ignored":
            return result
        if result.kind == "collision":
            self.combo = 0
            if self.seconds_left is not None:
                self.seconds_left = max(0.0, self.seconds_left - self.collision_penalty_seconds)
            # The same collision may exhaust both lives and time; life loss wins.
            if self.session.status == "lost":
                self.outcome, self.failure_reason = "lost", "lives"
            elif self.seconds_left == 0:
                self.outcome, self.failure_reason = "lost", "timeout"
                self.session.status = "lost"
            return result
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        if self.mode == "endless":
            self.seconds_left += self.combo_bonus_seconds
            if self.combo >= 100 or self.seconds_left > 900:
                self.outcome = "endless_won"
                return result
        if self.session.status == "won":
            self.outcome = ("campaign_won" if not self.custom and self.mode != "endless"
                            and self.level_index == 50 else "level_won")
        return result

    def tick(self, seconds: float) -> None:
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed tick must be a finite nonnegative duration")
        if self.outcome != "playing":
            return
        elapsed = seconds if self.seconds_left is None else min(seconds, self.seconds_left)
        self.elapsed_seconds += elapsed
        if self.seconds_left is not None:
            self.seconds_left = max(0.0, self.seconds_left - seconds)
            if self.seconds_left == 0:
                self.outcome, self.failure_reason = "lost", "timeout"
                self.session.status = "lost"

    def advance(self) -> bool:
        if self.outcome != "level_won" or self.custom:
            return False
        following = self._level(self.mode, self.seed, self.level_index + 1, self.tutorial)
        following.run_id = self.run_id
        if self.mode == "endless":
            following.session.lives = min(3, self.session.lives + 1)
            following.seconds_left = self.seconds_left
            following.elapsed_seconds = self.elapsed_seconds
            following.combo = self.combo
            following.best_combo = self.best_combo
            following.assisted = self.assisted
        self.__dict__.update(following.__dict__)
        return True

    def restart(self) -> None:
        self.session.restart()
        if self.mode == "endless":
            self.session.lives = 1
        self.seconds_left = countdown(self.difficulty)
        self.elapsed_seconds = 0.0
        self.combo = self.best_combo = 0
        self.outcome, self.failure_reason = "playing", ""
        self.counted = self.assisted = False

    def to_dict(self) -> dict:
        fields = ("mode", "difficulty", "level_index", "seed", "seconds_left", "elapsed_seconds",
                  "combo", "best_combo", "outcome", "failure_reason", "custom", "counted", "name",
                  "description", "tutorial", "assisted", "run_id")
        return {
            "version": SNAPSHOT_VERSION,
            "run": {key: getattr(self, key) for key in fields},
            "board": {
                "mask": [list(cell) for cell in sorted(self.session.board.mask)],
                "arrows": [{"id": arrow.id, "cells": [list(cell) for cell in arrow.cells],
                            "direction": arrow.direction.name} for arrow in self.session.board.arrows],
            },
            "remaining_ids": list(self.session.remaining),
            "lives": self.session.lives,
            "moves": self.session.moves,
            "session_status": self.session.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameRun":
        """Validate public JSON data before restoring; never invoke generation."""
        try:
            return cls._restore(data)
        except (KeyError, TypeError, IndexError, OverflowError) as error:
            raise ValueError(f"Invalid game snapshot: {error}") from error

    @classmethod
    def _restore(cls, data: dict) -> "GameRun":
        if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION:
            raise ValueError("Unsupported game snapshot version")
        raw = data["run"]
        if not isinstance(raw, dict):
            raise ValueError("Snapshot run must be an object")
        fields = ("mode", "difficulty", "level_index", "seed", "seconds_left", "elapsed_seconds",
                  "combo", "best_combo", "outcome", "failure_reason", "custom", "counted", "name",
                  "description", "tutorial", "run_id")
        values = {key: raw[key] for key in fields}
        values["assisted"] = raw.get("assisted", False)
        for key in ("mode", "difficulty", "seed", "outcome", "failure_reason", "name", "description", "run_id"):
            if not isinstance(values[key], str):
                raise ValueError(f"{key} must be text")
        for key in ("level_index", "combo", "best_combo"):
            if type(values[key]) is not int or values[key] < (1 if key == "level_index" else 0):
                raise ValueError(f"Invalid {key}")
        for key in ("custom", "counted", "tutorial", "assisted"):
            if type(values[key]) is not bool:
                raise ValueError(f"{key} must be boolean")
        if values["mode"] not in MODES or values["difficulty"] not in MODES or values["outcome"] not in OUTCOMES:
            raise ValueError("Unknown mode, difficulty, or outcome")
        if not values["run_id"] or values["best_combo"] < values["combo"]:
            raise ValueError("Invalid run identity or combo")
        if values["custom"] and values["mode"] == "endless":
            raise ValueError("Endless is not a custom-map mode")
        if not values["custom"]:
            expected = "endless" if values["mode"] == "endless" else difficulty_for_level(values["level_index"], values["mode"])
            if values["difficulty"] != expected:
                raise ValueError("Difficulty does not match progression")
        elif values["difficulty"] != values["mode"]:
            raise ValueError("Custom-map difficulty does not match mode")
        for key in ("seconds_left", "elapsed_seconds"):
            value = values[key]
            if key == "seconds_left" and value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid {key}")
        if (values["seconds_left"] is None) != (values["difficulty"] == "easy"):
            raise ValueError("Countdown does not match difficulty")
        if values["failure_reason"] not in ("", "lives", "timeout"):
            raise ValueError("Unknown failure reason")

        def cells(value):
            if not isinstance(value, list):
                raise ValueError("Cell collection must be a list")
            result = []
            for cell in value:
                if not isinstance(cell, list) or len(cell) != 2 or any(type(v) is not int for v in cell):
                    raise ValueError("Cell coordinates must be integer pairs")
                x, y = cell
                result.append((x, y))
            if len(set(result)) != len(result):
                raise ValueError("Duplicate cell coordinates")
            validate_canvas(result)
            return tuple(result)

        mask = frozenset(cells(data["board"]["mask"]))
        arrows = []
        for item in data["board"]["arrows"]:
            if not isinstance(item["id"], str) or not item["id"]:
                raise ValueError("Arrow IDs must be nonempty text")
            arrows.append(Arrow(item["id"], cells(item["cells"]), Direction[item["direction"]]))
        board = Board(mask, tuple(arrows))
        if not arrows or not solve(board).solvable:
            raise ValueError("Snapshot initial board must have a complete solution")
        session = GameSession(board)
        ids = data["remaining_ids"]
        if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
            raise ValueError("Remaining arrow IDs must be a list of strings")
        if len(set(ids)) != len(ids) or not set(ids) <= session.remaining.keys():
            raise ValueError("Unknown or duplicated remaining arrow ID")
        session.remaining = {key: session.remaining[key] for key in ids}
        for key in ("lives", "moves"):
            if type(data[key]) is not int or data[key] < 0:
                raise ValueError(f"Invalid {key}")
        if data["lives"] > 3:
            raise ValueError("Lives exceed three")
        session.lives, session.moves = data["lives"], data["moves"]
        session.status = data["session_status"]
        outcome, reason = values["outcome"], values["failure_reason"]
        if outcome == "lost":
            if session.status != "lost" or reason not in ("lives", "timeout"):
                raise ValueError("Lost snapshot has inconsistent status")
            if reason == "lives" and session.lives != 0:
                raise ValueError("Life loss requires zero lives")
            if reason == "timeout" and values["seconds_left"] != 0:
                raise ValueError("Timeout requires an exhausted clock")
        else:
            if reason or session.lives == 0:
                raise ValueError("Active/won snapshot has inconsistent life state")
            if outcome in ("level_won", "campaign_won"):
                if session.remaining or session.status != "won":
                    raise ValueError("Cleared outcome requires an empty board")
            elif outcome == "playing":
                if not session.remaining or session.status != "playing" or values["seconds_left"] == 0:
                    raise ValueError("Playing snapshot is not playable")
            elif outcome == "endless_won":
                if values["mode"] != "endless" or not (values["combo"] >= 100 or values["seconds_left"] > 900):
                    raise ValueError("Endless victory threshold was not reached")
                if session.status != ("playing" if session.remaining else "won"):
                    raise ValueError("Endless snapshot session status is inconsistent")
        if outcome == "campaign_won" and (values["custom"] or values["mode"] == "endless" or values["level_index"] != 50):
            raise ValueError("Campaign victory requires level 50")
        return cls(session=session, **values)
