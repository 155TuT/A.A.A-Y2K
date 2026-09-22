"""Build and verify an onedir bundle; --installer wraps it in native installers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import zipfile

from build_support import (APP_NAME, ROOT, VERSION, command, compare_reports, digest,
                           source_snapshot, target_name, write_json)
from installers import build_installers, inno_compiler


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


def validate_version() -> None:
    installed = importlib.metadata.version("arrow-y2k")
    if installed != VERSION:
        raise RuntimeError(f"Installed metadata is {installed}, source is {VERSION}. Reinstall the project.")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME") != f"v{VERSION}":
        raise RuntimeError("Release tag must match the source version.")


def build(*, installer: bool = False) -> Path:
    validate_version()
    target = target_name()
    if installer and sys.platform == "win32":
        if target != "windows-x64":
            raise RuntimeError("The Windows installer currently requires an x64 Python runtime.")
        inno_compiler()
    snapshot = source_snapshot()
    reports = ROOT / "build/reports"
    reports.mkdir(parents=True, exist_ok=True)
    source_report, frozen_report = reports / "source.json", reports / "frozen.json"
    source_report.unlink(missing_ok=True)
    frozen_report.unlink(missing_ok=True)
    command([sys.executable, str(ROOT / "run.py"), "--self-test", "--test-report", str(source_report)])
    command([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--workpath", str(ROOT / "build/pyinstaller"), "--distpath", str(ROOT / "dist"),
             str(ROOT / "packaging/arrow_y2k.spec")])
    distribution = ROOT / "dist" / (APP_NAME + (".app" if sys.platform == "darwin" else ""))
    executable = (distribution / "Contents/MacOS" / APP_NAME if sys.platform == "darwin" else
                  distribution / (APP_NAME + (".exe" if sys.platform == "win32" else "")))
    if not executable.is_file():
        raise RuntimeError(f"Build did not produce the expected executable: {executable}")
    command([str(executable), "--self-test", "--test-report", str(frozen_report)])
    parity = compare_reports(source_report, frozen_report)
    output = ROOT / "dist/release" / target
    output.mkdir(parents=True, exist_ok=True)
    stem = f"{APP_NAME}-{VERSION}-{target}"
    assets = (build_installers(distribution, output, stem) if installer else
              [archive_distribution(distribution, output / (stem + "-portable.zip"))])
    if source_snapshot() != snapshot:
        raise RuntimeError("Source files changed during the build. Re-run after edits are complete.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    manifest = {
        "schema_version": 2, "version": VERSION, "target": target, "commit": commit, "dirty": dirty,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version.split()[0],
        "dependencies": {item.metadata["Name"]: item.version for item in importlib.metadata.distributions()},
        "executable": executable.relative_to(ROOT).as_posix(), "executable_sha256": digest(executable),
        "assets": {path.name: digest(path) for path in assets}, "install_verification": {},
        "source_files_sha256": snapshot, **parity,
    }
    path = output / (stem + "-manifest.json")
    write_json(path, manifest)
    print(f"Verified {parity['tests_run']} source/frozen tests. Manifest: {path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", action="store_true", help="Create Windows Setup or macOS PKG and DMG.")
    parser.add_argument("--validate-version", action="store_true")
    parser.add_argument("--compare", nargs=2, metavar=("SOURCE_REPORT", "FROZEN_REPORT"))
    args = parser.parse_args()
    if args.compare:
        print(json.dumps(compare_reports(*(Path(value) for value in args.compare)), indent=2))
    elif args.validate_version:
        validate_version()
        print(VERSION)
    else:
        build(installer=args.installer)


if __name__ == "__main__":
    main()
