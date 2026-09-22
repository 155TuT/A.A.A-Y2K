"""Native pixel sprites and the official GitHub mark on the shared lattice."""
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw
from .pixels import MINT, WHITE, BACKGROUND, render_hearts
from .palette import rgb

YELLOW = rgb("warning")
YELLOW_LIGHT = rgb("warning-light")
YELLOW_DARK = rgb("icon-gold-shadow")
GRAY = rgb("icon-gear")


@lru_cache(maxsize=12)
def pixel_icon(name):
    image = Image.new("RGBA", (12, 12))
    draw = ImageDraw.Draw(image)
    if name == "play":
        draw.polygon(((2, 1), (10, 6), (2, 11)), fill=rgb("icon-play-shadow"))
        draw.polygon(((2, 1), (9, 6), (2, 10)), fill=MINT)
        draw.line(((2, 1), (7, 4)), fill=rgb("icon-play-light"))
    elif name == "folder":
        draw.rectangle((0, 2, 4, 8), fill=YELLOW_DARK)
        draw.rectangle((1, 2, 4, 4), fill=YELLOW_LIGHT)
        draw.rectangle((1, 4, 10, 10), fill=YELLOW_DARK)
        draw.rectangle((0, 5, 11, 9), fill=YELLOW)
        draw.line((0, 5, 11, 5), fill=YELLOW_LIGHT)
        draw.point((10, 9), fill=YELLOW_DARK)
    elif name == "trophy":
        draw.rectangle((0, 2, 11, 5), outline=YELLOW_DARK)
        draw.line((1, 2, 10, 2), fill=YELLOW_LIGHT)
        draw.rectangle((2, 1, 9, 5), fill=YELLOW)
        draw.line((2, 1, 9, 1), fill=YELLOW_LIGHT)
        draw.rectangle((3, 5, 8, 6), fill=YELLOW)
        draw.rectangle((5, 6, 6, 9), fill=YELLOW_DARK)
        draw.rectangle((3, 10, 8, 11), fill=YELLOW_DARK)
        draw.line((3, 10, 8, 10), fill=YELLOW)
        draw.line((3, 2, 3, 4), fill=YELLOW_LIGHT)
    elif name == "map":
        draw.polygon(((0, 1), (3, 0), (7, 2), (11, 1), (11, 10), (8, 11), (4, 9), (0, 10)), fill=rgb("icon-map-outline"))
        draw.polygon(((1, 2), (3, 1), (7, 3), (10, 2), (10, 9), (8, 10), (4, 8), (1, 9)), fill=rgb("icon-map-paper"))
        draw.line(((4, 2), (4, 8)), fill=rgb("icon-map-fold"))
        draw.line(((7, 3), (7, 9)), fill=rgb("icon-map-fold"))
        draw.rectangle((2, 3, 3, 5), fill=rgb("icon-map-land"))
        draw.rectangle((5, 5, 7, 6), fill=rgb("icon-map-land"))
        draw.line(((8, 3), (8, 6), (9, 7), (9, 9)), fill=rgb("icon-map-water"))
    elif name == "gear":
        draw.rectangle((4, 0, 7, 11), fill=rgb("icon-gear-shadow"))
        draw.rectangle((0, 4, 11, 7), fill=rgb("icon-gear-shadow"))
        draw.rectangle((2, 2, 9, 9), fill=GRAY)
        draw.rectangle((4, 1, 7, 10), fill=GRAY)
        draw.rectangle((1, 4, 10, 7), fill=GRAY)
        draw.line((2, 2, 7, 2), fill=rgb("icon-gear-light"))
        draw.rectangle((4, 4, 7, 7), fill=rgb("icon-gear-hole"))
        draw.line((4, 7, 7, 7), fill=rgb("icon-gear-edge"))
    elif name == "exit":
        draw.line(((5, 1), (1, 1), (1, 10), (5, 10)), fill=WHITE)
        draw.line((4, 5, 11, 5), fill=WHITE)
        draw.line(((8, 2), (11, 5), (8, 8)), fill=WHITE)
    elif name == "github":
        source = Path(__file__).parent / "assets" / "icons" / "github-invertocat-white.png"
        with Image.open(source) as original:
            mark = original.convert("RGBA")
            mark = mark.crop(mark.getbbox())
            # At 16 pixels the two narrow ear cutouts collapse into the head.
            # Twenty pixels retains them while sampling the official contour.
            mark.thumbnail((20, 20), Image.Resampling.LANCZOS)
        image = Image.new("RGBA", mark.size, (*rgb("brand-white"), 0))
        image.putalpha(mark.getchannel("A").point(lambda alpha: 255 if alpha >= 128 else 0))
    elif name == "heart":
        # Reuse the life renderer rather than maintain a second heart design.
        image = render_hearts(1).crop((1, 1, 14, 12)).convert("RGBA")
        for y in range(image.height):
            for x in range(image.width):
                if image.getpixel((x, y))[:3] == BACKGROUND:
                    image.putpixel((x, y), (0, 0, 0, 0))
    else:
        raise ValueError(f"Unknown pixel icon: {name}")
    return image
