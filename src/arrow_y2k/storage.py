"""Local settings, profile, five run slots and a separate custom-map collection.

All paths are owned by GameStore. Game rules and run serialization stay in
campaign.GameRun. Writes replace a same-directory temporary file atomically.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import TYPE_CHECKING
from uuid import uuid4

from platformdirs import user_data_dir

from .generation import GenerateConfig
from .canvas import validate_canvas
from .model import Board, Cell

if TYPE_CHECKING:
    from .campaign import GameRun

SCHEMA_VERSION = 1
DIFFICULTIES = frozenset(("easy", "medium", "hard"))
MODES = DIFFICULTIES | {"endless"}
RESOLUTIONS = frozenset(("1024x768", "1280x720", "1920x1080"))


def user_data_root() -> Path:
    """One owner for the installation-independent application data directory."""
    return Path(user_data_dir("ArrowAfterArrowY2K", appauthor=False))


class DomainStorageError(ValueError):
    """A storage error that a UI can show directly without terminating the game."""


@dataclass
class Settings:
    autosave: bool = True
    save_minutes: int = 3
    master_volume: float = 0.65
    effects_volume: float = 0.7
    muted: bool = False
    resolution: str = "1280x720"
    reduced_motion: bool = False

    def validate(self) -> None:
        for name in ("autosave", "muted", "reduced_motion"):
            if type(getattr(self, name)) is not bool:
                raise DomainStorageError(f"设置 {name} 必须为开关值。")
        if type(self.save_minutes) is not int or not 1 <= self.save_minutes <= 60:
            raise DomainStorageError("自动保存间隔须为 1–60 分钟。")
        for name in ("master_volume", "effects_volume"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise DomainStorageError("音量须在 0 到 1 之间。")
        if self.resolution not in RESOLUTIONS:
            raise DomainStorageError("不支持该窗口分辨率。")


@dataclass
class Profile:
    unlocked_modes: set[str] = field(default_factory=lambda: {"easy"})
    total_arrows: int = 0
    current_streak: int = 0
    best_streak: int = 0
    endless_best_seconds: float | None = None
    edited_map: bool = False
    achievements: set[str] = field(default_factory=lambda: {"mode_easy"})
    tutorial_completed: bool = False
    completed_levels: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        result = asdict(self)
        for key in ("unlocked_modes", "achievements", "completed_levels"):
            result[key] = sorted(result[key])
        return result

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        if not isinstance(data, dict):
            raise DomainStorageError("玩家记录格式不正确。")
        result = cls()
        for key in ("unlocked_modes", "achievements", "completed_levels"):
            if key in data:
                value = data[key]
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    raise DomainStorageError("玩家记录中的列表格式不正确。")
                setattr(result, key, set(value))
        result.unlocked_modes.add("easy")
        result.achievements.add("mode_easy")
        if not result.unlocked_modes <= MODES:
            raise DomainStorageError("玩家记录包含未知模式。")
        for key in ("total_arrows", "current_streak", "best_streak"):
            value = data.get(key, 0)
            if type(value) is not int or value < 0:
                raise DomainStorageError("玩家记录中的计数必须为非负整数。")
            setattr(result, key, value)
        result.best_streak = max(result.best_streak, result.current_streak)
        for key in ("edited_map", "tutorial_completed"):
            value = data.get(key, False)
            if type(value) is not bool:
                raise DomainStorageError("玩家记录中的开关格式不正确。")
            setattr(result, key, value)
        value = data.get("endless_best_seconds")
        if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or value <= 0):
            raise DomainStorageError("无尽模式纪录必须为有效的正数秒数。")
        result.endless_best_seconds = value
        return result


@dataclass(frozen=True)
class SaveSummary:
    slot: int
    level_index: int
    difficulty: str
    left: int
    total: int
    lives: int
    saved_at: str
    mode: str


@dataclass(frozen=True)
class CustomMap:
    id: str
    name: str
    difficulty: str
    mask: frozenset[Cell]
    config: GenerateConfig


def _json_read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DomainStorageError(f"无法读取 {path.name}：{error}") from error
    if not isinstance(value, dict):
        raise DomainStorageError(f"{path.name} 必须包含 JSON 对象。")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise DomainStorageError(f"{path.name} 的数据版本不受支持。")
    return value


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(payload, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as error:
        raise DomainStorageError(f"无法保存 {path.name}：{error}") from error
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass  # Preserve the original failure; an orphan temp is harmless.


def _map_payload(item: CustomMap) -> dict:
    return {"schema_version": SCHEMA_VERSION, "kind": "custom_map", "id": item.id,
            "name": item.name, "difficulty": item.difficulty,
            "mask": [list(cell) for cell in sorted(item.mask, key=lambda cell: (cell[1], cell[0]))],
            "config": asdict(item.config)}


def _parse_map(data: dict) -> CustomMap:
    try:
        if data.get("kind") != "custom_map":
            raise DomainStorageError("文件不是可导入的自定义地图。")
        _validate_map_id(data["id"])
        name, difficulty = data["name"], data["difficulty"]
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise DomainStorageError("地图名称须为 1–80 个字符。")
        if difficulty not in DIFFICULTIES:
            raise DomainStorageError("地图难度必须为 easy、medium 或 hard。")
        raw_mask = data["mask"]
        if not isinstance(raw_mask, list) or any(
            not isinstance(cell, list) or len(cell) != 2
            or any(type(value) is not int or value < 0 for value in cell)
            for cell in raw_mask
        ):
            raise DomainStorageError("地图坐标必须为非负整数对。")
        mask = frozenset(tuple(cell) for cell in raw_mask)
        if len(mask) != len(raw_mask):
            raise DomainStorageError("地图包含重复格子。")
        validate_canvas(mask)
        Board(mask)
        raw_config = data["config"]
        if not isinstance(raw_config, dict) or not isinstance(raw_config.get("seed", "2026"), str):
            raise DomainStorageError("生成参数必须为对象，种子必须为文本。")
        for key, default in (("min_length", 1), ("max_length", 7)):
            if type(raw_config.get(key, default)) is not int:
                raise DomainStorageError("箭头长度必须为整数。")
        for key, default in (("density", 0.75), ("turn_bias", 0.6)):
            value = raw_config.get(key, default)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise DomainStorageError("密度与转弯偏好必须为有限数值。")
        config = GenerateConfig(**raw_config)
        return CustomMap(data["id"], name.strip(), difficulty, mask, config)
    except DomainStorageError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise DomainStorageError(f"地图数据不正确：{error}") from error


def _validate_map_id(map_id: str) -> None:
    if not isinstance(map_id, str) or re.fullmatch(r"[0-9a-f]{32}", map_id) is None:
        raise DomainStorageError("地图 ID 无效；内置模板不属于可删除的自定义地图。")


def _read_map_file(path: Path) -> CustomMap:
    """One decoder for current map files and the original demo's export format."""
    path = Path(path)
    data = _json_read(path)
    if "kind" not in data and "cells" in data and "generation" in data:
        data = {"schema_version": SCHEMA_VERSION, "kind": "custom_map",
                "id": uuid4().hex, "name": path.stem[:80] or "导入地图",
                "difficulty": "easy", "mask": data["cells"], "config": data["generation"]}
    return _parse_map(data)


