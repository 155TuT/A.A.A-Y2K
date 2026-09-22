from dataclasses import asdict, replace
import json

import pytest

from arrow_y2k.generation import GenerateConfig, template_mask
from arrow_y2k.storage import DomainStorageError, GameStore, Profile, Settings


def test_settings_profile_persist_in_injected_directory(tmp_path):
    store = GameStore(tmp_path)
    assert not (tmp_path / "settings.json").exists()
    assert store.settings.autosave and store.settings.save_minutes == 3
    store.settings.autosave = False
    store.settings.master_volume = 0.25
    store.settings.resolution = "1920x1080"
    store.profile.total_arrows = 120
    store.profile.unlocked_modes.add("medium")
    store.profile.completed_levels.add("run:3")
    store.save_settings()
    store.save_profile()
    loaded = GameStore(tmp_path)
    assert asdict(loaded.settings) == asdict(store.settings)
    assert loaded.profile.to_dict() == store.profile.to_dict()


def test_corrupt_files_preserved_and_explicit_warnings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    (tmp_path / "profile.json").write_text("[]", encoding="utf-8")
    store = GameStore(tmp_path)
    assert store.settings.save_minutes == 3
    assert store.profile.unlocked_modes == {"easy"}
    assert len(store.warnings) == 2
    assert path.read_text(encoding="utf-8") == "{broken"


def test_atomic_write_does_not_destroy_previous_settings(tmp_path, monkeypatch):
    store = GameStore(tmp_path)
    store.save_settings()
    original = (tmp_path / "settings.json").read_bytes()
    store.settings.muted = True
    def fail_replace(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr("arrow_y2k.storage.os.replace", fail_replace)
    with pytest.raises(DomainStorageError):
        store.save_settings()
    assert (tmp_path / "settings.json").read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_custom_collection_roundtrip_updates_import_identity_and_delete(tmp_path):
    store = GameStore(tmp_path / "state")
    mask = template_mask("heart")
    config = GenerateConfig(seed="my seed", density=0.8)
    original = store.save_custom_map("我的心形", mask, config, "medium")
    edited = store.save_custom_map("修改名称", mask, config, "hard", original.id)
    assert edited.id == original.id
    assert store.list_custom_maps() == [edited]
    external = tmp_path / "export" / "my-map.json"
    store.export_custom_map(edited.id, external)
    imported = store.import_custom_map(external)
    assert imported.id != edited.id
    assert (imported.name, imported.mask, imported.config, imported.difficulty) == (
        edited.name, edited.mask, edited.config, edited.difficulty)
    assert len(store.list_custom_maps()) == 2
    store.delete_custom_map(original.id)
    assert store.list_custom_maps() == [imported]
    assert external.exists()


def test_custom_delete_rejects_preset_and_path_traversal(tmp_path):
    store = GameStore(tmp_path)
    for identifier in ("heart", "../profile", "a" * 31, "A" * 32, "", "/tmp/a"):
        with pytest.raises(DomainStorageError):
            store.delete_custom_map(identifier)
    with pytest.raises(DomainStorageError):
        store.save_custom_map("", template_mask("square"), GenerateConfig(), "easy")
    with pytest.raises(DomainStorageError):
        store.save_custom_map("地图", frozenset(), GenerateConfig(), "easy")


def test_invalid_map_import_does_not_change_collection(tmp_path):
    store = GameStore(tmp_path / "state")
    original = store.save_custom_map("原版", template_mask("square"), GenerateConfig(), "easy")
    external = tmp_path / "map.json"
    store.export_custom_map(original.id, external)
    data = json.loads(external.read_text(encoding="utf-8"))
    data["mask"] = [[-1, 0]]
    external.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DomainStorageError):
        store.import_custom_map(external)
    assert store.list_custom_maps() == [original]


