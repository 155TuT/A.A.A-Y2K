"""Build on the current OS, then compare source and frozen shared contracts.

Usage:
    python tools/build.py
    python tools/build.py --onefile
    python tools/build.py --compare source.json frozen.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import stat
import zipfile
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "A.A.A-Y2K"


def compare_reports(source_path: Path, frozen_path: Path) -> dict:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if source.get("frozen") is not False or frozen.get("frozen") is not True:
        raise RuntimeError("Reports must identify one source run and one frozen run.")
    for report in (source, frozen):
        if report.get("suite") != "arrow_y2k.shared_contract" or not report.get("successful"):
            raise RuntimeError("Both shared-contract runs must pass.")
        tests = report.get("tests", [])
        identifiers = [case["id"] for case in tests]
        if not tests or len(set(identifiers)) != len(identifiers) or len(tests) != report["tests_run"]:
            raise RuntimeError("The report has missing or duplicate test IDs.")
        if any(case["status"] != "passed" for case in tests):
            raise RuntimeError("No skipped, failed or errored test may pass the release gate.")
    signature = lambda report: sorted((case["id"], case["status"]) for case in report["tests"])
    if signature(source) != signature(frozen):
        raise RuntimeError("Source and frozen test IDs/results differ.")
    return {"suite": source["suite"], "tests_run": source["tests_run"],
            "source_frozen_parity": True, "test_ids": [case["id"] for case in source["tests"]]}


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as content:
        for chunk in iter(lambda: content.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def source_snapshot() -> dict[str, str]:
    files = [ROOT / "run.py", ROOT / "pyproject.toml", ROOT / "tools" / "build.py"]
    files.extend(path for path in (ROOT / "src" / "arrow_y2k").rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    return {str(path.relative_to(ROOT)).replace(os.sep, "/"): digest(path) for path in sorted(files)}


def archive_distribution(distribution: Path, target: Path) -> Path:
    """Preserve executable modes and symlinks in macOS .app / Linux bundles."""
    paths = [distribution]
    if distribution.is_dir():
        paths.extend(sorted(distribution.rglob("*")))
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in paths:
            name = path.relative_to(distribution.parent).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, os.readlink(path))
            else:
                archive.write(path, name)
    return target


def command(arguments: list[str], *, timeout: int = 900) -> None:
    # Pass an argument array: filenames and report paths never become shell code.
    print("+ " + subprocess.list2cmdline(arguments), flush=True)
    subprocess.run(arguments, cwd=ROOT, check=True, timeout=timeout)


def build(*, onefile: bool = False, console: bool = False) -> Path:
    snapshot = source_snapshot()
    reports = ROOT / "build" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    source_report, frozen_report = reports / "source.json", reports / "frozen.json"
    command([sys.executable, str(ROOT / "run.py"), "--self-test", "--test-report", str(source_report)])
    options = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--noupx",
        "--onefile" if onefile else "--onedir",
        "--console" if console else "--windowed",
        "--name", APP_NAME, "--paths", str(ROOT / "src"),
        "--specpath", str(ROOT / "build" / "spec"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--distpath", str(ROOT / "dist"),
        "--collect-submodules", "arrow_y2k",
        "--collect-submodules", "textual",
        "--collect-data", "textual",
        "--recursive-copy-metadata", "textual",
        "--copy-metadata", "pygame-ce",
        "--copy-metadata", "Pillow",
        "--copy-metadata", "platformdirs",
        "--add-data", str(ROOT / "src" / "arrow_y2k" / "game.tcss") + ":arrow_y2k",
        "--add-data", str(ROOT / "src" / "arrow_y2k" / "assets") + ":arrow_y2k/assets",
        "--exclude-module", "pytest",
        str(ROOT / "run.py"),
    ]
    command(options)
    suffix = ".exe" if sys.platform == "win32" else ""
    if sys.platform == "darwin" and not console:
        distribution = ROOT / "dist" / f"{APP_NAME}.app"
        executable = distribution / "Contents" / "MacOS" / APP_NAME
    elif onefile:
        distribution = ROOT / "dist" / f"{APP_NAME}{suffix}"
        executable = distribution
    else:
        distribution = ROOT / "dist" / APP_NAME
        executable = distribution / f"{APP_NAME}{suffix}"
    if not executable.is_file():
        raise RuntimeError(f"Build did not produce the expected executable: {executable}")
    command([str(executable), "--self-test", "--test-report", str(frozen_report)])
    parity = compare_reports(source_report, frozen_report)
    if source_snapshot() != snapshot:
        raise RuntimeError("Source files changed during the build. Re-run after edits are complete.")
    archive_stem = ROOT / "dist" / f"{APP_NAME}-{platform.system().lower()}-{platform.machine().lower()}"
    archive = archive_distribution(distribution, Path(str(archive_stem) + ".zip"))
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version.split()[0],
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("pyinstaller", "textual", "pygame-ce", "Pillow", "platformdirs")},
        "executable": str(executable.relative_to(ROOT)).replace(os.sep, "/"),
        "executable_sha256": digest(executable),
        "archive": archive.name, "archive_sha256": digest(archive),
        "source_files_sha256": snapshot, **parity,
    }
    (ROOT / "dist" / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {parity['tests_run']} identical source/frozen tests. Archive: {archive}")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onefile", action="store_true", help="Bundle one executable instead of the default portable folder.")
    parser.add_argument("--console", action="store_true", help="Keep a console for development diagnostics.")
    parser.add_argument("--compare", nargs=2, metavar=("SOURCE_REPORT", "FROZEN_REPORT"))
    args = parser.parse_args()
    if args.compare:
        result = compare_reports(*(Path(value) for value in args.compare))
        print(json.dumps(result, indent=2))
    else:
        build(onefile=args.onefile, console=args.console)


if __name__ == "__main__":
    main()
