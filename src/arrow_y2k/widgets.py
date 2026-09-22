"""Textual input adapters composed with native integer-pixel renderers."""
from PIL import Image, ImageDraw
from rich.text import Text
from rich.cells import cell_len
from textual.widgets import Button, Select, Static
from textual.containers import Horizontal
from textual.geometry import Region
from .icons import pixel_icon
from .palette import rgb
from textual import events
from textual.widget import Widget
from .pixels import (render_board, render_hearts, render_mask_editor, hit_test,
                     board_metrics, Animation, BACKGROUND, MINT)
from .fonts import draw_text
from .canvas import CANVAS_WIDTH as EDITOR_WIDTH, CANVAS_HEIGHT as EDITOR_HEIGHT


class RasterView(Widget):
    ALLOW_SELECT = False
    def native_frame(self, width, height):
        raise NotImplementedError

    def render(self):
        return Text("")


def text_art(label, color):
    """Visible glyph bounds, independent of the font's baseline padding."""
    frame = Image.new("RGBA", (max(1, cell_len(label) * 6), 12))
    draw_text(frame, (0, 0), label, color)
    bounds = frame.getbbox()
    return frame.crop(bounds) if bounds else Image.new("RGBA", (0, 0))



def rectangle_face(widget, width, height):
    """One outline/background policy for all native interactive controls."""
    frame = Image.new("RGB", (width, height), BACKGROUND)
    inset = min(6, max(0, (height - 20) // 2))
    ImageDraw.Draw(frame).rectangle((0, inset, width - 1, height - inset - 1),
                                   fill=widget.styles.background.rgb,
                                   outline=widget.styles.border_top[1].rgb)
    return frame


class ControlFace:
    """Compose pixel chrome around Textual's unchanged cursor/text/slider."""
    def __init__(self, widget):
        self.widget = widget

    def __call__(self, width, height):
        from .desktop import _rasterize_strips
        widget = self.widget
        frame = rectangle_face(widget, width, height)
        region = widget.region
        content = widget.content_region
        lines = widget.render_lines(Region(0, 0, region.width, region.height))
        surface = _rasterize_strips(lines, (width, height))
        left = (content.x - region.x) * 6
        top = (content.y - region.y) * 12
        bounds = (left, top, left + content.width * 6, top + content.height * 12)
        frame.paste(surface.crop(bounds), (left, top))
        return frame


def attach_control_face(widget):
    widget.native_full_region = True
    widget.native_frame = ControlFace(widget)


class PixelButton(Button):
    """Keep Textual input/focus; compose one pixel-exact button face."""
    native_full_region = True

    def __init__(self, label, *, icon=None, icon_only=False, **kwargs):
        super().__init__(label, **kwargs)
        self.icon = icon
        self.icon_only = icon_only
        self.active_effect_duration = 0
        if icon_only:
            self.add_class("icon-only")
            self.tooltip = label

    def native_frame(self, width, height):
        # Vertical layout gutters stay page-colored. Hover only fills the
        # interior of the actual outline, equally inset by one source pixel.
        frame = rectangle_face(self, width, height)
        draw = ImageDraw.Draw(frame)
        label = "" if self.icon_only else self.label.plain
        text = text_art(label, self.styles.color.rgb)
        art = pixel_icon(self.icon) if self.icon else None
        if art is not None:
            art = art.crop(art.getbbox())
        gap = 6 if art is not None and label else 0
        group_width = text.width + (art.width if art else 0) + gap
        left = (width - group_width) // 2
        if art is not None:
            frame.paste(art, (left, (height - art.height) // 2), art)
            left += art.width + gap
        if label:
            frame.paste(text, (left, (height - text.height) // 2), text)
        if self.has_class("header-home"):
            draw.line((0, height - 1, width - 1, height - 1), fill=rgb("border-separator"))
        return frame

    def render(self):
        return Text("")


class HeaderTitle(RasterView):
    def __init__(self, title, **kwargs):
        super().__init__(**kwargs)
        self.title = title

    def native_frame(self, width, height):
        frame = Image.new("RGB", (width, height), BACKGROUND)
        art = text_art(self.title, MINT)
        frame.paste(art, (0, (height - art.height) // 2), art)
        ImageDraw.Draw(frame).line((0, height - 1, width - 1, height - 1), fill=rgb("border-separator"))
        return frame


class PageHeader(Horizontal):
    """One shared, compact home action and vertically centered page title."""
    def __init__(self, title):
        super().__init__(classes="page-header")
        self.title = title

    def compose(self):
        yield HeaderTitle(self.title, classes="page-title")
        yield PixelButton("返回主页", icon="exit", classes="danger header-home", id="go-home")

    def native_frame(self, width, height):
        frame = Image.new("RGB", (width, height), BACKGROUND)
        ImageDraw.Draw(frame).line((0, height - 1, width - 1, height - 1), fill=rgb("border-separator"))
        return frame


class DisclosureArt:
    """A tiny renderer composed into the existing Select disclosure widget."""
    def __init__(self, widget):
        self.widget = widget

    def __call__(self, width, height):
        frame = Image.new("RGB", (width, height), rgb("surface-field"))
        draw = ImageDraw.Draw(frame)
        center = height // 2
        for x in (width // 2 - 6, width // 2, width // 2 + 6):
            draw.ellipse((x - 1, center - 1, x + 1, center + 1), fill=self.widget.styles.color.rgb)
        return frame


class PixelSelect(Select):
    """Keep Select's keyboard/popup behavior, replace only its disclosure glyph."""
    def on_mount(self):
        for current in self.query("SelectCurrent, SelectOverlay"):
            attach_control_face(current)
        for arrow in self.query(".arrow"):
            arrow.update("•••")
            arrow.native_frame = DisclosureArt(arrow)


class CreditsView(RasterView):
    PREFIX = "Made By 155TuT with GPT and "
    SUFFIX = " Love"

    def native_frame(self, width, height):
        frame = Image.new("RGB", (width, height), BACKGROUND)
        left = max(0, (width - (len(self.PREFIX + self.SUFFIX) * 6 + 13)) // 2)
        top = max(0, (height - 12) // 2)
        color = rgb("text-credit")
        draw_text(frame, (left, top), self.PREFIX, color)
        left += len(self.PREFIX) * 6
        heart = pixel_icon("heart")
        frame.paste(heart, (left, top), heart)
        draw_text(frame, (left + heart.width, top), self.SUFFIX, color)
        return frame


class TitleView(RasterView):
    TEXT = "ARROW.AFTER.ARROW-Y2K"

    def native_frame(self, width, height):
        image = Image.new("RGB", (len(self.TEXT) * 6, 12), BACKGROUND)
        draw_text(image, (0, 0), self.TEXT, MINT)
        scale = min(2, max(1, width // image.width))
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
        frame = Image.new("RGB", (width, height), BACKGROUND)
        frame.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
        return frame


class BoardView(RasterView):
    can_focus = True

    @property
    def mask(self):
        if self.app.editing:
            return frozenset((x, y) for y in range(EDITOR_HEIGHT) for x in range(EDITOR_WIDTH))
        return self.app.session.board.mask

    def native_frame(self, width, height):
        app = self.app
        if app.editing:
            image = render_mask_editor(app.editor_mask, width=EDITOR_WIDTH, height=EDITOR_HEIGHT, hover=app.editor_hover)
            geometry = board_metrics(width, height, self.mask)
            if geometry.scale != 1:
                image = image.resize((image.width * geometry.scale, image.height * geometry.scale), Image.Resampling.NEAREST)
            frame = Image.new("RGB", (width, height), BACKGROUND)
            frame.paste(image, (geometry.origin_x, geometry.origin_y))
            return frame
        animations = app.effects.animations
        if app.store.settings.reduced_motion:
            animations = tuple(Animation(item.arrow, item.kind,
                               1.0 if item.kind == "exit" or item.progress >= .30 else 0.0,
                               item.collision_distance) for item in animations)
        return render_board(app.session.current_board, size=(width, height), hovered=app.hovered,
                            hint=app.hint_id, animations=animations,
                            cursor=app.cursor if self.has_focus else None, red_ids=app.failed_ids)

    def cell_at(self, event):
        x = round(event.pointer_screen_x * 6) - self.content_region.x * 6
        y = round(event.pointer_screen_y * 12) - self.content_region.y * 12
        width, height = self.content_size.width * 6, self.content_size.height * 12
        geometry = board_metrics(max(1, width), max(1, height), self.mask)
        if geometry.origin_x < 0 or geometry.origin_y < 0:
            return None
        return hit_test(x, y, width, height, self.mask)

    def on_mouse_down(self, event: events.MouseDown):
        if event.button not in (1, 3):
            return
        event.stop()
        self.focus()
        cell = self.cell_at(event)
        if self.app.editing:
            self.app.paint_cell(cell, erase=event.button == 3)
            self.app.painting = event.button
            self.capture_mouse()
        elif cell is not None:
            self.app.click_cell(cell)

    def on_mouse_up(self, event: events.MouseUp):
        self.app.painting = 0
        self.release_mouse()

    def on_mouse_move(self, event: events.MouseMove):
        cell = self.cell_at(event)
        if self.app.editing:
            self.app.editor_hover = cell
            if self.app.painting:
                self.app.paint_cell(cell, erase=self.app.painting == 3)
        else:
            self.app.hovered = self.app.session.current_board.occupancy.get(cell)
        self.refresh()

    def on_leave(self):
        self.app.hovered = self.app.editor_hover = None
        self.refresh()

    def on_key(self, event: events.Key):
        moves = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if event.key in moves:
            dx, dy = moves[event.key]
            w = max(x for x, y in self.mask) + 1
            h = max(y for x, y in self.mask) + 1
            x, y = self.app.cursor
            self.app.cursor = (max(0, min(w - 1, x + dx)), max(0, min(h - 1, y + dy)))
            if self.app.editing:
                self.app.editor_hover = self.app.cursor
            event.stop()
            self.refresh()
        elif event.key in ("enter", "space"):
            if self.app.editing:
                self.app.paint_cell(self.app.cursor, erase=self.app.cursor in self.app.editor_mask)
            else:
                self.app.click_cell(self.app.cursor)
            event.stop()


class SaveHearts(RasterView):
    def __init__(self, lives=0, *, centered=False, **kwargs):
        super().__init__(**kwargs)
        self.lives = lives
        self.centered = centered

    def art(self):
        return render_hearts(self.lives)

    def zoom(self, width, height):
        return 1

    def native_frame(self, width, height):
        image = self.art()
        scale = max(1, min(self.zoom(width, height), width // image.width, height // image.height))
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
        frame = Image.new("RGB", (width, height), BACKGROUND)
        left = max(0, (width - image.width) // 2) if self.centered else 0
        frame.paste(image, (left, max(0, (height - image.height) // 2)))
        return frame


class HeartsView(SaveHearts):
    def art(self):
        app = self.app
        damage = app.effects.heart_frames
        if app.store.settings.reduced_motion:
            damage = {index: 1.0 if progress >= 0 else progress for index, progress in damage.items()}
        return render_hearts(app.session.lives, damage=damage)

    def zoom(self, width, height):
        board = self.app.screen.query_one("#board")
        return board_metrics(max(1, board.content_size.width * 6), max(1, board.content_size.height * 12),
                             self.app.session.board.mask).scale