def test_slot_bounds_autosave_cannot_be_deleted_and_corruption(tmp_path):
    store = GameStore(tmp_path)
    for index in (-1, 5, True, "1"):
        with pytest.raises(DomainStorageError):
            store.load_slot(index)
    with pytest.raises(DomainStorageError):
        store.delete_slot(0)
    assert store.load_slot(1) is None
    slots = tmp_path / "slots"
    slots.mkdir()
    (slots / "slot-1.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(DomainStorageError):
        store.load_slot(1)
    assert store.slots() == [None] * 5
    assert store.warnings
    store.delete_slot(1)
    assert not (slots / "slot-1.json").exists()


def test_profile_rejects_invalid_counters():
    for data in ({"total_arrows": -1}, {"current_streak": True},
                 {"unlocked_modes": ["unknown"]}, {"endless_best_seconds": float("nan")}):
        with pytest.raises(DomainStorageError):
            Profile.from_dict(data)


def test_five_slots_preserve_real_run_snapshot_without_regeneration(tmp_path, monkeypatch):
    from arrow_y2k.campaign import GameRun
    from arrow_y2k.solver import solve

    store = GameStore(tmp_path)
    run = GameRun.new("medium", seed="storage-roundtrip")
    run.tick(12.75)
    first = solve(run.session.current_board).order[0]
    assert run.click(first).kind == "escaped"
    expected = run.to_dict()
    for index in range(5):
        store.save_slot(index, run)
    def forbid_generation(*args, **kwargs):
        raise AssertionError("Loading a run must restore the board, never regenerate it")
    monkeypatch.setattr("arrow_y2k.campaign.generate", forbid_generation)
    for index in range(5):
        assert store.load_slot(index).to_dict() == expected
    summaries = store.slots()
    assert len(summaries) == 5
    assert [item.slot for item in summaries] == list(range(5))
    assert all(item.left == item.total - 1 and item.level_index == 1 and item.lives == 3
               and item.difficulty == "medium" and item.mode == "medium" for item in summaries)
    assert "+" in summaries[0].saved_at or summaries[0].saved_at.endswith("Z")
    store.delete_slot(3)
    assert store.slots()[3] is None
    assert store.load_slot(0).to_dict() == expected


@pytest.mark.parametrize("field,value", [("max_length", 2.5), ("seed", []),
                                         ("turn_bias", float("nan")), ("density", True)])
def test_map_import_validates_generation_parameter_types(tmp_path, field, value):
    store = GameStore(tmp_path / "state")
    item = store.save_custom_map("模板", template_mask("square"), GenerateConfig(), "easy")
    path = tmp_path / "bad.json"
    store.export_custom_map(item.id, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["config"][field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DomainStorageError):
        store.import_custom_map(path)
    assert store.list_custom_maps() == [item]



def test_old_settings_load_with_color_mode_default_and_new_mode_round_trips(tmp_path):
    store = GameStore(tmp_path)
    store.settings.master_volume = .4
    store.save_settings()
    path = tmp_path / "settings.json"
    legacy = json.loads(path.read_text(encoding="utf-8"))
    del legacy["settings"]["monochrome"]
    path.write_text(json.dumps(legacy), encoding="utf-8")
    loaded = GameStore(tmp_path)
    assert not loaded.settings.monochrome and loaded.settings.master_volume == .4
    assert not loaded.warnings
    loaded.save_settings(replace(loaded.settings, monochrome=True))
    reopened = GameStore(tmp_path)
    assert reopened.settings.monochrome and reopened.settings.master_volume == .4


@pytest.mark.parametrize("invalid", [0, 1, "true", None])
def test_monochrome_setting_requires_a_real_boolean(invalid):
    with pytest.raises(DomainStorageError):
        Settings(monochrome=invalid).validate()


def test_candidate_settings_write_failure_preserves_active_settings_and_file(tmp_path, monkeypatch):
    store = GameStore(tmp_path)
    store.save_settings()
    active = store.settings
    path = tmp_path / "settings.json"
    before = path.read_bytes()
    def fail_replace(*args):
        raise OSError("settings locked")
    monkeypatch.setattr("arrow_y2k.storage.os.replace", fail_replace)
    with pytest.raises(DomainStorageError):
        store.save_settings(replace(active, monochrome=True, master_volume=.25))
    assert store.settings is active
    assert not store.settings.monochrome and store.settings.master_volume == .65
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))
