"""Textual raster widgets. Both displays share the same pixel artwork and hit map."""
from __future__ import annotations

from PIL import Image
from rich.text import Text
from rich.style import Style
from textual import events
from textual.widget import Widget

from .pixels import render_board, render_hearts, render_mask_editor, hit_test, board_metrics

BG = "#10171b"


def half_blocks(image: Image.Image) -> Text:
    """One terminal cell carries two vertically adjacent square pixels."""
    image = image.convert("RGB")
    result = Text(no_wrap=True, overflow="crop")
    pixels = image.load()
    for y in range(0, image.height, 2):
        for x in range(image.width):
            top = pixels[x, y]
            bottom = pixels[x, min(y + 1, image.height - 1)]
            result.append("▀", Style(color="#%02x%02x%02x" % top,
                                     bgcolor="#%02x%02x%02x" % bottom))
        if y + 2 < image.height:
            result.append("\n")
    return result


class BoardView(Widget):
    can_focus = True

    def native_frame(self, width: int, height: int) -> Image.Image:
        game = self.app
        if game.editing:
            image = render_mask_editor(game.editor_mask, width=12, height=10,
                                       hover=game.editor_hover)
            scale = max(1, min(width // image.width, height // image.height))
            image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
            frame = Image.new("RGB", (width, height), BG)
            frame.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
            return frame
        return render_board(game.session.current_board, size=(width, height),
                            hovered=game.hovered, hint=game.hint_id,
                            animation=game.animation, cursor=game.cursor if self.has_focus else None,
                            red_ids=game.failed_ids)

    def render(self) -> Text:
        if self.app.native:
            return Text("")  # The desktop compositor uses native_frame at this widget's exact region.
        mask = frozenset((x, y) for y in range(10) for x in range(12)) if self.app.editing else self.app.session.board.mask
        geometry = board_metrics(max(1, self.size.width), max(2, self.size.height * 2), mask)
        if geometry.origin_x < 0 or geometry.origin_y < 0:
            return Text(f"终端空间不足\n\n棋盘需要至少 {geometry.image_width} 列 × {(geometry.image_height + 1) // 2} 行。\n请放大终端，或直接运行\npython run.py\n打开像素窗口。", style="#b2efc8")
        return half_blocks(self.native_frame(max(1, self.size.width), max(2, self.size.height * 2)))

    def cell_at(self, event: events.MouseEvent):
        if self.app.native:
            x = round(event.pointer_screen_x * 6) - self.content_region.x * 6
            y = round(event.pointer_screen_y * 12) - self.content_region.y * 12
            width, height = self.content_size.width * 6, self.content_size.height * 12
        else:
            x, y = int(event.x), int(event.y) * 2
            width, height = self.size.width, self.size.height * 2
        mask = frozenset((x, y) for y in range(10) for x in range(12)) if self.app.editing else self.app.session.board.mask
        geometry = board_metrics(max(1, width), max(1, height), mask)
        if not self.app.native and (geometry.origin_x < 0 or geometry.origin_y < 0):
            return None
        return hit_test(x, y, width, height, mask)

    def on_mouse_down(self, event: events.MouseDown) -> None:
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

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.app.painting = 0
        self.release_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        cell = self.cell_at(event)
        if self.app.editing:
            self.app.editor_hover = cell
            if self.app.painting:
                self.app.paint_cell(cell, erase=self.app.painting == 3)
        else:
            self.app.hovered = self.app.session.current_board.occupancy.get(cell)
        self.refresh()

    def on_leave(self) -> None:
        self.app.hovered = None
        self.app.editor_hover = None
        self.refresh()

    def on_key(self, event: events.Key) -> None:
        moves = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if event.key in moves:
            dx, dy = moves[event.key]
            mask = self.app.session.board.mask
            w, h = (12, 10) if self.app.editing else (max(x for x, y in mask) + 1, max(y for x, y in mask) + 1)
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


class HeartsView(Widget):
    def native_frame(self, width: int, height: int) -> Image.Image:
        import time
        before_impact = self.app.heart_started is not None and time.monotonic() < self.app.heart_started
        image = render_hearts(self.app.session.lives + int(before_impact),
                              progress=None if before_impact else self.app.heart_progress,
                              lost_index=None if before_impact else self.app.lost_index)
        board = self.app.query_one("#board")
        geometry = board_metrics(max(1, board.content_size.width * 6), max(1, board.content_size.height * 12),
                                 self.app.session.board.mask)
        scale = max(1, min(geometry.scale, width // image.width, height // image.height))
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
        frame = Image.new("RGB", (width, height), BG)
        frame.paste(image, (0, 0))
        return frame

    def render(self) -> Text:
        if self.app.native:
            return Text("")
        image = render_hearts(self.app.session.lives, progress=self.app.heart_progress,
                             lost_index=self.app.lost_index)
        # A compact textual-life presentation still uses the same outline bitmap.
        return half_blocks(image.resize((24, 12), Image.Resampling.NEAREST))