class GameStore:
    """Persistent state rooted in platformdirs, or an injected isolated folder."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else user_data_root()
        self.warnings: list[str] = []
        self.settings = Settings()
        self.profile = Profile()
        settings_path = self.root / "settings.json"
        if settings_path.exists():
            try:
                data = _json_read(settings_path)
                self.settings = Settings(**data["settings"])
                self.settings.validate()
            except (DomainStorageError, KeyError, TypeError) as error:
                self.settings = Settings()
                self._warn(f"设置载入失败，当前使用默认值（原文件已保留）：{error}")
        profile_path = self.root / "profile.json"
        if profile_path.exists():
            try:
                self.profile = Profile.from_dict(_json_read(profile_path)["profile"])
            except (DomainStorageError, KeyError, TypeError) as error:
                self.profile = Profile()
                self._warn(f"玩家记录载入失败，当前使用空白记录（原文件已保留）：{error}")

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def save_settings(self) -> None:
        self.settings.validate()
        _atomic_json(self.root / "settings.json",
                     {"schema_version": SCHEMA_VERSION, "settings": asdict(self.settings)})

    def save_profile(self) -> None:
        payload = self.profile.to_dict()
        Profile.from_dict(payload)
        _atomic_json(self.root / "profile.json",
                     {"schema_version": SCHEMA_VERSION, "profile": payload})

    def _slot_path(self, index: int) -> Path:
        if type(index) is not int or not 0 <= index < 5:
            raise DomainStorageError("存档槽编号必须为 0–4；0 为自动保存。")
        return self.root / "slots" / f"slot-{index}.json"

    def save_slot(self, index: int, run: GameRun) -> None:
        path = self._slot_path(index)
        _atomic_json(path, {"schema_version": SCHEMA_VERSION, "kind": "game_run",
                            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "run": run.to_dict()})

    def _read_slot(self, index: int):
        from .campaign import GameRun

        path = self._slot_path(index)
        if not path.exists():
            return None
        data = _json_read(path)
        try:
            if data.get("kind") != "game_run":
                raise DomainStorageError("文件不是游戏存档。")
            stamp = data["saved_at"]
            if not isinstance(stamp, str) or datetime.fromisoformat(stamp).utcoffset() is None:
                raise DomainStorageError("存档时间格式不正确。")
            run = GameRun.from_dict(data["run"])
            return data, run
        except DomainStorageError:
            raise
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise DomainStorageError(f"存档 {index} 数据不正确：{error}") from error

    def load_slot(self, index: int) -> GameRun | None:
        result = self._read_slot(index)
        return None if result is None else result[1]

    def slots(self) -> list[SaveSummary | None]:
        result = []
        for index in range(5):
            try:
                loaded = self._read_slot(index)
                if loaded is None:
                    result.append(None)
                    continue
                data, run = loaded
                session = run.session
                result.append(SaveSummary(index, run.level_index, run.difficulty,
                                          len(session.current_board.arrows), len(session.board.arrows),
                                          session.lives, data["saved_at"], run.mode))
            except DomainStorageError as error:
                result.append(None)
                self._warn(str(error))
        return result

    def delete_slot(self, index: int) -> None:
        path = self._slot_path(index)
        if index == 0:
            raise DomainStorageError("自动存档由游戏管理，不能手动删除。")
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise DomainStorageError(f"无法删除存档：{error}") from error

    def _map_path(self, map_id: str) -> Path:
        _validate_map_id(map_id)
        return self.root / "custom_maps" / f"{map_id}.json"

    def _load_custom_map(self, map_id: str) -> CustomMap:
        item = _parse_map(_json_read(self._map_path(map_id)))
        if item.id != map_id:
            raise DomainStorageError("地图 ID 与文件名不一致。")
        return item

    def list_custom_maps(self) -> list[CustomMap]:
        result = []
        for path in sorted((self.root / "custom_maps").glob("*.json")):
            try:
                result.append(self._load_custom_map(path.stem))
            except DomainStorageError as error:
                self._warn(str(error))
        return sorted(result, key=lambda item: (item.name.casefold(), item.id))

    def save_custom_map(self, name: str, mask: frozenset[Cell], config: GenerateConfig,
                        difficulty: str, map_id: str | None = None) -> CustomMap:
        item = CustomMap(map_id or uuid4().hex, name, difficulty, frozenset(mask), config)
        payload = _map_payload(item)
        item = _parse_map(payload)
        _atomic_json(self._map_path(item.id), _map_payload(item))
        return item

    def delete_custom_map(self, map_id: str) -> None:
        path = self._map_path(map_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise DomainStorageError(f"无法删除地图：{error}") from error

    def export_custom_map(self, map_id: str, path: Path) -> None:
        item = self._load_custom_map(map_id)
        _atomic_json(Path(path), _map_payload(item))

    def import_custom_map(self, path: Path) -> CustomMap:
        item = _read_map_file(Path(path))
        # An import creates its own identity, so another user's ID cannot replace
        # any map already in this collection.
        return self.save_custom_map(item.name, item.mask, item.config, item.difficulty)

def save_map(path: str | Path, mask: frozenset[Cell], config: GenerateConfig) -> None:
    """Compatibility export; validation and disk writes use the shared store codec."""
    path = Path(path)
    item = _parse_map(_map_payload(CustomMap(uuid4().hex, path.stem[:80] or "地图",
                                           "easy", mask, config)))
    board = Board(item.mask)
    _atomic_json(path, {"schema_version": SCHEMA_VERSION,
                       "width": board.width, "height": board.height,
                       "cells": [list(cell) for cell in sorted(item.mask)],
                       "generation": asdict(item.config)})


def load_map(path: str | Path) -> tuple[frozenset[Cell], GenerateConfig]:
    """Compatibility API: both map formats share one decoder and validation path."""
    item = _read_map_file(Path(path))
    return item.mask, item.config
