"""Profile achievements and mode unlocks, independent of UI and disk access.

The caller persists Profile after a mutation. Completed official levels are
idempotent across save/load because GameRun supplies a persistent completion_id.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

from .storage import Profile

if TYPE_CHECKING:
    from .campaign import GameRun


@dataclass(frozen=True)
class Achievement:
    id: str
    title: str
    description: str
    unlocked: bool = False


_CATALOG = (
    ("mode_easy", "新手上路", "开始游戏，解锁简单模式。"),
    ("mode_medium", "熟能生巧", "完成正式第 3 关，解锁中等模式。"),
    ("mode_hard", "小有所成", "完成正式第 10 关，解锁困难模式。"),
    ("mode_endless", "炉火纯青", "完成正式第 50 关，解锁无尽模式。"),
    ("arrows_100", "百箭穿杨", "累计成功移除 100 支箭头。"),
    ("arrows_500", "五百箭痕", "累计成功移除 500 支箭头。"),
    ("arrows_1000", "千箭齐发", "累计成功移除 1,000 支箭头。"),
    ("arrows_100000", "十万箭雨", "累计成功移除 100,000 支箭头。"),
    ("streak_10", "十连捷", "正式关卡连续通关 10 次。"),
    ("streak_50", "五十连捷", "正式关卡连续通关 50 次。"),
    ("streak_100", "百战百胜", "正式关卡连续通关 100 次。"),
    ("streak_500", "五百连胜", "正式关卡连续通关 500 次。"),
    ("map_editor", "地图匠人", "编辑一张自定义地图。"),
    ("endless_clear", "无尽突破", "首次完成无尽模式，记录最快完成用时。"),
)
ARROW_THRESHOLDS = (100, 500, 1000, 100000)
STREAK_THRESHOLDS = (10, 50, 100, 500)


class AchievementService:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.profile.unlocked_modes.add("easy")
        # Existing unlocks appear earned without replaying an old toast at launch.
        self.profile.achievements.update(f"mode_{mode}" for mode in self.profile.unlocked_modes)

    def list_all(self) -> list[Achievement]:
        return [Achievement(key, title, description, key in self.profile.achievements)
                for key, title, description in _CATALOG]

    def _award(self, identifiers) -> list[Achievement]:
        identifiers = set(identifiers)
        fresh = [Achievement(key, title, description, True)
                 for key, title, description in _CATALOG
                 if key in identifiers and key not in self.profile.achievements]
        self.profile.achievements.update(item.id for item in fresh)
        return fresh

    def record_arrow(self, success: bool) -> list[Achievement]:
        if not success:
            return []
        self.profile.total_arrows += 1
        return self._award(f"arrows_{count}" for count in ARROW_THRESHOLDS
                           if self.profile.total_arrows >= count)

    def record_level(self, run: GameRun) -> list[Achievement]:
        if run.custom or run.mode == "endless" or run.outcome not in ("level_won", "campaign_won"):
            return []
        if run.completion_id in self.profile.completed_levels:
            return []
        self.profile.completed_levels.add(run.completion_id)
        self.profile.current_streak += 1
        self.profile.best_streak = max(self.profile.best_streak, self.profile.current_streak)
        awards = [f"streak_{count}" for count in STREAK_THRESHOLDS
                  if self.profile.current_streak >= count]
        for cleared_level, mode in ((3, "medium"), (10, "hard"), (50, "endless")):
            if run.level_index >= cleared_level:
                self.profile.unlocked_modes.add(mode)
                awards.append(f"mode_{mode}")
        if run.mode == "easy" and run.level_index >= 3:
            self.profile.tutorial_completed = True
        return self._award(awards)

    def record_loss(self) -> list[Achievement]:
        self.profile.current_streak = 0
        return []

    def record_editor(self) -> list[Achievement]:
        self.profile.edited_map = True
        return self._award(("map_editor",))

    def record_endless(self, seconds: float) -> list[Achievement]:
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("无尽通关用时必须为有效的正数秒数。")
        if self.profile.endless_best_seconds is None or seconds < self.profile.endless_best_seconds:
            self.profile.endless_best_seconds = float(seconds)
        return self._award(("endless_clear",))
