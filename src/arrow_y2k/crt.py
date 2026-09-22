"""A cached CRT enclosure composed around the existing pixel framebuffer.

All geometry and effects use the same logical pixel lattice as Textual. The
final integer enlargement is nearest-neighbour. Glass curvature is confined
to the outermost few pixels; the actual content and its hit positions stay put.
"""
from __future__ import annotations

from math import floor
from random import Random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .fonts import draw_text
from .palette import rgb

SHUTDOWN_SHAKE_SECONDS = .30
SHUTDOWN_DURATION = 1.30
GLASS = rgb("crt-glass")
CASE = rgb("crt-case")
CASE_LIGHT = rgb("crt-case-light")
CASE_SHADOW = rgb("crt-case-shadow")
LED_YELLOW = rgb("crt-led-yellow")
LED_RED = rgb("crt-led-red")


def shutdown_phase(elapsed: float | None) -> str:
    if elapsed is None:
        return "on"
    if elapsed < SHUTDOWN_SHAKE_SECONDS:
        return "unstable"
    if elapsed < SHUTDOWN_DURATION:
        return "no_signal"
    return "off"


class CrtShell:
    """Warm plastic enclosure, glass sampling, controls and presentation only.

    ``content_size`` is the requested *physical* inner-screen size. ``frame``
    passed to render is its logical size (content_size divided by scale).
    Geometry APIs receive / return physical coordinates relative to the outer
    window, except input_point's returned logical source-pixel coordinate.
    """
    MARGIN_X = 20
    MARGIN_TOP = 20
    MARGIN_BOTTOM = 54

    def __init__(self, content_size: tuple[int, int], scale: int):
        if scale < 1 or int(scale) != scale or any(value <= 0 or value % scale for value in content_size):
            raise ValueError("CRT screen dimensions must be positive integer multiples of scale")
        self.content_size = tuple(content_size)
        self.scale = int(scale)
        self.logical_size = tuple(value // scale for value in content_size)
        width, height = self.logical_size
        self._size = (width + 2 * self.MARGIN_X, height + self.MARGIN_TOP + self.MARGIN_BOTTOM)
        self.outer_size = tuple(value * scale for value in self._size)
        self.viewport = (self.MARGIN_X * scale, self.MARGIN_TOP * scale, *content_size)
        self._outer_mask = Image.new("L", self._size)
        ImageDraw.Draw(self._outer_mask).rounded_rectangle(
            (0, 0, self._size[0] - 1, self._size[1] - 1), radius=7, fill=255)
        self.outer_mask = self._outer_mask.resize(self.outer_size, Image.Resampling.NEAREST)
        self._glass_mask = Image.new("L", self.logical_size)
        ImageDraw.Draw(self._glass_mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=3, fill=255)
        self._controls = self._control_geometry()
        self.control_rects = {name: tuple(value * scale for value in bounds)
                              for name, bounds in self._controls.items()}
        self.indicator_centers = tuple((x * scale, y * scale) for x, y in self._indicator_centers())
        self._scanlines, self._noise, self._reflection = self._make_filters()
        self._case = self._make_case()
        self._case_mono = self._make_case(monochrome=True)
        self._no_signal = Image.new("RGB", self.logical_size, GLASS)
        draw_text(self._no_signal, ((width - 9 * 6) // 2, (height - 12) // 2),
                  "NO SIGNAL", (159, 180, 169))
        self._off = Image.new("RGB", self.logical_size, GLASS)

    def _control_geometry(self):
        width, height = self._size
        return {"menu": (width - 129, height - 29, 17, 7),
                "minus": (width - 101, height - 29, 17, 7),
                "plus": (width - 73, height - 29, 17, 7),
                "power": (width - 41, height - 35, 19, 19)}

    def _indicator_centers(self):
        _, height = self._size
        return ((29, height - 26), (43, height - 26))

    def input_point(self, point: tuple[int, int]) -> tuple[int, int] | None:
        left, top, width, height = self.viewport
        x, y = point
        if not (left <= x < left + width and top <= y < top + height):
            return None
        px, py = floor((x - left) / self.scale), floor((y - top) / self.scale)
        if not self._glass_mask.getpixel((px, py)):
            return None
        return px, py

    def contains_screen(self, point: tuple[int, int]) -> bool:
        return self.input_point(point) is not None

    def forward_point(self, point: tuple[int, int]) -> tuple[int, int] | None:
        """Map a logical content pixel to its physical centre, without warping."""
        width, height = self.logical_size
        x, y = map(int, point)
        if not (0 <= x < width and 0 <= y < height) or not self._glass_mask.getpixel((x, y)):
            return None
        return (self.viewport[0] + x * self.scale + self.scale // 2,
                self.viewport[1] + y * self.scale + self.scale // 2)

    def control_at(self, point: tuple[int, int]) -> str | None:
        px, py = point
        for name, (x, y, width, height) in self.control_rects.items():
            if x <= px < x + width and y <= py < y + height:
                return name
        return None

    def _make_filters(self):
        width, height = self.logical_size
        scanlines = Image.new("RGB", self.logical_size, (255, 255, 255))
        draw = ImageDraw.Draw(scanlines)
        for y in range(1, height, 2):
            draw.line((0, y, width - 1, y), fill=(246, 246, 246))
        random = Random(404)
        noise = []
        for _ in range(4):
            grain = Image.frombytes("L", self.logical_size, random.randbytes(width * height))
            grain = grain.point([0] * 220 + [1] * 31 + [2] * 5).convert("RGB")
            noise.append(grain)
        reflection = Image.new("RGB", self.logical_size)
        draw = ImageDraw.Draw(reflection)
        draw.polygon(((0, 0), (width * .55, 0), (0, height * .8)), fill=(1, 2, 2))
        reflection = reflection.filter(ImageFilter.GaussianBlur(8))
        edge = ImageDraw.Draw(reflection)
        edge.line((4, 0, width - 5, 0), fill=(2, 7, 4))
        edge.line((2, 1, width - 3, 1), fill=(1, 3, 2))
        edge.line((0, 4, 0, height - 5), fill=(1, 5, 3))
        edge.line((width - 1, 4, width - 1, height - 5), fill=(0, 3, 2))
        edge.line((4, height - 1, width - 5, height - 1), fill=(1, 4, 2))
        return scanlines, tuple(noise), reflection

    def _make_case(self, monochrome=False):
        width, height = self._size
        screen_width, screen_height = self.logical_size
        def glass_color(color):
            if not monochrome:
                return color
            value = round(.299 * color[0] + .587 * color[1] + .114 * color[2])
            return (value, value, value)
        frame = Image.new("RGB", self._size, (91, 94, 86))
        draw = ImageDraw.Draw(frame)
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=7,
                               fill=(146, 148, 133), outline=(73, 77, 70))
        draw.polygon(((6, 2), (width - 8, 2), (width - 14, 9), (13, 9),
                      (9, 13), (9, height - 14), (2, height - 8), (2, 7)), fill=CASE_LIGHT)
        draw.polygon(((width - 3, 7), (width - 3, height - 8), (width - 9, height - 3),
                      (8, height - 3), (14, height - 10), (width - 11, height - 10),
                      (width - 10, 13)), fill=CASE_SHADOW)
        draw.rounded_rectangle((8, 8, width - 11, height - 11), radius=5, fill=CASE)
        draw.line((12, 8, width - 14, 8), fill=(245, 242, 221))
        draw.line((8, 13, 8, height - 15), fill=(224, 223, 202))
        # Screen light only touches the adjacent plastic / black inner lip.
        # It is static and low intensity: no breathing glow or full-frame warp.
        glow = Image.new("RGBA", self._size)
        ImageDraw.Draw(glow).rounded_rectangle(
            (self.MARGIN_X - 5, self.MARGIN_TOP - 5,
             self.MARGIN_X + screen_width + 4, self.MARGIN_TOP + screen_height + 4),
            radius=7, outline=(*glass_color((45, 143, 88)), 70), width=3)
        glow = glow.filter(ImageFilter.GaussianBlur(4))
        frame.paste(glow, (0, 0), glow)
        draw = ImageDraw.Draw(frame)
        # A recessed glass surround, including the tiny rounded glass corners.
        glass_bounds = (self.MARGIN_X - 7, self.MARGIN_TOP - 7,
                        self.MARGIN_X + screen_width + 6, self.MARGIN_TOP + screen_height + 6)
        draw.rounded_rectangle(glass_bounds, radius=9, fill=glass_color((76, 80, 73)),
                               outline=glass_color((137, 139, 123)))
        draw.rounded_rectangle((glass_bounds[0] + 2, glass_bounds[1] + 2,
                               glass_bounds[2] - 1, glass_bounds[3] - 1), radius=8,
                              fill=glass_color((11, 26, 23)), outline=glass_color((35, 54, 42)))
        draw.rounded_rectangle((self.MARGIN_X - 2, self.MARGIN_TOP - 2,
                                self.MARGIN_X + screen_width + 1, self.MARGIN_TOP + screen_height + 1),
                               radius=5, outline=glass_color((38, 77, 51)))
        draw.line((20, height - 47, width - 22, height - 47), fill=(165, 168, 148))
        draw.line((20, height - 46, width - 22, height - 46), fill=(221, 220, 198))
        draw_text(frame, (57, height - 33), "A.A.A / Y2K", (132, 138, 121))
        for name in self._controls:
            self._draw_control(frame, name, False)
        for index in range(2):
            self._draw_indicator(frame, index, False)
        # Thin grille slots terminate before the controls and do not compete
        # with the actual game. Their tiny upper lip gives the plastic depth.
        for x in range(width - 192, width - 145, 6):
            draw.line((x, height - 31, x, height - 22), fill=(143, 149, 129))
            draw.line((x + 1, height - 31, x + 1, height - 22), fill=(219, 218, 194))
        return frame

    def _draw_control(self, frame, name, pressed):
        x, y, width, height = self._controls[name]
        draw = ImageDraw.Draw(frame)
        bounds = (x, y, x + width - 1, y + height - 1)
        draw.rounded_rectangle(bounds, radius=2, fill=(107, 113, 99), outline=(153, 158, 137))
        if pressed:
            face = (x + 2, y + 2, x + width - 3, y + height - 2)
            draw.rounded_rectangle(face, radius=1, fill=(162, 168, 146))
            draw.line((x + 2, y + 2, x + width - 3, y + 2), fill=(118, 126, 108))
        else:
            face = (x + 1, y + 1, x + width - 3, y + height - 3)
            draw.rounded_rectangle(face, radius=1, fill=(210, 211, 188))
            draw.line((x + 2, y + 1, x + width - 4, y + 1), fill=(242, 239, 217))
        if name == "power":
            # A two-pixel cut-through mark, centred on the visible face rather
            # than on its asymmetric bevel / outer button bounds.
            mark = Image.new("L", (12, 13))
            cut = ImageDraw.Draw(mark)
            cut.arc((0, 1, 11, 12), 310, 590, fill=255, width=2)
            cut.rectangle((5, 0, 6, 6), fill=255)
            left = face[0] + ((face[2] - face[0] + 1) - mark.width) // 2
            top = face[1] + ((face[3] - face[1] + 1) - mark.height) // 2
            recess = Image.new("L", (mark.width + 2, mark.height + 2))
            recess.paste(mark, (1, 1))
            recess = recess.filter(ImageFilter.MaxFilter(3))
            frame.paste((88, 91, 66), (left - 1, top - 1, left + mark.width + 1, top + mark.height + 1), recess)
            frame.paste(LED_YELLOW, (left, top, left + mark.width, top + mark.height), mark)
            shifted = Image.new("L", mark.size)
            shifted.paste(mark, (0, 1))
            upper_edge = ImageChops.subtract(mark, shifted)
            frame.paste((255, 239, 161), (left, top, left + mark.width, top + mark.height), upper_edge)
        else:
            label_y = y - 13
            draw_text(frame, (x + (width - 6) // 2, label_y),
                      {"menu": "M", "minus": "-", "plus": "+"}[name], (129, 137, 119))

    def _draw_indicator(self, frame, index, active):
        x, y = self._indicator_centers()[index]
        draw = ImageDraw.Draw(frame)
        draw.rectangle((x - 4, y - 3, x + 4, y + 3), fill=(151, 155, 135))
        draw.rectangle((x - 3, y - 2, x + 3, y + 2), fill=(62, 73, 57))
        color = (LED_YELLOW if index == 0 else LED_RED) if active else ((103, 97, 51) if index == 0 else (91, 55, 46))
        draw.rectangle((x - 2, y - 1, x + 2, y + 1), fill=color)
        if active:
            draw.line((x - 1, y - 1, x + 1, y - 1), fill=(255, 242, 171) if index == 0 else (255, 149, 110))

    def indicator_states(self, elapsed, *, reduced_motion=False, shutdown_elapsed=None):
        phase = shutdown_phase(shutdown_elapsed)
        if phase == "off":
            return False, False
        if phase != "on":
            return False, True
        if reduced_motion:
            return True, False
        elapsed = max(0, elapsed)
        return elapsed % 1.1 < .52, (elapsed + .27) % 1.7 < .16

    def _screen(self, frame, elapsed, shutdown_elapsed, reduced_motion, monochrome=False):
        phase = shutdown_phase(shutdown_elapsed)
        if phase == "off":
            content = self._off
        elif phase == "no_signal":
            content = self._no_signal
        elif phase == "unstable" and not reduced_motion:
            step = int(max(0, shutdown_elapsed) / .05)
            content = Image.new("RGB", self.logical_size, GLASS)
            content.paste(frame, ((0, 1, -2, 2, -1, 0)[step % 6], step % 2))
            if step % 2:
                content = Image.blend(content, self._off, .40)
        else:
            content = frame
        if phase != "off":
            content = ImageChops.multiply(content, self._scanlines)
            grain = self._noise[0 if reduced_motion else int(max(0, elapsed) * 12) % len(self._noise)]
            content = ImageChops.add(content, grain)
            content = ImageChops.add(content, self._reflection)
        glass = Image.new("RGB", self.logical_size, GLASS)
        glass.paste(content, (0, 0), self._glass_mask)
        # Convert after every screen overlay so glyphs, hearts, tooltips,
        # reflections and the NO SIGNAL card all obey the same mode.
        return ImageOps.grayscale(glass).convert("RGB") if monochrome else glass

    def render(self, frame: Image.Image, elapsed: float, pressed: str | None = None,
               shutdown_elapsed: float | None = None, reduced_motion: bool = False,
               monochrome: bool = False) -> Image.Image:
        if frame.size != self.logical_size:
            raise ValueError("CRT content must match the configured logical framebuffer size")
        if frame.mode != "RGB":
            frame = frame.convert("RGB")
        output = (self._case_mono if monochrome else self._case).copy()
        output.paste(self._screen(frame, elapsed, shutdown_elapsed, reduced_motion, monochrome),
                     (self.MARGIN_X, self.MARGIN_TOP))
        if pressed in self._controls:
            self._draw_control(output, pressed, True)
        for index, active in enumerate(self.indicator_states(elapsed, reduced_motion=reduced_motion,
                                                             shutdown_elapsed=shutdown_elapsed)):
            self._draw_indicator(output, index, active)
        output = output.convert("RGBA")
        output.putalpha(self._outer_mask)
        return output.resize(self.outer_size, Image.Resampling.NEAREST)
