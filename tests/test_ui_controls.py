"""Input, state, and pixel-geometry regressions for the native Textual controls."""
import pytest
from PIL import Image, ImageChops
from textual.widgets import Button, Switch
from arrow_y2k.app import ArrowApp
from arrow_y2k.desktop import RESOLUTIONS, compose_frame, configure_native_colors
from arrow_y2k.icons import pixel_icon
from arrow_y2k.pixels import BACKGROUND, render_hearts
from arrow_y2k.widgets import PixelButton


def make_app(path):
    app = ArrowApp(native=True, data_dir=path, clock=lambda: 0.0, seed="controls")
    app.audio.play = lambda _: True
    app.host_action = lambda _: None
    configure_native_colors(app)
    return app


@pytest.mark.parametrize("name", ["play", "folder", "trophy", "map", "gear", "exit", "github", "heart"])
def test_icons_use_binary_integer_pixels_and_heart_matches_game(name):
    icon = pixel_icon(name)
    assert icon.mode == "RGBA"
    assert set(icon.getchannel("A").tobytes()) == {0, 255}
    assert len(icon.getcolors()) <= 8
    if name == "heart":
        background = Image.new("RGB", icon.size, BACKGROUND)
        background.paste(icon, (0, 0), icon)
        assert ImageChops.difference(background, render_hearts(1).crop((1, 1, 14, 12))).getbbox() is None


@pytest.mark.parametrize("resolution", list(RESOLUTIONS))
async def test_home_alignment_square_exit_and_icons_fit_each_resolution(tmp_path, resolution):
    app = make_app(tmp_path)
    preset = RESOLUTIONS[resolution]
    async with app.run_test(size=preset.terminal_size) as pilot:
        await pilot.pause()
        menu = app.screen.query_one("#home-menu")
        start, load = app.q("#new-game", PixelButton), app.q("#open-saves", PixelButton)
        assert start.region.x == menu.region.x
        assert load.region.right == menu.region.right
        assert start.region.right < load.region.x
        for name in ("open-achievements", "open-editor", "open-settings"):
            button = app.q("#" + name, PixelButton)
            assert (button.region.x, button.region.right) == (menu.region.x, menu.region.right)
        exit_button = app.q("#exit-desktop", PixelButton)
        github = app.q("#github", PixelButton)
        assert exit_button.region.x == menu.region.x
        assert github.region.right == menu.region.right
        assert exit_button.tooltip == "退出到桌面" and github.tooltip == "GitHub / 项目主页"
        assert app.focused is None
        frame = compose_frame(app, preset.logical_size)
        # The Fusion Pixel outline glyph is inset inside its terminal cells;
        # test visible ink rather than assume terminal cells are square.
        for button in (exit_button, github):
            region = button.region
            crop = frame.crop((region.x*6, region.y*12, region.right*6, region.bottom*12))
            color = button.styles.border_top[1].rgb
            points = [(x, y) for y in range(crop.height) for x in range(crop.width) if crop.getpixel((x, y)) == color]
            assert points
            xs, ys = zip(*points)
            assert max(xs)-min(xs) == max(ys)-min(ys)
        for widget in app.screen.query("Button"):
            assert app.screen.region.contains_region(widget.region)
