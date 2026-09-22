# One onedir recipe for the installed Windows app, macOS bundle and Linux archive.
from pathlib import Path
import runpy
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
metadata = runpy.run_path(str(root / "src" / "arrow_y2k" / "__init__.py"))
name, version = metadata["APP_NAME"], metadata["__version__"]
sys.path.insert(0, str(root / "src"))
datas = [
    (str(root / "src/arrow_y2k/game.tcss"), "arrow_y2k"),
    (str(root / "src/arrow_y2k/assets"), "arrow_y2k/assets"),
]
datas += collect_data_files("textual") + copy_metadata("textual", recursive=True)
for dependency in ("arrow-y2k", "pygame-ce", "Pillow", "platformdirs"):
    datas += copy_metadata(dependency)

analysis = Analysis(
    [str(root / "run.py")], pathex=[str(root / "src")], datas=datas,
    hiddenimports=collect_submodules("arrow_y2k") + collect_submodules("textual"),
    excludes=["pytest", "ruff"],
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name=name,
    console=False, upx=False, strip=False,
)
collection = COLLECT(executable, analysis.binaries, analysis.datas, name=name, upx=False, strip=False)
if sys.platform == "darwin":
    app = BUNDLE(
        collection, name=name + ".app", bundle_identifier="io.github.155tut.arrow-y2k",
        version=version,
        info_plist={"CFBundleShortVersionString": version, "NSHighResolutionCapable": True},
    )
