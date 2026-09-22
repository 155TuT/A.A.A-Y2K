"""Install/copy release payloads on disposable CI runners and run the real app."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import zipfile

from PIL import Image
from platformdirs import user_data_dir

from build_support import APP_NAME, ROOT, command, compare_reports, digest, target_name, write_json

REPORTS = ROOT / "build/reports"


def verify_executable(executable: Path, label: str, data_root: Path) -> dict:
    report = REPORTS / f"installed-{label}.json"
    report.unlink(missing_ok=True)
    command([str(executable), "--self-test", "--test-report", str(report)])
    parity = compare_reports(REPORTS / "source.json", report)
    screenshot = REPORTS / f"installed-{label}.png"
    screenshot.unlink(missing_ok=True)
    command([str(executable), "--data-dir", str(data_root), "--resolution", "1024x768",
             "--screenshot", str(screenshot), "--quit-after", "0.75"], timeout=60)
    with Image.open(screenshot) as frame:
        if frame.size != (1104, 916) or frame.mode != "RGBA":
            raise RuntimeError("Installed app did not render the expected CRT frame.")
        if len(frame.getcolors(maxcolors=2**24)) < 8 or frame.getpixel((0, 0))[3] != 0:
            raise RuntimeError("Installed app produced an empty or invalid frame.")
    return {**parity, "launch_and_shutdown": True, "screenshot_sha256": digest(screenshot)}


def verify_windows(package: Path, temporary: Path) -> dict:
    # An Inno installation also registers an uninstaller. Never replace a local
    # player's installed application just to smoke-test a release.
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Installer integration checks must run on a disposable GitHub runner.")
    installed = temporary / "installed"
    player = Path(user_data_dir("ArrowAfterArrowY2K", appauthor=False))
    player.mkdir(parents=True, exist_ok=True)
    marker = player / "installer-verification.txt"
    if marker.exists():
        raise RuntimeError("Refusing to overwrite an existing verification marker.")
    marker.write_text("preserve player data", encoding="utf-8")
    arguments = [str(package), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/NOICONS",
                 f"/DIR={installed}"]
    try:
        command([*arguments, f"/LOG={REPORTS / 'setup-install.log'}"])
        # Repeat an install over the same location to exercise upgrade file handling.
        command([*arguments, f"/LOG={REPORTS / 'setup-reinstall.log'}"])
        result = verify_executable(installed / f"{APP_NAME}.exe", "setup", temporary / "player")
    finally:
        uninstaller = installed / "unins000.exe"
        if uninstaller.exists():
            command([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                     f"/LOG={REPORTS / 'setup-uninstall.log'}"])
    for _ in range(50):
        if not (installed / f"{APP_NAME}.exe").exists():
            break
        time.sleep(0.1)
    if (installed / f"{APP_NAME}.exe").exists() or marker.read_text(encoding="utf-8") != "preserve player data":
        raise RuntimeError("Uninstall failed to remove the application or preserve player data.")
    marker.unlink()
    return {**result, "reinstall": True, "uninstall": True, "player_data_preserved": True}


def verify_macos(package: Path, temporary: Path) -> dict:
    if package.suffix == ".pkg":
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("PKG integration checks must run on a disposable GitHub runner.")
        installed = Path("/Applications") / f"{APP_NAME}.app"
        if installed.exists():
            raise RuntimeError(f"Refusing to replace an existing application: {installed}")
        command(["sudo", "installer", "-pkg", str(package), "-target", "/"])
        return {**verify_executable(installed / "Contents/MacOS" / APP_NAME, "pkg", temporary / "player"),
                "system_install": True}
    mounted = temporary / "mounted"
    mounted.mkdir()
    command(["hdiutil", "verify", str(package)])
    command(["hdiutil", "attach", str(package), "-readonly", "-nobrowse", "-mountpoint", str(mounted)])
    try:
        if not (mounted / "Applications").is_symlink():
            raise RuntimeError("DMG is missing its Applications installation shortcut.")
        installed = temporary / f"{APP_NAME}.app"
        command(["ditto", str(mounted / installed.name), str(installed)])
    finally:
        command(["hdiutil", "detach", str(mounted)])
    command(["codesign", "--verify", "--deep", "--strict", str(installed)])
    return {**verify_executable(installed / "Contents/MacOS" / APP_NAME, "dmg", temporary / "player"),
            "image_verified": True, "copied_from_image": True, "ad_hoc_signature_verified": True}


def verify_portable(package: Path, temporary: Path) -> dict:
    if sys.platform == "win32":
        with zipfile.ZipFile(package) as archive:
            archive.extractall(temporary)
        executable = temporary / APP_NAME / f"{APP_NAME}.exe"
    else:
        # unzip preserves the executable modes and symlinks recorded by build.py.
        command(["unzip", "-q", str(package), "-d", str(temporary)])
        executable = temporary / APP_NAME / APP_NAME
    return verify_executable(executable, "portable", temporary / "player")


def verify(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = {}
    for name, checksum in manifest["assets"].items():
        if Path(name).name != name:
            raise RuntimeError("Asset names must be plain filenames.")
        asset = manifest_path.parent / name
        if digest(asset) != checksum:
            raise RuntimeError(f"Asset changed before installation verification: {name}")
        with tempfile.TemporaryDirectory(prefix="aaa-install-") as directory:
            temporary = Path(directory)
            if asset.suffix == ".exe":
                result = verify_windows(asset, temporary)
            elif asset.suffix in (".pkg", ".dmg"):
                result = verify_macos(asset, temporary)
            else:
                result = verify_portable(asset, temporary)
        results[name] = {"successful": True, **result}
    manifest["install_verification"] = results
    write_json(REPORTS / "installation.json", {"target": manifest["target"], "assets": results})
    audit = manifest_path.with_name(manifest_path.name.replace("-manifest.json", "-verification.zip"))
    with zipfile.ZipFile(audit, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(REPORTS.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(REPORTS))
    manifest["verification_archive"] = {"name": audit.name, "sha256": digest(audit)}
    write_json(manifest_path, manifest)
    print(f"Verified installation and launch: {', '.join(results)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.manifest is None:
        paths = list((ROOT / "dist/release" / target_name()).glob("*-manifest.json"))
        if len(paths) != 1:
            parser.error("Expected exactly one manifest; pass --manifest explicitly.")
        args.manifest = paths[0]
    verify(args.manifest.resolve())
