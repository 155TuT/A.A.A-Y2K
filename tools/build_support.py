"""Shared release metadata, hashing and source/frozen verification gates."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
METADATA = runpy.run_path(str(ROOT / "src" / "arrow_y2k" / "__init__.py"))
APP_NAME = METADATA["APP_NAME"]
VERSION = METADATA["__version__"]
BUNDLE_ID = "io.github.155tut.arrow-y2k"


def target_name() -> str:
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower())
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}[platform.system()]
    return f"{system}-{arch}"


def command(arguments: list[str], *, timeout: int = 900, **kwargs) -> None:
    print("+ " + subprocess.list2cmdline([str(item) for item in arguments]), flush=True)
    subprocess.run(arguments, cwd=ROOT, check=True, timeout=timeout, **kwargs)


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as content:
        for chunk in iter(lambda: content.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_snapshot() -> dict[str, str]:
    files = [ROOT / "run.py", ROOT / "pyproject.toml", ROOT / ".gitattributes"]
    for directory in ("src/arrow_y2k", "tools", "packaging", ".github/workflows"):
        files.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(files)}


def compare_reports(source_path: Path, frozen_path: Path) -> dict:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if source.get("frozen") is not False or frozen.get("frozen") is not True:
        raise RuntimeError("Reports must identify one source run and one frozen run.")
    for report in (source, frozen):
        if report.get("suite") != "arrow_y2k.shared_contract" or report.get("successful") is not True:
            raise RuntimeError("Both shared-contract runs must pass.")
        tests = report.get("tests", [])
        identifiers = [case["id"] for case in tests]
        if not tests or len(set(identifiers)) != len(identifiers) or len(tests) != report["tests_run"]:
            raise RuntimeError("The report has missing or duplicate test IDs.")
        if any(case["status"] != "passed" for case in tests):
            raise RuntimeError("No skipped, failed or errored test may pass the release gate.")
    source_cases = sorted((case["id"], case["status"]) for case in source["tests"])
    frozen_cases = sorted((case["id"], case["status"]) for case in frozen["tests"])
    if source_cases != frozen_cases:
        raise RuntimeError("Source and frozen test IDs/results differ.")
    if source.get("app_version") != VERSION or frozen.get("app_version") != VERSION:
        raise RuntimeError("Source and frozen reports must match the release version.")
    return {"suite": source["suite"], "tests_run": source["tests_run"],
            "source_frozen_parity": True, "test_ids": [case["id"] for case in source["tests"]]}
