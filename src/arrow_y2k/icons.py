"""Small, hand-drawn RGBA sprites on the same pixel lattice as the hearts."""
from functools import lru_cache
from PIL import Image, ImageDraw
from .pixels import MINT, WHITE, BACKGROUND, render_hearts

YELLOW = (210, 188, 111)
YELLOW_LIGHT = (246, 224, 153)
YELLOW_DARK = (111, 90, 49)
GRAY = (175, 190, 191)


@lru_cache(maxsize=12)
def pixel_icon(name):
    image = Image.new("RGBA", (12, 12))
    draw = ImageDraw.Draw(image)
    if name == "play":
        draw.polygon(((2, 1), (10, 6), (2, 11)), fill=(44, 98, 67))
        draw.polygon(((2, 1), (9, 6), (2, 10)), fill=MINT)
        draw.line(((2, 1), (7, 4)), fill=(189, 239, 201))
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
        draw.polygon(((0, 1), (3, 0), (7, 2), (11, 1), (11, 10), (8, 11), (4, 9), (0, 10)), fill=(104, 88, 60))
        draw.polygon(((1, 2), (3, 1), (7, 3), (10, 2), (10, 9), (8, 10), (4, 8), (1, 9)), fill=(219, 205, 160))
        draw.line(((4, 2), (4, 8)), fill=(183, 168, 130))
        draw.line(((7, 3), (7, 9)), fill=(183, 168, 130))
        draw.rectangle((2, 3, 3, 5), fill=(93, 137, 89))
        draw.rectangle((5, 5, 7, 6), fill=(93, 137, 89))
        draw.line(((8, 3), (8, 6), (9, 7), (9, 9)), fill=(98, 153, 166))
    elif name == "gear":
        draw.rectangle((4, 0, 7, 11), fill=(84, 102, 107))
        draw.rectangle((0, 4, 11, 7), fill=(84, 102, 107))
        draw.rectangle((2, 2, 9, 9), fill=GRAY)
        draw.rectangle((4, 1, 7, 10), fill=GRAY)
        draw.rectangle((1, 4, 10, 7), fill=GRAY)
        draw.line((2, 2, 7, 2), fill=(219, 228, 222))
        draw.rectangle((4, 4, 7, 7), fill=(45, 65, 65))
        draw.line((4, 7, 7, 7), fill=(225, 232, 229))
    elif name == "exit":
        draw.line(((5, 1), (1, 1), (1, 10), (5, 10)), fill=WHITE)
        draw.line((4, 5, 11, 5), fill=WHITE)
        draw.line(((8, 2), (11, 5), (8, 8)), fill=WHITE)
    elif name == "github":
        # Pixel silhouette of the familiar cat mark; no external image asset.
        draw.polygon(((1, 1), (4, 2), (7, 2), (10, 1), (10, 5), (11, 6), (10, 9), (8, 10), (8, 11), (4, 11), (4, 10), (2, 9), (1, 6)), fill=(204, 216, 208))
        draw.line(((0, 8), (1, 10), (4, 10)), fill=(204, 216, 208))
        draw.point((4, 6), fill=(64, 82, 75))
        draw.point((8, 6), fill=(64, 82, 75))
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
