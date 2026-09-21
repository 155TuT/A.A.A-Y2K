from types import SimpleNamespace

import pytest

from arrow_y2k.achievements import AchievementService
from arrow_y2k.storage import GameStore, Profile


def completed(level, *, run_id="run", mode="easy", custom=False, outcome="level_won"):
    return SimpleNamespace(level_index=level, mode=mode, custom=custom, outcome=outcome,
                           completion_id=f"{run_id}:{level}")


def test_mode_unlock_boundaries_and_initial_easy():
    service = AchievementService(Profile())
    assert [item.id for item in service.list_all() if item.unlocked] == ["mode_easy"]
    assert service.record_level(completed(2)) == []
    assert service.profile.unlocked_modes == {"easy"}
    assert [item.id for item in service.record_level(completed(3))] == ["mode_medium"]
    assert service.profile.tutorial_completed
    service.record_level(completed(9))
    assert "hard" not in service.profile.unlocked_modes
    assert [item.id for item in service.record_level(completed(10))] == ["mode_hard"]
    service.record_level(completed(49))
    assert "endless" not in service.profile.unlocked_modes
    assert [item.id for item in service.record_level(completed(50))] == ["mode_endless"]


def test_official_win_streak_is_idempotent_across_save_load(tmp_path):
    store = GameStore(tmp_path)
    service = AchievementService(store.profile)
    for index in range(1, 11):
        fresh = service.record_level(completed(index))
    assert "streak_10" in [item.id for item in fresh]
    store.save_profile()
    loaded = GameStore(tmp_path)
    resumed = AchievementService(loaded.profile)
    assert resumed.record_level(completed(10)) == []
    assert loaded.profile.current_streak == loaded.profile.best_streak == 10
    assert resumed.record_level(completed(11, custom=True)) == []
    assert resumed.record_level(completed(11, outcome="playing")) == []
    assert resumed.record_level(completed(11, mode="endless", outcome="endless_won")) == []
    resumed.record_loss()
    assert loaded.profile.current_streak == 0
    assert loaded.profile.best_streak == 10
    resumed.record_level(completed(1, run_id="fresh-run"))
    assert loaded.profile.current_streak == 1


@pytest.mark.parametrize("count", [100, 500, 1000, 100000])
def test_arrow_awards_count_only_success_and_toast_once(count):
    profile = Profile(total_arrows=count - 1)
    service = AchievementService(profile)
    assert service.record_arrow(False) == []
    assert profile.total_arrows == count - 1
    assert f"arrows_{count}" in [item.id for item in service.record_arrow(True)]
    assert service.record_arrow(True) == []


@pytest.mark.parametrize("count", [10, 50, 100, 500])
def test_streak_thresholds(count):
    profile = Profile(current_streak=count - 1, best_streak=count - 1)
    service = AchievementService(profile)
    assert f"streak_{count}" in [item.id for item in service.record_level(completed(1))]
    assert service.record_level(completed(1)) == []
    assert profile.best_streak == count


def test_editor_endless_records_and_bad_times():
    service = AchievementService(Profile())
    assert [item.id for item in service.record_editor()] == ["map_editor"]
    assert service.record_editor() == []
    assert [item.id for item in service.record_endless(125)] == ["endless_clear"]
    assert service.record_endless(130) == []
    assert service.profile.endless_best_seconds == 125
    assert service.record_endless(100) == []
    assert service.profile.endless_best_seconds == 100
    for invalid in (0, -1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            service.record_endless(invalid)
