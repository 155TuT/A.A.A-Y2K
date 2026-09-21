"""The one font/raster policy: 12 source pixels, binary coverage, integer scaling.

Fusion Pixel's monospaced 12 px face has 6 px Latin and 12 px CJK advances,
matching Textual's one- and two-cell character widths exactly.
"""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.cells import cell_len

CELL_WIDTH = 6
CELL_HEIGHT = 12
FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "fusion-pixel-12px-monospaced-zh_hans.ttf"


@lru_cache(maxsize=1)
def pixel_font() -> ImageFont.FreeTypeFont:
    """Load the bundled, unmodified OFL face at its native pixel size."""
    return ImageFont.truetype(str(FONT_PATH), CELL_HEIGHT)


@lru_cache(maxsize=2048)
def glyph_mask(character: str) -> Image.Image:
    """Return a binary mask; no gray antialias pixels can enter the framebuffer."""
    width = max(1, cell_len(character)) * CELL_WIDTH
    mask = Image.new("1", (width, CELL_HEIGHT))
    ImageDraw.Draw(mask).text((0, 0), character, font=pixel_font(), fill=1)
    return mask


def draw_text(
    image: Image.Image,
    position: tuple[int, int],
    text: str,
    color: tuple[int, int, int],
) -> None:
    """Draw Textual-width text on the same source-pixel lattice as game art."""
    x, y = position
    for character in text:
        width = cell_len(character) * CELL_WIDTH
        if width == 0:
            continue
        if character != " ":
            image.paste(color, (x, y), glyph_mask(character))
        x += width
