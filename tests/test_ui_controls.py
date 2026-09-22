"""Input, state, and pixel-geometry regressions for the native Textual controls."""
import pytest
from PIL import Image, ImageChops
from textual.widgets import Button, Switch
from arrow_y2k.app import ArrowApp
from arrow_y2k.desktop import RESOLUTIONS, compose_frame, configure_native_colors
from arrow_y2k.icons import pixel_icon
from arrow_y2k.pixels import BACKGROUND, render_hearts
from arrow_y2k.widgets import PixelButton, PixelSelect


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


async def test_settings_active_tab_does_not_leave_basic_focused_or_hovered(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        await pilot.click("#open-settings", offset=(2, 1))
        await pilot.pause()
        await pilot.hover("#settings-basic")
        await pilot.click("#settings-video", offset=(2, 1))
        await pilot.pause()
        basic, video = app.q("#settings-basic", Button), app.q("#settings-video", Button)
        assert not basic.has_class("selected") and not basic.has_focus and not basic.mouse_hover
        assert video.has_class("selected")
        select = app.q("#cfg-resolution", PixelSelect)
        arrows = select.query(".arrow")
        assert len(arrows) == 2
        for arrow in arrows:
            assert str(arrow.render()) == "•••"
            image = arrow.native_frame(18, 12)
            colored_columns = [x for x in range(18) if any(image.getpixel((x, y)) == arrow.styles.color.rgb for y in range(12))]
            assert colored_columns == [2, 3, 4, 8, 9, 10, 14, 15, 16]
        await pilot.click("#cfg-resolution", offset=(2, 1))
        await pilot.pause()
        assert select.expanded
        await pilot.press("down", "enter")
        assert select.value == "1920x1080"


async def test_switch_focus_keeps_outline_and_button_presses_have_no_gate(tmp_path):
    app = make_app(tmp_path)
    played = []
    app.audio.play = played.append
    async with app.run_test(size=(106, 30)) as pilot:
        app.route("settings")
        await pilot.pause()
        switch = app.q("#cfg-autosave", Switch)
        assert switch.value
        await pilot.click("#cfg-autosave", offset=(2, 1))
        await pilot.pause()
        assert not switch.value and switch._slider_position == 0
        frame = compose_frame(app, (640, 360))
        r = switch.region
        color = switch.styles.border_left[1].rgb
        # Both vertical lines must survive the focus/press state.
        left = [(x, y) for x in range(r.x*6, (r.x+1)*6) for y in range((r.y+1)*12, (r.y+2)*12) if frame.getpixel((x, y)) == color]
        right = [(x, y) for x in range((r.right-1)*6, r.right*6) for y in range((r.y+1)*12, (r.y+2)*12) if frame.getpixel((x, y)) == color]
        assert left and right
        app.dispatch("settings-audio")
        await pilot.pause()
        preview = app.q("#audio-preview", Button)
        assert preview.active_effect_duration == 0
        preview.press()
        preview.press()
        await pilot.pause()
        assert len(played) == 2
        assert not preview.has_class("-active")


async def test_game_text_selection_is_disabled_without_disabling_inputs(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(106, 30)) as pilot:
        app.start_game("easy")
        await pilot.pause()
        assert not app.screen.allow_select
        assert not app.screen.query_one("#board").allow_select
        await pilot.triple_click("#stats", offset=(2, 0))
        await pilot.triple_click("#board", offset=(1, 1))
        await pilot.pause()
        assert not app.screen.selections
        app.route("settings")
        await pilot.pause()
        field = app.screen.query_one("#cfg-save-minutes")
        field.focus()
        await pilot.press("ctrl+shift+a", "5")
        assert field.value == "5"
