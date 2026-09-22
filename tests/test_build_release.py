"""Adversarial checks for gates that decide which binaries may be published."""
import json
import stat
import subprocess
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
    monkeypatch.setattr(release, "source_snapshot", lambda root: {"source": "hash"})
    for target, suffixes in release.TARGETS.items():
        folder = tmp_path / target
        folder.mkdir()
        assets, verification = {}, {}
        for suffix in suffixes:
            name = f"{build_support.APP_NAME}-{build_support.VERSION}-{target}{suffix}"
            asset = folder / name
            asset.write_bytes(name.encode())
            assets[name] = build_support.digest(asset)
            verification[name] = {"successful": True, "source_frozen_parity": True,
                                  "launch_and_shutdown": True, "test_ids": ["a"]}
        audit = folder / f"{target}-verification.zip"
        audit.write_bytes(b"test evidence")
        build_support.write_json(folder / f"{target}-manifest.json", {
            "target": target, "version": build_support.VERSION, "commit": "commit", "dirty": False,
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


@pytest.mark.parametrize("draft", [True, False])
def test_release_lookup_finds_drafts_and_published_releases_across_pages(monkeypatch, draft):
    item = {"tag_name": "v0.4.0", "draft": draft, "assets": []}

    def api(arguments, **kwargs):
        assert arguments == ["gh", "api", "repos/owner/repo/releases?per_page=100", "--paginate", "--slurp"]
        assert kwargs["encoding"] == "utf-8"
        return subprocess.CompletedProcess(arguments, 0, json.dumps([[{"tag_name": "v0.3.0"}], [item]]), "")

    monkeypatch.setattr(release.subprocess, "run", api)
    assert release.github_release("owner/repo", "v0.4.0") == item
    assert release.github_release("owner/repo", "v9.0.0") is None


def test_release_lookup_does_not_treat_api_failure_as_a_missing_release(monkeypatch):
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 1, "", "HTTP 403: permission denied"))
    with pytest.raises(RuntimeError, match="403"):
        release.github_release("owner/repo", "v0.4.0")


def test_release_uses_original_checkout_metadata_and_hashes(release_matrix, tmp_path, monkeypatch):
    original = tmp_path / "original"
    package = original / "src/arrow_y2k"
    package.mkdir(parents=True)
    metadata = package / "__init__.py"
    metadata.write_text(f'APP_NAME = {build_support.APP_NAME!r}\n__version__ = {build_support.VERSION!r}\n')
    roots = []

    def snapshot(root):
        roots.append(root)
        return {"source": "hash"}

    monkeypatch.setattr(release, "source_snapshot", snapshot)
    assert len(release.collect_assets(release_matrix, "commit", source_root=original)) == 14
    assert roots == [original]
    metadata.write_text(f'APP_NAME = {build_support.APP_NAME!r}\n__version__ = "9.0.0"\n')
    with pytest.raises(RuntimeError, match="Version"):
        release.collect_assets(release_matrix, "commit", source_root=original)


def test_source_snapshot_reads_only_the_requested_checkout(tmp_path):
    for name in ("run.py", "pyproject.toml", ".gitattributes"):
        (tmp_path / name).write_text(name)
    package = tmp_path / "src/arrow_y2k"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.0.1'")
    snapshot = build_support.source_snapshot(tmp_path)
    assert set(snapshot) == {"run.py", "pyproject.toml", ".gitattributes", "src/arrow_y2k/__init__.py"}
    assert snapshot["run.py"] == build_support.digest(tmp_path / "run.py")


@pytest.mark.parametrize("fault", [None, "commit", "status", "path", "missing_job", "failed_job"])
def test_resume_requires_the_original_run_and_all_native_installation_jobs(monkeypatch, fault):
    run = {"head_sha": "commit", "status": "completed", "path": ".github/workflows/build.yml"}
    jobs = [{"name": f"Build and install ({target})", "conclusion": "success"} for target in release.TARGETS]
    if fault == "commit":
        run["head_sha"] = "different"
    elif fault in ("status", "path"):
        run[fault] = "wrong"
    elif fault == "missing_job":
        jobs.pop()
    elif fault == "failed_job":
        jobs[0]["conclusion"] = "failure"
    monkeypatch.setattr(release, "github_api", lambda endpoint, **kw:
                        [{"jobs": jobs}] if "/jobs?" in endpoint else run)
    if fault:
        with pytest.raises(RuntimeError):
            release.validate_source_run("owner/repo", 1, "commit")
    else:
        release.validate_source_run("owner/repo", 1, "commit")


@pytest.mark.parametrize("state", ["new", "draft", "public", "missing_after_upload", "bad_digest"])
def test_publish_checks_uploaded_draft_before_making_it_public(release_matrix, monkeypatch, state):
    calls, lookups = [], []
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(release.subprocess, "check_output", lambda *a, **k: "commit\n")
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, "commit\n", ""))
    monkeypatch.setattr(release, "command", lambda args: calls.append(args))

    def remote(repo, tag):
        lookups.append(tag)
        if len(lookups) == 1:
            return None if state == "new" else {"draft": state != "public"}
        if state == "missing_after_upload":
            return None
        paths = release.collect_assets(release_matrix, "commit") + [release_matrix / "SHA256SUMS.txt"]
        assets = [{"name": path.name, "size": path.stat().st_size,
                   "digest": f"sha256:{build_support.digest(path)}"} for path in paths]
        if state == "bad_digest":
            assets[0]["digest"] = "sha256:wrong"
        return {"draft": True, "assets": assets}

    monkeypatch.setattr(release, "github_release", remote)
    if state in ("public", "missing_after_upload", "bad_digest"):
        with pytest.raises(RuntimeError):
            release.publish(release_matrix)
        assert not any("--draft=false" in call for call in calls)
        if state == "public":
            assert not calls
    else:
        release.publish(release_matrix)
        assert "--draft=false" in calls[-1]
        assert any(call[2] == "create" for call in calls) == (state == "new")
