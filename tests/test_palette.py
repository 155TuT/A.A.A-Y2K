"""The CSS and native art must resolve the same semantic design tokens."""
from pathlib import Path
import re

from arrow_y2k import pixels
from arrow_y2k.app import ArrowApp
from arrow_y2k.icons import pixel_icon
from arrow_y2k.palette import TOKENS, css_variables, rgb
from arrow_y2k.widgets import PixelButton


def test_stylesheet_references_registered_semantic_colors_without_raw_hex():
    package = Path(pixels.__file__).parent
    css = (package / "game.tcss").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    references = set(re.findall(r"\$([\w-]+)", css))
    assert references and references <= css_variables().keys()
    assert all(name.startswith("aaa-") for name in references)
    for name in ("pages.py", "widgets.py", "icons.py", "pixels.py"):
        assert not re.search(r"#[0-9a-fA-F]{6}\b", (package / name).read_text(encoding="utf-8"))


def test_board_hearts_and_icon_materials_use_the_semantic_palette():
    assert pixels.BACKGROUND == rgb("surface")
    assert pixels.MINT == rgb("accent")
    assert pixels.WHITE == rgb("ink")
    assert pixels.RED == rgb("collision")
    assert pixels.HEART_RED == rgb("heart")
    assert pixels.HEART_SHADOW == rgb("heart-shadow")
    assert pixels.HEART_LIGHT == rgb("heart-light")
    colors = {rgb(name) for name in TOKENS}
    for name in ("play", "folder", "trophy", "map", "gear", "exit", "github", "heart"):
        icon = pixel_icon(name)
        assert all(pixel[:3] in colors for pixel in icon.get_flattened_data() if pixel[3])


async def test_textual_theme_injection_and_native_control_share_hover_color(tmp_path):
    app = ArrowApp(data_dir=tmp_path, clock=lambda: 0.0)
    variables = app.get_css_variables()
    assert all(variables[key] == value for key, value in css_variables().items())
    async with app.run_test(size=(106, 30)) as pilot:
        await pilot.hover("#open-settings", offset=(2, 1))
        await pilot.pause()
        button = app.screen.query_one("#open-settings", PixelButton)
        assert button.styles.background.rgb == rgb("surface-hover")
        assert button.styles.color.rgb == rgb("accent")
        assert button.styles.border_top[1].rgb == rgb("accent")
        image = button.native_frame(button.region.width * 6, button.region.height * 12)
        assert image.getpixel((1, 7)) == rgb("surface-hover")
        assert image.getpixel((0, 6)) == rgb("accent")
