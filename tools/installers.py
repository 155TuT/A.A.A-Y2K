"""Native installation formats around an already verified onedir distribution."""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile

from build_support import APP_NAME, BUNDLE_ID, ROOT, VERSION, command


def inno_compiler() -> Path:
    candidates = [os.environ.get("ISCC", ""), shutil.which("ISCC.exe") or ""]
    candidates += [str(Path(os.environ.get(key, "C:/Program Files (x86)")) / "Inno Setup 6/ISCC.exe")
                   for key in ("ProgramFiles(x86)", "ProgramFiles")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("Inno Setup 6 is required. Install it or set ISCC to the compiler path.")


def build_installers(distribution: Path, output: Path, stem: str) -> list[Path]:
    if sys.platform == "win32":
        filename = stem + "-Setup"
        command([str(inno_compiler()), f"/DAppVersion={VERSION}",
                 f"/DSourceDir={distribution}", f"/DOutputDir={output}",
                 f"/DOutputName={filename}", str(ROOT / "packaging/windows.iss")])
        return [output / (filename + ".exe")]
    if sys.platform == "darwin":
        package, image = output / (stem + ".pkg"), output / (stem + ".dmg")
        with tempfile.TemporaryDirectory(prefix="pkg-", dir=ROOT / "build") as temporary:
            stage = Path(temporary)
            payload = stage / "payload"
            command(["ditto", str(distribution), str(payload / "Applications" / distribution.name)])
            components = stage / "components.plist"
            # Disable relocation: a build-tree copy with the same bundle ID
            # must never redirect installation away from /Applications.
            components.write_bytes(plistlib.dumps([{
                "RootRelativeBundlePath": f"Applications/{distribution.name}",
                "BundleIsRelocatable": False, "BundleIsVersionChecked": True,
                "BundleHasStrictIdentifier": True, "BundleOverwriteAction": "upgrade",
            }]))
            command(["pkgbuild", "--root", str(payload), "--component-plist", str(components),
                     "--install-location", "/", "--identifier", BUNDLE_ID, "--version", VERSION,
                     str(package)])
        with tempfile.TemporaryDirectory(prefix="dmg-", dir=ROOT / "build") as temporary:
            stage = Path(temporary)
            command(["ditto", str(distribution), str(stage / distribution.name)])
            (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
            (stage / "Install.txt").write_text(
                f"Drag {APP_NAME}.app to Applications.\n"
                "Alternatively, use the matching .pkg installer from the release.\n"
                "This release is ad-hoc signed, without Apple notarization.\n", encoding="utf-8")
            command(["hdiutil", "create", "-volname", f"{APP_NAME} {VERSION}", "-srcfolder", str(stage),
                     "-ov", "-format", "UDZO", str(image)])
        return [package, image]
    raise RuntimeError("Installers are supported on Windows and macOS; use the Linux portable archive.")
