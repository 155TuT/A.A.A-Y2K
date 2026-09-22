"""Source and frozen executables share the same launch and verification entrypoint."""
import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .display_config import RESOLUTIONS


def prepare_windowed_streams(data_dir: Path | None = None):
    """Supply missing GUI-process streams without replacing an existing console.

    Textual retains sys.__stdout__/sys.__stderr__, so all four names matter.
    The returned file stays open as the process's stream and is closed at exit.
    """
    missing = [name for name in ("stdout", "stderr", "__stdout__", "__stderr__")
               if getattr(sys, name) is None]
    if not missing:
        return None
    from .storage import user_data_root
    root = Path(data_dir) if data_dir is not None else user_data_root()
    root.mkdir(parents=True, exist_ok=True)
    stream = (root / "runtime.log").open("a", encoding="utf-8", buffering=1)
    for name in missing:
        setattr(sys, name, stream)
    return stream


def main():
    parser = argparse.ArgumentParser(description="ARROW.AFTER.ARROW-Y2K")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--resolution", choices=tuple(RESOLUTIONS))
    parser.add_argument("--seed", help="固定新游戏种子；默认每次新建使用新种子")
    parser.add_argument("--data-dir", type=Path, help="独立用户数据目录（测试或便携使用）")
    parser.add_argument("--screenshot", help="保存原生窗口显示帧")
    parser.add_argument("--quit-after", type=float, help="验证用自动退出秒数")
    parser.add_argument("--self-test", action="store_true", help="执行源码与二进制共用的行为验证套件")
    parser.add_argument("--test-report", help="写出验证 JSON 报告")
    args = parser.parse_args()
    if args.self_test:
        from .selftest import run_self_tests
        raise SystemExit(run_self_tests(args.test_report))
    prepare_windowed_streams(args.data_dir)
    from .app import ArrowApp
    app = ArrowApp(seed=args.seed, data_dir=args.data_dir)
    if args.resolution:
        app.resolution_name = args.resolution
        app.store.settings.resolution = args.resolution
    from .desktop import run_desktop
    asyncio.run(run_desktop(app, resolution=app.resolution_name,
                            screenshot_path=args.screenshot, quit_after=args.quit_after))


if __name__ == "__main__":
    main()
