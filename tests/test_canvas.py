"""Shared canvas bounds across editing, exchange, generation, and exact saves."""
from dataclasses import asdict
import json
import pytest

from arrow_y2k.canvas import CANVAS_WIDTH, CANVAS_HEIGHT, validate_canvas
from arrow_y2k.campaign import GameRun
from arrow_y2k.generation import GenerateConfig
from arrow_y2k.persistence import load_map, save_map
from arrow_y2k.storage import DomainStorageError, GameStore
from arrow_y2k.widgets import EDITOR_WIDTH, EDITOR_HEIGHT


def test_widget_and_run_canvas_share_dimensions():
    assert (EDITOR_WIDTH, EDITOR_HEIGHT) == (CANVAS_WIDTH, CANVAS_HEIGHT) == (20, 16)
    validate_canvas(((0, 0), (CANVAS_WIDTH - 1, CANVAS_HEIGHT - 1)))


@pytest.mark.parametrize("cell", [(20, 0), (0, 16), (-1, 0), (0, -1), (1.5, 0), (True, 0)])
def test_invalid_canvas_cannot_be_saved_imported_generated_or_restored(tmp_path, cell):
    store = GameStore(tmp_path / "state")
    config = GenerateConfig("bounds")
    good = store.save_custom_map("keep", frozenset({(0, 0)}), config, "easy")
    with pytest.raises((DomainStorageError, ValueError)):
        store.save_custom_map("invalid", frozenset({cell}), config, "easy")
    with pytest.raises(ValueError):
        GameRun.from_custom(frozenset({cell}), config, "easy")
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"schema_version": 1, "cells": [list(cell)],
                               "generation": asdict(config)}), encoding="utf-8")
    for load in (store.import_custom_map, load_map):
        with pytest.raises(ValueError):
            load(path)
    current = tmp_path / "current.json"
    store.export_custom_map(good.id, current)
    payload = json.loads(current.read_text(encoding="utf-8"))
    payload["mask"] = [list(cell)]
    current.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DomainStorageError):
        store.import_custom_map(current)
    snapshot = GameRun.from_custom(frozenset({(0, 0)}), config, "easy").to_dict()
    snapshot["board"]["mask"] = [list(cell)]
    with pytest.raises(ValueError):
        GameRun.from_dict(snapshot)
    assert store.list_custom_maps() == [good]


def test_legacy_and_current_maps_on_inclusive_boundary_remain_usable(tmp_path):
    mask = frozenset({(0, 0), (19, 15)})
    config = GenerateConfig("original boundary", 1, 7, 0.7)
    path = tmp_path / "legacy.json"
    save_map(path, mask, config)
    assert "cells" in json.loads(path.read_text(encoding="utf-8"))
    assert load_map(path) == (mask, config)
    store = GameStore(tmp_path / "state")
    imported = store.import_custom_map(path)
    assert (imported.mask, imported.config) == (mask, config)
    current = tmp_path / "current.json"
    store.export_custom_map(imported.id, current)
    assert load_map(current) == (mask, config)
    run = GameRun.from_custom(mask, config, "easy")
    assert GameRun.from_dict(run.to_dict()).to_dict() == run.to_dict()


def test_compatibility_module_delegates_to_single_storage_owner():
    from arrow_y2k import persistence, storage
    assert persistence.load_map is storage.load_map
    assert persistence.save_map is storage.save_map


@pytest.mark.parametrize("mode", ["medium", "hard"])
@pytest.mark.parametrize("tutorial", [False, True])
def test_non_easy_third_levels_never_receive_heart_tutorial(mode, tutorial):
    run = GameRun._level(mode, "shape-mismatch", 3, tutorial)
    assert "心形" not in run.description


def test_heart_guidance_only_appears_during_actual_easy_tutorial():
    assert "心形" in GameRun._level("easy", "guide", 3, True).description
    assert "心形" not in GameRun._level("easy", "guide", 3, False).description


@pytest.mark.parametrize("combo,bonus", [(0,3),(9,3),(10,4),(69,9),(70,10),(100,10)])
def test_combo_bonus_property_is_single_rule_entry(combo, bonus):
    run = GameRun.new("endless", "reward")
    run.combo = combo
    assert run.combo_bonus_seconds == bonus
