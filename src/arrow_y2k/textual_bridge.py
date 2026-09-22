"""Version-bound Textual rendering and input adapter, independent of SDL.

Private Textual access for composition, pointer cancellation and lifecycle is
kept here so framework upgrades have one explicit compatibility boundary.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image, ImageDraw
from rich.cells import cell_len
from textual import events
from textual.geometry import Offset, Region
from textual.widgets import Button, Switch

from .fonts import CELL_HEIGHT, CELL_WIDTH, draw_text
from .palette import rgb

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget

BACKGROUND = rgb("host-surface")
FOREGROUND = rgb("host-text")


def app_context(app: App):
    return app._context()


def is_exiting(app: App) -> bool:
    return app._exit


def reset_pointer_state(app: App) -> None:
    if not app.screen_stack:
        return
    app._set_mouse_over(None, None)
    app.mouse_position = Offset(-1, -1)
    # Textual 6.12 retains the down target after MouseUp. Cancel that click too.
    app._mouse_down_widget = None
    app._click_chain_last_offset = app._click_chain_last_time = None
    app._chained_clicks = 1
    app.capture_mouse(None)
    app.screen.clear_selection()
    for widget in app.screen.query("Button, Switch"):
        widget.remove_class("-active")
    if isinstance(app.focused, (Button, Switch)):
        app.screen.set_focus(None)


def configure_native_colors(app: App) -> None:
    """The graphical display is RGB even if its launching terminal sets NO_COLOR."""
    from textual.filter import Monochrome, NoColor

    for line_filter in app.get_line_filters():
        if isinstance(line_filter, (Monochrome, NoColor)):
            line_filter.enabled = False
    app.no_color = False


def raster_point(event: events.MouseEvent, widget: Widget) -> tuple[int, int]:
    """Map a forwarded Textual mouse event to exact widget source pixels.

Textual preserves floating pointer coordinates while its normal ``x`` / ``y``
properties remain terminal cells. This avoids mutable global pointer state and
also survives Textual's MouseMove translation and MouseDown event cloning.
"""
    region = widget.content_region
    return (
        round(event.pointer_screen_x * CELL_WIDTH) - region.x * CELL_WIDTH,
        round(event.pointer_screen_y * CELL_HEIGHT) - region.y * CELL_HEIGHT,
    )


def mouse_message(
    kind: type[events.MouseEvent],
    point: tuple[int, int],
    *,
    button: int = 1,
    shift: bool = False,
    ctrl: bool = False,
    meta: bool = False,
) -> events.MouseEvent:
    """Create ordinary Textual input with lossless source-pixel coordinates."""
    x, y = point[0] / CELL_WIDTH, point[1] / CELL_HEIGHT
    return kind(None, x, y, 0, 0, button, shift, meta, ctrl, screen_x=x, screen_y=y)


def _color(color: object, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if color is None or getattr(color, "is_default", False):
        return fallback
    return tuple(color.get_truecolor())


def _textual_surface(app: App):
    """Single version-bound bridge to Textual's already-composed screen."""
    with app_context(app):
        compositor = app.screen._compositor
        strips = compositor.render_strips()
        visible = list(compositor.visible_widgets.items())
        overlays = []
        painted_regions = []
        # The base strips already contain ordinary controls. Once native art
        # replaces an area, later widgets that cover it must be restored in
        # the same painter order, including tooltip / Select popups. Render
        # their own complete lines so CJK glyphs survive compositor cuts at
        # the boundary of the underlying native button.
        for widget, (_, clip) in reversed(visible):
            if not widget.visible:
                continue
            renderer = getattr(widget, "native_frame", None)
            complete_overlay = getattr(widget, "native_complete_overlay", False)
            full_region = complete_overlay or getattr(widget, "native_full_region", False)
            region = widget.region if full_region or renderer is None else widget.content_region
            visible_region = region.intersection(clip)
            if not visible_region:
                continue
            restore_text = renderer is None and (
                complete_overlay or any(visible_region.overlaps(area) for area in painted_regions)
            )
            if renderer is None and not restore_text:
                continue
            width, height = region.width * CELL_WIDTH, region.height * CELL_HEIGHT
            if renderer is not None:
                art = renderer(width, height)
            else:
                lines = widget.render_lines(Region(0, 0, region.width, region.height))
                art = _rasterize_strips(lines, (width, height))
            overlays.append((region, clip, art))
            painted_regions.append(visible_region)
    return strips, overlays


def _rasterize_strips(strips, size: tuple[int, int]) -> Image.Image:
    """One shared path for Textual colours, glyphs, backgrounds and underline."""
    frame = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(frame)
    for row, strip in enumerate(strips):
        y = row * CELL_HEIGHT
        x = 0
        for segment in strip:
            if segment.control:
                continue
            width = cell_len(segment.text) * CELL_WIDTH
            style = segment.style
            foreground = _color(style.color if style else None, FOREGROUND)
            background = _color(style.bgcolor if style else None, BACKGROUND)
            if style and style.reverse:
                foreground, background = background, foreground
            if width:
                draw.rectangle((x, y, x + width - 1, y + CELL_HEIGHT - 1), fill=background)
                draw_text(frame, (x, y), segment.text, foreground)
                if style and style.underline:
                    draw.line((x, y + CELL_HEIGHT - 1, x + width - 1, y + CELL_HEIGHT - 1), fill=foreground)
            x += width

    return frame


def compose_frame(app: App, logical_size: tuple[int, int]) -> Image.Image:
    """Compose a native-resolution frame usable by any embedding host.

The real Textual compositor supplies every ordinary widget. Widgets may expose
``native_frame(width, height) -> PIL.Image`` for pixel art inside their content
region, or their full region when ``native_full_region`` is true. Ordinary
controls covering native art are restored in Textual painter order. All layers
are clipped to their Textual viewport.
"""
    strips, overlays = _textual_surface(app)
    frame = _rasterize_strips(strips, logical_size)

    # Compositor visible_widgets is front-to-back; overlay in painter order.
    for region, clip, art in overlays:
        width, height = region.width * CELL_WIDTH, region.height * CELL_HEIGHT
        if art.size != (width, height):
            raise ValueError("native_frame must return exactly its requested source-pixel size")
        visible_region = region.intersection(clip)
        if not visible_region:
            continue
        left = (visible_region.x - region.x) * CELL_WIDTH
        top = (visible_region.y - region.y) * CELL_HEIGHT
        cropped = art.crop((left, top, left + visible_region.width * CELL_WIDTH, top + visible_region.height * CELL_HEIGHT))
        frame.paste(cropped, (visible_region.x * CELL_WIDTH, visible_region.y * CELL_HEIGHT))
    return frame
