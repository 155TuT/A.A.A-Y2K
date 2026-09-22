"""Textual input adapters composed with native integer-pixel renderers."""
from PIL import Image, ImageDraw
from rich.text import Text
from rich.cells import cell_len
from textual.widgets import Button, Select, Static
from .icons import pixel_icon
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


class PixelButton(Button):
    """Textual keeps input and accessibility; a sprite decorates its content."""
    def __init__(self, label, *, icon=None, icon_only=False, **kwargs):
        super().__init__(label, **kwargs)
        self.icon = icon
        self.icon_only = icon_only
        self.active_effect_duration = 0
        if icon_only:
            self.add_class("icon-only")
            self.tooltip = label

    def native_frame(self, width, height):
        background = self.styles.background.rgb
        frame = Image.new("RGB", (width, height), background)
        label = "" if self.icon_only else self.label.plain
        label_width = cell_len(label) * 6
        art_width = 12 if self.icon else 0
        gap = 6 if self.icon and label else 0
        left = max(0, (width - label_width - art_width - gap) // 2)
        top = max(0, (height - 12) // 2)
        if self.icon:
            art = pixel_icon(self.icon)
            frame.paste(art, (left, top), art)
        draw_text(frame, (left + art_width + gap, top), label, self.styles.color.rgb)
        return frame

    def render(self):
        return Text("")


class DisclosureArt:
    """A tiny renderer composed into the existing Select disclosure widget."""
    def __init__(self, widget):
        self.widget = widget

    def __call__(self, width, height):
        frame = Image.new("RGB", (width, height), (21, 35, 29))
        draw = ImageDraw.Draw(frame)
        center = height // 2
        for x in (width // 2 - 6, width // 2, width // 2 + 6):
            draw.ellipse((x - 1, center - 1, x + 1, center + 1), fill=self.widget.styles.color.rgb)
        return frame


class PixelSelect(Select):
    """Keep Select's keyboard/popup behavior, replace only its disclosure glyph."""
    def on_mount(self):
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
        color = (102, 132, 116)
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
