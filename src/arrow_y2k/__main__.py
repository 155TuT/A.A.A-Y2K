"""Run the native Textual pixel window, or opt into a normal terminal."""
import argparse
import asyncio


def main() -> None:
    parser = argparse.ArgumentParser(description="一箭又一箭 / Textual 像素解谜")
    parser.add_argument("--terminal", action="store_true", help="使用当前终端（显示精度由终端控制）")
    parser.add_argument("--resolution", choices=("1024x768", "1280x720", "1920x1080"), default="1280x720")
    parser.add_argument("--level", type=int, default=1)
    parser.add_argument("--seed", default="2026")
    parser.add_argument("--screenshot", help="保存真实窗口帧 PNG")
    parser.add_argument("--quit-after", type=float, help="验证时在指定秒数后关闭")
    args = parser.parse_args()
    from .app import ArrowApp
    app = ArrowApp(native=not args.terminal, level=args.level, seed=args.seed)
    app.resolution_name = args.resolution
    if args.terminal:
        app.run()
    else:
        from .desktop import run_desktop
        asyncio.run(run_desktop(app, resolution=args.resolution,
                                screenshot_path=args.screenshot, quit_after=args.quit_after))


if __name__ == "__main__":
    main()
