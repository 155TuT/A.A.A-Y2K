"""Adversarial checks for gates that decide which binaries may be published."""
import json
import stat
import zipfile

import pytest

import build
import build_support
import release


def test_source_and_binary_reports_require_identical_passing_cases(tmp_path):
    source, binary = tmp_path / "source.json", tmp_path / "frozen.json"
    report = {"suite": "arrow_y2k.shared_contract", "app_version": build_support.VERSION,
              "successful": True, "tests_run": 1, "tests": [{"id": "a", "status": "passed"}]}
    build_support.write_json(source, {**report, "frozen": False})
    build_support.write_json(binary, {**report, "frozen": True})
    assert build_support.compare_reports(source, binary)["source_frozen_parity"]
    for changes in (
        {"successful": False}, {"tests": [{"id": "a", "status": "skipped"}]},
        {"tests": [{"id": "different", "status": "passed"}]}, {"tests_run": 2},
        {"app_version": "0.0.0"}, {"frozen": False}, {"tests": []},
        {"tests_run": 2, "tests": [{"id": "a", "status": "passed"}] * 2},
    ):
        build_support.write_json(binary, {**report, "frozen": True, **changes})
        with pytest.raises(RuntimeError):
            build_support.compare_reports(source, binary)


def test_tag_must_match_source_and_installed_version(monkeypatch):
    monkeypatch.setattr(build.importlib.metadata, "version", lambda _: build_support.VERSION)
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v0.0.0")
    with pytest.raises(RuntimeError, match="tag"):
        build.validate_version()
    monkeypatch.setenv("GITHUB_REF_NAME", "v" + build_support.VERSION)
    build.validate_version()
    monkeypatch.setattr(build.importlib.metadata, "version", lambda _: "0.0.0")
    with pytest.raises(RuntimeError, match="Reinstall"):
        build.validate_version()


def test_archive_retains_executable_permission_and_symlink(tmp_path):
    folder = tmp_path / "app"
    folder.mkdir()
    executable = folder / "game"
    executable.write_bytes(b"test executable")
    executable.chmod(0o755)
    link = folder / "link"
    try:
        link.symlink_to("game")
    except OSError:
        link = None  # Non-developer-mode Windows may lack symlink privilege.
    archive_path = build.archive_distribution(folder, tmp_path / "app.zip")
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("app/game") == b"test executable"
        assert archive.getinfo("app/game").external_attr >> 16 == executable.stat().st_mode
        if link is not None:
            assert stat.S_ISLNK(archive.getinfo("app/link").external_attr >> 16)
            assert archive.read("app/link") == b"game"


@pytest.fixture
def release_matrix(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "source_snapshot", lambda: {"source": "hash"})
    for target, suffixes in release.TARGETS.items():
        folder = tmp_path / target
        folder.mkdir()
        assets, verification = {}, {}
        for suffix in suffixes:
            name = f"{release.APP_NAME}-{release.VERSION}-{target}{suffix}"
            asset = folder / name
            asset.write_bytes(name.encode())
            assets[name] = build_support.digest(asset)
            verification[name] = {"successful": True, "source_frozen_parity": True,
                                  "launch_and_shutdown": True, "test_ids": ["a"]}
        audit = folder / f"{target}-verification.zip"
        audit.write_bytes(b"test evidence")
        build_support.write_json(folder / f"{target}-manifest.json", {
            "target": target, "version": release.VERSION, "commit": "commit", "dirty": False,
            "source_files_sha256": {"source": "hash"}, "source_frozen_parity": True,
            "test_ids": ["a"], "tests_run": 1, "assets": assets, "install_verification": verification,
            "verification_archive": {"name": audit.name, "sha256": build_support.digest(audit)},
        })
    return tmp_path


def test_release_accepts_only_complete_verified_matrix(release_matrix):
    assert len(release.collect_assets(release_matrix, "commit")) == 14


@pytest.mark.parametrize("corruption", ["missing_target", "dirty", "commit", "version", "source",
                                       "asset_hash", "installation", "test_inventory", "missing_installer"])
def test_release_rejects_incomplete_or_mixed_artifacts(release_matrix, corruption):
    path = release_matrix / "windows-x64/windows-x64-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "missing_target":
        path.unlink()
    else:
        if corruption == "dirty":
            manifest["dirty"] = True
        elif corruption in ("commit", "version"):
            manifest[corruption] = "wrong"
        elif corruption == "source":
            manifest["source_files_sha256"] = {"old": "hash"}
        elif corruption == "asset_hash":
            manifest["assets"][next(iter(manifest["assets"]))] = "wrong"
        elif corruption == "installation":
            manifest["install_verification"][next(iter(manifest["assets"]))]["successful"] = False
        elif corruption == "test_inventory":
            manifest["test_ids"] = ["other"]
        elif corruption == "missing_installer":
            manifest["assets"] = {}
        build_support.write_json(path, manifest)
    with pytest.raises(RuntimeError):
        release.collect_assets(release_matrix, "commit")
