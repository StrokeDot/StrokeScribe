"""The Line order window: the order of the drawing (lines) and of the painting (parts).

Drawing tab: the lines in the order the pen draws them.
Painting tab: the parts in the order the brush paints them (Painter paint mode).

* Click a line or part on the picture to select it; click it again to unselect it.
  Drag a box to select everything inside it. The list works too.
* Selected items are orange with their number; the others are coloured by when
  they come (blue = first, red = last).
* Move the selected items together, to the start, up, down, to the end or to a place.
* Automatic orders, Default (the order it had when it came in), and Play.
* Drawing tab: Reverse, Delete, Pace and Pause for the selected lines.
Nothing changes in the project until "Use this order" (one undo step).
"""
from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

ACCENT = QColor(255, 122, 26)
PAINT_AUTO = (
    ('Big parts first, details last', 'The default: the biggest parts first, then smaller ones, details last.'),
    ('Top to bottom', 'Parts higher in the picture first.'),
    ('Left to right', 'Parts further left first.'),
    ('Nearest next', 'Each next part is the one closest to where the brush is.'),
)


def order_colour(i, n):
    """Blue for early items to red for late ones."""
    t = i / max(1, n - 1)
    return QColor.fromHsvF(.66 * (1 - t), .75, .85)


def default_line_order(strokes, drawing=None):
    """The lines in the order they had when the picture came in."""
    names = [s.name for s in strokes]
    lead = [re.match(r'\s*(\d+)', n) for n in names]
    if names and all(lead):                                  # traced SVGs: 001-outline, 002-line…
        return [s for _, s in sorted(zip([int(m.group(1)) for m in lead], strokes), key=lambda p: p[0])]
    last = [re.findall(r'(\d+)', n) for n in names]
    if names and all(last):
        numbers = [int(x[-1]) for x in last]
        if len(set(numbers)) == len(numbers):                # line 1, line 2… / Pen H / 1…
            return [s for _, s in sorted(zip(numbers, strokes), key=lambda p: p[0])]
    recorded = getattr(drawing, 'default_order', None) if drawing is not None else None
    if recorded and sorted(recorded) == sorted(names):
        place = {n: i for i, n in enumerate(recorded)}
        return sorted(strokes, key=lambda s: place[s.name])
    return list(strokes)


class OrderPicture(QWidget):
    """The picture: click to select, drag a box to select several."""
    clicked = Signal(int)
    boxed = Signal(list)

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setMinimumSize(520, 420)
        self._press = None
        self._drag = None
        self.shown = None              # Play: only the first `shown` items
        self.trail = []                # Trace the order: the paths drawn with the mouse
        self.lasso = None              # Circle: the loop being drawn (widget points)
        self.setMouseTracking(False)

    # ------------------------------------------------------------ drawing tab
    def transform(self):
        x0, y0, x1, y1 = self.dialog.bounds
        w, h = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
        pad = 18
        scale = min((self.width() - 2 * pad) / w, (self.height() - 2 * pad) / h)
        return scale, (self.width() - w * scale) / 2 - x0 * scale, (self.height() - h * scale) / 2 - y0 * scale

    def polylines(self):
        scale, ox, oy = self.transform()
        return [[(x * scale + ox, y * scale + oy) for x, y in s.points] for s in self.dialog.strokes]

    # ------------------------------------------------------------ painting tab
    def image_rect(self):
        image = self.dialog.colours
        pad = 18
        w, h = self.width() - 2 * pad, self.height() - 2 * pad
        scale = min(w / max(1, image.width()), h / max(1, image.height()))
        iw, ih = image.width() * scale, image.height() * scale
        return QRectF((self.width() - iw) / 2, (self.height() - ih) / 2, iw, ih)

    def part_at(self, x, y):
        grid = self.dialog.grid
        r = self.image_rect()
        gh, gw = grid.shape
        gx, gy = int((x - r.x()) / r.width() * gw), int((y - r.y()) / r.height() * gh)
        if 0 <= gx < gw and 0 <= gy < gh and grid[gy, gx] > 0:
            rid = int(grid[gy, gx])
            return self.dialog.parts.index(rid) if rid in self.dialog.parts else -1
        return -1

    def overlay(self):
        """The parts coloured by order (selected ones orange), as a picture over the colours."""
        import numpy as np
        d = self.dialog
        grid = d.grid
        n = len(d.parts)
        limit = n if self.shown is None else self.shown
        palette = np.zeros((int(grid.max()) + 1, 4), np.uint8)
        for i, rid in enumerate(d.parts):
            if i >= limit:
                palette[rid] = (255, 255, 255, 215)                    # not painted yet (Play)
                continue
            if i in d.selected:
                palette[rid] = (255, 122, 26, 200)
            elif d.colour_order.isChecked():
                c = order_colour(i, n)
                palette[rid] = (c.red(), c.green(), c.blue(), 105)
        rgba = np.ascontiguousarray(palette[grid])
        image = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.shape[1] * 4, QImage.Format.Format_RGBA8888)
        return image.copy()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(250, 248, 243))
        if self.dialog.mode == 'paint':
            self.paint_parts(p)
        else:
            self.paint_lines(p)
        if self._drag is not None:
            p.setPen(QPen(ACCENT, 1.4, Qt.PenStyle.DashLine)); p.setBrush(QColor(255, 122, 26, 30))
            p.drawRect(self._drag)
        self.paint_circles(p)
        if self.lasso and len(self.lasso) > 1:
            p.setBrush(QColor(255, 122, 26, 35))
            p.setPen(QPen(ACCENT, 2, Qt.PenStyle.DashLine))
            p.drawPolygon([QPointF(x, y) for x, y in self.lasso])
        if self.dialog.tracing and self.trail:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(40, 160, 255, 150), max(2., self.dialog.trace_size.value() * 2),
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for path in self.trail:
                if len(path) > 1:
                    p.drawPath(_path(path))
        p.end()

    # ------------------------------------------------------------ circles
    def to_widget(self, point):
        """A circle point (drawing units, or picture fractions on the Painting tab) on screen."""
        x, y = point
        if self.dialog.mode == 'paint':
            r = self.image_rect()
            return r.x() + x * r.width(), r.y() + y * r.height()
        scale, ox, oy = self.transform()
        return x * scale + ox, y * scale + oy

    def from_widget(self, x, y):
        if self.dialog.mode == 'paint':
            r = self.image_rect()
            return (x - r.x()) / max(1e-6, r.width()), (y - r.y()) / max(1e-6, r.height())
        scale, ox, oy = self.transform()
        return (x - ox) / scale, (y - oy) / scale

    def paint_circles(self, p):
        """The circles drawn so far, each with its group number."""
        for k, poly in enumerate(self.dialog.circles.get(self.dialog.mode, [])):
            pts = [QPointF(*self.to_widget(pt)) for pt in poly]
            if len(pts) < 3:
                continue
            p.setBrush(QColor(255, 122, 26, 22))
            p.setPen(QPen(ACCENT, 2, Qt.PenStyle.SolidLine))
            p.drawPolygon(pts)
            top = min(pts, key=lambda q: q.y())
            # "Group 1", not "1": a loop's number is not a place in the order (exp.101).
            self._tag(p, top.x(), top.y() - 10, f'Group {k + 1}', QColor(120, 70, 220))

    def _tag(self, p, x, y, number, colour=None):
        font = QFont(); font.setBold(True); font.setPointSizeF(8.5); p.setFont(font)
        text = str(number)
        w = max(26, p.fontMetrics().horizontalAdvance(text) + 12)
        label = QRectF(x - w / 2, y - 9, w, 17)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(colour if colour is not None else ACCENT)
        p.drawRoundedRect(label, 5, 5)
        p.setPen(QColor('white')); p.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def paint_lines(self, p):
        d = self.dialog
        lines = self.polylines()
        n = len(lines)
        limit = n if self.shown is None else self.shown
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, line in enumerate(lines[:limit]):
            if len(line) < 2 or i in d.selected:
                continue
            colour = order_colour(i, n) if d.colour_order.isChecked() else QColor(70, 70, 80)
            if self.shown is not None and i == limit - 1:
                colour = ACCENT
            p.setPen(QPen(colour, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(_path(line))
        for i in sorted(d.selected):
            if i >= min(limit, n) or len(lines[i]) < 2:
                continue
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ACCENT, 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(_path(lines[i]))
            x, y = lines[i][0]
            self._tag(p, x, y - 13, i + 1)

    def paint_parts(self, p):
        d = self.dialog
        r = self.image_rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(r, d.colours)
        p.drawImage(r, self.overlay())
        gh, gw = d.grid.shape
        # Every part shows its place in the order (exp.101), so a saved order can be seen
        # after it is opened again; the selected ones in orange.
        shown = set(d.selected) | (set(range(len(d.parts))) if d.show_numbers.isChecked() else set())
        for i in sorted(shown):
            rid = d.parts[i]
            if rid not in d.centres:
                continue
            cx, cy, _ = d.centres[rid]
            self._tag(p, r.x() + cx / gw * r.width(), r.y() + cy / gh * r.height(), i + 1,
                      None if i in d.selected else QColor(60, 60, 72, 210))

    # ------------------------------------------------------------ mouse
    # ------------------------------------------------------------ tracing the order
    def trace_hit(self, x, y):
        """Everything under the cursor (within the trace size) joins the order, nearest first."""
        d = self.dialog
        r = d.trace_size.value()
        if d.mode == 'paint':
            grid = d.grid
            rect = self.image_rect()
            gh, gw = grid.shape
            cx, cy = (x - rect.x()) / rect.width() * gw, (y - rect.y()) / rect.height() * gh
            rr = r / rect.width() * gw
            found = {}
            for gy in range(max(0, int(cy - rr)), min(gh, int(cy + rr) + 1)):
                for gx in range(max(0, int(cx - rr)), min(gw, int(cx + rr) + 1)):
                    rid = int(grid[gy, gx])
                    dist = ((gx + .5 - cx) ** 2 + (gy + .5 - cy) ** 2) ** .5
                    if rid and dist <= rr and dist < found.get(rid, 1e9):
                        found[rid] = dist
            for rid, _ in sorted(found.items(), key=lambda kv: kv[1]):
                if rid in d.parts:
                    d.trace_add(d.parts.index(rid))
            return
        import numpy as np
        a, b, owner, where = self.segments()
        if not len(a):
            return
        ab = b - a
        t = np.clip(((x - a[:, 0]) * ab[:, 0] + (y - a[:, 1]) * ab[:, 1]) / np.maximum((ab ** 2).sum(1), 1e-9), 0, 1)
        dist = np.hypot(a[:, 0] + ab[:, 0] * t - x, a[:, 1] + ab[:, 1] * t - y)
        close = dist <= r
        if not close.any():
            return
        hits = {}
        for k in np.flatnonzero(close):
            i = int(owner[k])
            if i not in hits or dist[k] < hits[i][0]:
                hits[i] = (float(dist[k]), float(where[k] + t[k] * (where[k + 1] - where[k])
                                                   if k + 1 < len(where) and owner[k + 1] == owner[k] else where[k]))
        for i, (_, along) in sorted(hits.items(), key=lambda kv: kv[1][0]):
            d.trace_add(i, flip=along > .5)

    def segments(self):
        """Every line as segments (numpy), made once per order and picture size."""
        import numpy as np
        key = (tuple(id(s) for s in self.dialog.strokes), self.width(), self.height())
        if getattr(self, '_segments', None) and self._segments[0] == key:
            return self._segments[1]
        a, b, owner, where = [], [], [], []
        for i, line in enumerate(self.polylines()):
            if len(line) == 1:
                line = line * 2
            n = max(1, len(line) - 1)
            for j in range(len(line) - 1):
                a.append(line[j]); b.append(line[j + 1]); owner.append(i); where.append(j / n)
        out = (np.asarray(a, float).reshape(-1, 2), np.asarray(b, float).reshape(-1, 2),
               np.asarray(owner, int), np.asarray(where, float))
        self._segments = (key, out)
        return out

    def item_at(self, x, y):
        return self.part_at(x, y) if self.dialog.mode == 'paint' else self.line_at(x, y)

    def mousePressEvent(self, event):
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if self.dialog.circling:
            if ctrl:                                         # Ctrl+click in a circle: remove it
                self.dialog.circle_remove_at(*self.from_widget(event.position().x(), event.position().y()))
                return
            self.lasso = [(event.position().x(), event.position().y())]
            self.update(); return
        if self.dialog.tracing and ctrl:                     # Ctrl+click: take it out of the trace
            self.dialog.trace_remove(self.item_at(event.position().x(), event.position().y()))
            return
        if self.dialog.tracing:
            self._trace_last = event.position()
            self.trail.append([(event.position().x(), event.position().y())])
            self.trace_hit(event.position().x(), event.position().y())
            self.update(); return
        self._press = event.position()

    def mouseMoveEvent(self, event):
        if self.dialog.circling:
            if self.lasso is not None:
                pos = event.position()
                last = self.lasso[-1]
                if abs(pos.x() - last[0]) + abs(pos.y() - last[1]) >= 3:
                    self.lasso.append((pos.x(), pos.y())); self.update()
            return
        if self.dialog.tracing:
            last = getattr(self, '_trace_last', None)
            if last is None:
                return
            pos = event.position()
            step = max(2., self.dialog.trace_size.value() / 2)
            dist = ((pos.x() - last.x()) ** 2 + (pos.y() - last.y()) ** 2) ** .5
            for k in range(1, int(dist / step) + 2):
                f = min(1., k * step / max(1e-6, dist))
                self.trace_hit(last.x() + (pos.x() - last.x()) * f, last.y() + (pos.y() - last.y()) * f)
            self.trail[-1].append((pos.x(), pos.y()))
            self._trace_last = pos
            self.update(); return
        if self._press is None:
            return
        a, b = self._press, event.position()
        if abs(a.x() - b.x()) + abs(a.y() - b.y()) > 6:
            self._drag = QRectF(a, b).normalized(); self.update()

    def mouseReleaseEvent(self, event):
        if self.dialog.circling:
            lasso, self.lasso = self.lasso, None
            if lasso and len(lasso) >= 3:
                self.dialog.circle_done([self.from_widget(x, y) for x, y in lasso])
            self.update(); return
        if self.dialog.tracing:
            self._trace_last = None
            self.update(); return
        if self._drag is not None:
            box = self._drag
            self._drag = None; self._press = None
            self.boxed.emit(self.inside(box)); self.update(); return
        self._press = None
        x, y = event.position().x(), event.position().y()
        self.clicked.emit(self.part_at(x, y) if self.dialog.mode == 'paint' else self.line_at(x, y))

    def inside(self, box):
        if self.dialog.mode == 'paint':
            r = self.image_rect()
            gh, gw = self.dialog.grid.shape
            out = []
            for i, rid in enumerate(self.dialog.parts):
                cx, cy, _ = self.dialog.centres[rid]
                if box.contains(QPointF(r.x() + cx / gw * r.width(), r.y() + cy / gh * r.height())):
                    out.append(i)
            return out
        return [i for i, line in enumerate(self.polylines())
                if line and all(box.contains(QPointF(x, y)) for x, y in line)]

    def line_at(self, x, y, tolerance=9.):
        best, best_d = -1, tolerance
        for i, line in enumerate(self.polylines()):
            for (ax, ay), (bx, by) in zip(line, line[1:]):
                dx, dy = bx - ax, by - ay
                t = max(0., min(1., ((x - ax) * dx + (y - ay) * dy) / max(1e-9, dx * dx + dy * dy)))
                dist = ((ax + dx * t - x) ** 2 + (ay + dy * t - y) ** 2) ** .5
                if dist < best_d:
                    best, best_d = i, dist
        return best


def _path(line):
    path = QPainterPath(QPointF(*line[0]))
    for pt in line[1:]:
        path.lineTo(QPointF(*pt))
    return path


class DropList(QListWidget):
    """The list; says when items were dragged to a new place."""
    dropped = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.dropped.emit()


class LineOrderDialog(QDialog):
    def __init__(self, window, mode='draw'):
        super().__init__(window)
        self.setWindowTitle('Line order')
        self.window_ = window
        drawing = window.drawing
        self.drawing = drawing
        self.strokes = list(drawing.strokes)
        self.bounds = tuple(drawing.bounds)
        self.line_selection = set(window.selected_rows()) if hasattr(window, 'selected_rows') else set()
        self.part_selection = set()
        self.parts = []                 # part ids in painting order
        self.parts_changed = False
        self.circles = {'draw': [], 'paint': [list(map(tuple, c)) for c in (getattr(drawing, 'paint_circles', None) or [])]}
        self.circled_ids = []
        self.circling = False
        self.grid = None
        self.colours = None
        self.mode = 'draw'
        outer = QVBoxLayout(self)
        # Drawing | Painting
        switch = QHBoxLayout(); outer.addLayout(switch)
        self.tab_buttons = {}
        for key, text in (('draw', 'Drawing (lines)'), ('paint', 'Painting (parts)')):
            b = QPushButton(text); b.setCheckable(True); b.setObjectName('primary' if key == 'draw' else '')
            b.clicked.connect(lambda checked=False, k=key: self.set_mode(k))
            switch.addWidget(b); self.tab_buttons[key] = b
        switch.addStretch(1)
        body = QHBoxLayout(); outer.addLayout(body, 1)
        left = QVBoxLayout(); body.addLayout(left, 3)
        self.picture = OrderPicture(self)
        self.picture.clicked.connect(self.picture_clicked)
        self.picture.boxed.connect(self.picture_boxed)
        self.mode_note = QLabel(''); self.mode_note.setWordWrap(True); self.mode_note.setObjectName('notice')
        self.mode_note.setStyleSheet('QLabel { background: rgba(124, 92, 255, 40); border: 1px solid #7C5CFF;'
                                     ' border-radius: 6px; padding: 6px 8px; }')
        self.mode_note.hide()
        left.addWidget(self.mode_note)
        left.addWidget(self.picture, 1)
        self.hint = QLabel(''); self.hint.setWordWrap(True); self.hint.setObjectName('caption')
        left.addWidget(self.hint)
        view = QHBoxLayout(); left.addLayout(view)
        self.colour_order = QCheckBox('Colour by order (blue = first, red = last)')
        self.colour_order.setChecked(True); self.colour_order.toggled.connect(self.picture.update)
        view.addWidget(self.colour_order)
        self.show_numbers = QCheckBox('Show the numbers')
        self.show_numbers.setToolTip('Every part shows its place in the painting order.')
        self.show_numbers.setChecked(True); self.show_numbers.toggled.connect(self.picture.update)
        view.addWidget(self.show_numbers); view.addStretch(1)
        self.play_button = QPushButton('Play order')
        self.play_button.setToolTip('Show the order one by one. Click again to pause.')
        self.play_button.clicked.connect(lambda checked=False: self.toggle_play())
        view.addWidget(self.play_button)
        # Trace the order: draw the path with the mouse; whatever it passes over comes next.
        trace = QHBoxLayout(); left.addLayout(trace)
        self.trace_button = QPushButton('Trace the order'); self.trace_button.setCheckable(True)
        self.trace_button.setToolTip('Hold the mouse down and move over the picture the way the drawing should '
                                     'go: every line (or part) the cursor passes gets the next number.')
        self.trace_button.toggled.connect(self.set_tracing)
        trace.addWidget(self.trace_button)
        trace.addWidget(QLabel('Size'))
        from PySide6.QtWidgets import QSlider
        self.trace_size = QSlider(Qt.Orientation.Horizontal); self.trace_size.setRange(3, 45); self.trace_size.setValue(10)
        self.trace_size.setToolTip('How wide an area the cursor picks up while tracing.')
        self.trace_size.setMaximumWidth(140); trace.addWidget(self.trace_size)
        self.trace_follow = QCheckBox('Turn lines to follow my path'); self.trace_follow.setChecked(True)
        self.trace_follow.setToolTip('A line you reach at its far end is drawn from that end, so the pen follows your path.')
        trace.addWidget(self.trace_follow)
        self.circle_button = QPushButton('Circle'); self.circle_button.setCheckable(True)
        self.circle_button.setToolTip('Draw a loop around things: everything inside becomes group 1, the next '
                                      'loop group 2, and so on, in that order. Ctrl+click in a loop removes it.')
        self.circle_button.toggled.connect(self.set_circling)
        trace.addWidget(self.circle_button)
        self.trace_again = QPushButton('Start over')
        self.trace_again.setToolTip('Forget the traced path and the circles, and start again.')
        self.trace_again.clicked.connect(lambda checked=False: self.trace_restart())
        trace.addWidget(self.trace_again); trace.addStretch(1)
        self.tracing = False
        self.traced = []               # what was traced, in order (stroke ids / part ids)
        self.play_timer = QTimer(self); self.play_timer.setInterval(70)
        self.play_timer.timeout.connect(self.play_step)

        right = QVBoxLayout(); body.addLayout(right, 2)
        self.list_title = self._title('')
        right.addWidget(self.list_title)
        self.list = DropList()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.itemSelectionChanged.connect(self.list_selected)
        self.list.dropped.connect(lambda: QTimer.singleShot(0, self.list_dropped))
        right.addWidget(self.list, 1)
        sel = QHBoxLayout(); right.addLayout(sel)
        self.count = QLabel(''); sel.addWidget(self.count, 1)
        for text, slot in (('Select all', self.select_all), ('Clear selection', self.clear_selection)):
            b = QPushButton(text); b.clicked.connect(lambda checked=False, f=slot: f()); sel.addWidget(b)

        right.addWidget(self._title('MOVE THE SELECTED ONES TOGETHER'))
        grid = QGridLayout(); right.addLayout(grid)
        self.move_buttons = []
        for col, (text, how) in enumerate((('To start', 'start'), ('Up', 'up'), ('Down', 'down'), ('To end', 'end'))):
            b = QPushButton(text); b.clicked.connect(lambda checked=False, h=how: self.move(h))
            grid.addWidget(b, 0, col); self.move_buttons.append(b)
        grid.addWidget(QLabel('Move to place'), 1, 0)
        self.position = QSpinBox(); self.position.setRange(1, 1)
        self.position.setToolTip('The place in the order where the first selected one goes.')
        grid.addWidget(self.position, 1, 1, 1, 2)
        self.to_position = QPushButton('Move'); self.to_position.clicked.connect(lambda checked=False: self.move('at'))
        grid.addWidget(self.to_position, 1, 3); self.move_buttons.append(self.to_position)

        # Drawing only: what the selected lines do.
        self.line_tools = QWidget()
        lt = QGridLayout(self.line_tools); lt.setContentsMargins(0, 0, 0, 0)
        from stroke_timing import PACES
        self.reverse_button = QPushButton('Reverse'); self.reverse_button.clicked.connect(lambda c=False: self.edit(reverse=True))
        self.reverse_button.setToolTip('Draw the selected lines from the other end.')
        self.delete_button = QPushButton('Delete'); self.delete_button.clicked.connect(lambda c=False: self.delete())
        self.delete_button.setToolTip('Remove the selected lines from the animation.')
        self.pace = QComboBox(); self.pace.addItems([name for name, _ in PACES]); self.pace.setCurrentText('Normal')
        self.pace.activated.connect(lambda i: self.set_pace())
        self.pause = QDoubleSpinBox(); self.pause.setRange(0, 10); self.pause.setSingleStep(.25); self.pause.setSuffix(' s')
        self.pause.valueChanged.connect(lambda v: self.set_pause())
        lt.addWidget(self.reverse_button, 0, 0); lt.addWidget(self.delete_button, 0, 1)
        lt.addWidget(QLabel('Pace'), 1, 0); lt.addWidget(self.pace, 1, 1)
        lt.addWidget(QLabel('Pause after'), 2, 0); lt.addWidget(self.pause, 2, 1)
        self.line_tools_title = self._title('THE SELECTED LINES')
        right.addWidget(self.line_tools_title); right.addWidget(self.line_tools)

        right.addWidget(self._title('AUTOMATIC ORDER'))
        auto = QGridLayout(); right.addLayout(auto)
        self.auto = QComboBox()
        self.auto_about = QLabel(''); self.auto_about.setWordWrap(True); self.auto_about.setObjectName('caption')
        self.auto.currentIndexChanged.connect(lambda i: self.auto_about.setText(self.autos()[i][1] if 0 <= i < len(self.autos()) else ''))
        self.auto_scope = QComboBox(); self.auto_scope.addItems(['All', 'Only the selected ones'])
        apply = QPushButton('Apply'); apply.clicked.connect(lambda checked=False: self.apply_auto())
        auto.addWidget(self.auto, 0, 0, 1, 2); auto.addWidget(self.auto_scope, 1, 0); auto.addWidget(apply, 1, 1)
        right.addWidget(self.auto_about)
        right.addWidget(self._title('SAVED ORDERS'))
        saved = QGridLayout(); right.addLayout(saved)
        self.saved = QComboBox()
        self.saved.setToolTip('Default, or an order you saved: choose it to use it again.')
        self.saved.activated.connect(lambda i: self.use_saved(i))
        save = QPushButton('Save order'); save.setToolTip('Keep this order under a name, to come back to it later.')
        save.clicked.connect(lambda checked=False: self.save_order())
        self.forget = QPushButton('Delete'); self.forget.setToolTip('Delete the saved order chosen in the list.')
        self.forget.clicked.connect(lambda checked=False: self.delete_saved())
        saved.addWidget(self.saved, 0, 0, 1, 2); saved.addWidget(save, 1, 0); saved.addWidget(self.forget, 1, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Use this order')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.resize(1120, 720)
        self.set_mode(mode)

    def _title(self, text):
        label = QLabel(text); label.setObjectName('sectionTitle'); return label

    # ------------------------------------------------------------ the two tabs
    @property
    def selected(self):
        return self.part_selection if self.mode == 'paint' else self.line_selection

    @selected.setter
    def selected(self, rows):
        if self.mode == 'paint':
            self.part_selection = set(rows)
        else:
            self.line_selection = set(rows)

    def items(self):
        return self.parts if self.mode == 'paint' else self.strokes

    def autos(self):
        from line_order import AUTO
        return PAINT_AUTO if self.mode == 'paint' else AUTO

    def load_parts(self):
        """The parts Painter paints (only with the Painter paint mode and colours)."""
        if self.grid is not None:
            return True
        w = self.window_
        # Any paint mode opens the parts (exp.100: before, a mode other than Painter
        # quietly kept the Drawing tab, with only a small note under the picture).
        image = w.options().get('final_image')
        if image is None or image.isNull():
            return 'This element has no colours to paint.'
        from painter_paint import parts_for_window
        self.grid, self.default_parts, self.centres, self.circled_ids = parts_for_window(
            self.drawing, image, self.circles['paint'])
        chosen = [int(r) for r in (getattr(self.drawing, 'paint_part_order', None) or self.circled_ids)]
        known = set(self.default_parts)
        self.parts = [r for r in chosen if r in known] + [r for r in self.default_parts if r not in set(chosen)]
        self.colours = image
        return True

    def uses_painter(self):
        w = self.window_
        return w.reveal_mode.currentText() == getattr(w, 'PAINTER_TEXT', None)

    def paint_mode_note(self):
        """Said above the parts when the element does not paint with Painter."""
        if self.uses_painter():
            return ''
        return (f'This element paints with {self.window_.reveal_mode.currentText()}, which chooses its own '
                'order. The order you set here is painted by Painter: when you change it and press '
                '"Use this order", this element switches to Painter.')

    def set_mode(self, mode):
        self.play_timer.stop(); self.picture.shown = None; self.play_button.setText('Play order')
        if getattr(self, 'tracing', False) and mode != self.mode:
            self.trace_button.setChecked(False)
        if getattr(self, 'circling', False) and mode != self.mode:
            self.circle_button.setChecked(False)
        if mode == 'paint':
            ready = self.load_parts()
            if ready is not True:
                self.hint.setText(ready)
                self.tab_buttons['paint'].setChecked(False); self.tab_buttons['draw'].setChecked(True)
                return
        self.mode = mode
        for key, b in self.tab_buttons.items():
            b.setChecked(key == mode)
            b.setObjectName('primary' if key == mode else '')       # the open tab is the purple one
            b.style().unpolish(b); b.style().polish(b)
        painting = mode == 'paint'
        note = self.paint_mode_note() if painting else ''
        self.mode_note.setText(note); self.mode_note.setVisible(bool(note))
        self.list_title.setText('PARTS (painting order)' if painting else 'LINES (drawing order)')
        self.line_tools.setVisible(not painting); self.line_tools_title.setVisible(not painting)
        self.hint.setText('Click a part to select it, click it again to unselect it. Drag a box to select '
                          'several. Selected parts are orange, with their number.' if painting else
                          'Click a line to select it, click it again to unselect it. Drag a box to select '
                          'every line inside. Selected lines are orange, with their number.')
        self.auto.blockSignals(True); self.auto.clear(); self.auto.addItems([n for n, _ in self.autos()])
        self.auto.blockSignals(False); self.auto_about.setText(self.autos()[0][1])
        self.fill_saved()
        self.fill()

    # ------------------------------------------------------------ list and selection
    def fill(self):
        self.list.blockSignals(True)
        self.list.clear()
        items = self.items()
        n = len(items)
        word = 'Part' if self.mode == 'paint' else 'Line'
        for i in range(n):
            item = QListWidgetItem(f'{word} {i + 1}')
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setForeground(order_colour(i, n).darker(115))
            self.list.addItem(item)
            item.setSelected(i in self.selected)
        self.list.blockSignals(False)
        self.position.setRange(1, max(1, n))
        self.update_state()

    def update_state(self):
        k = len(self.selected)
        word = 'part' if self.mode == 'paint' else 'line'
        self.count.setText(f'{k} {word}{"s" if k != 1 else ""} selected' if k else f'No {word} selected')
        for b in self.move_buttons + [self.reverse_button, self.delete_button, self.pace, self.pause]:
            b.setEnabled(bool(k))
        if k:
            self.position.blockSignals(True); self.position.setValue(min(self.selected) + 1)
            self.position.blockSignals(False)
            if self.mode == 'draw':
                from stroke_timing import pace_name
                first = self.strokes[min(self.selected)]
                self.pace.blockSignals(True); self.pause.blockSignals(True)
                self.pace.setCurrentText(pace_name(getattr(first, 'pace', 1.)))
                self.pause.setValue(float(getattr(first, 'pause', 0.) or 0.))
                self.pace.blockSignals(False); self.pause.blockSignals(False)
        self.picture.update()

    def list_selected(self):
        self.selected = {self.list.row(item) for item in self.list.selectedItems()}
        self.update_state()

    def list_dropped(self):
        order = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        items = self.items()
        if sorted(order) != list(range(len(items))):
            return
        chosen = {id(items[i]) if self.mode == 'draw' else items[i] for i in self.selected}
        new = [items[i] for i in order]
        self._set_items(new)
        self.selected = {i for i, x in enumerate(new) if (id(x) if self.mode == 'draw' else x) in chosen}
        self.fill()

    def _set_items(self, new):
        if self.mode == 'paint':
            self.parts = list(new); self.parts_changed = True
        else:
            self.strokes = list(new)

    def set_selected(self, rows):
        self.selected = set(rows)
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setSelected(i in self.selected)
        self.list.blockSignals(False)
        if self.selected:
            self.list.scrollToItem(self.list.item(min(self.selected)))
        self.update_state()

    def picture_clicked(self, index):
        if index < 0:
            return
        self.set_selected(self.selected ^ {index})      # click again: unselected

    def picture_boxed(self, rows):
        self.set_selected(self.selected | set(rows))

    def select_all(self):
        self.set_selected(range(len(self.items())))

    def clear_selection(self):
        self.set_selected(())

    # ------------------------------------------------------------ moving and ordering
    def move(self, how):
        from line_order import move_block
        rows = sorted(self.selected)
        if not rows:
            return
        items = self.items()
        count = len(items) - len(rows)
        rest_before = len([i for i in range(rows[0]) if i not in self.selected])
        target = {'start': 0, 'end': count, 'up': max(0, rest_before - 1),
                  'down': min(count, rest_before + 1), 'at': self.position.value() - 1}[how]
        new, placed = move_block(items, rows, target)
        self._set_items(new)
        self.selected = set(placed)
        self.fill()

    def apply_auto(self):
        only = self.auto_scope.currentIndex() == 1
        if only and not self.selected:
            self.auto_about.setText('Select some first, or choose "All".')
            return
        rows = sorted(self.selected) if only else None
        if self.mode == 'paint':
            new = self.ordered_parts([self.parts[r] for r in rows] if rows else list(self.parts), self.auto.currentText())
            if rows:
                parts = list(self.parts)
                for r, x in zip(rows, new):
                    parts[r] = x
                new = parts
            self._set_items(new)
        else:
            from line_order import apply_order
            self.strokes, _ = apply_order(self.strokes, self.auto.currentText(), rows)
        self.selected = set(rows) if only else set()
        self.fill()

    def ordered_parts(self, parts, kind):
        import math
        c = self.centres
        if kind == 'Big parts first, details last':
            place = {r: i for i, r in enumerate(self.default_parts)}
            return sorted(parts, key=lambda r: place.get(r, 0))
        if kind == 'Top to bottom':
            return sorted(parts, key=lambda r: (c[r][1], c[r][0]))
        if kind == 'Left to right':
            return sorted(parts, key=lambda r: (c[r][0], c[r][1]))
        left = list(parts)
        out = [min(left, key=lambda r: (c[r][1], c[r][0]))]
        left.remove(out[0])
        while left:
            here = c[out[-1]][:2]
            nxt = min(left, key=lambda r: math.dist(here, c[r][:2]))
            left.remove(nxt); out.append(nxt)
        return out

    def default(self):
        if self.mode == 'paint':
            self._set_items(self.default_parts)
        else:
            self.strokes = default_line_order(self.strokes, self.drawing)
        self.selected = set()
        self.fill()

    # ------------------------------------------------------------ the selected lines
    def edit(self, **change):
        from history import edited_stroke
        rows = set(self.line_selection)
        self.strokes = [edited_stroke(s, **change) if i in rows else s for i, s in enumerate(self.strokes)]
        self.fill()

    def set_pace(self):
        from stroke_timing import pace_value
        self.edit(pace=pace_value(self.pace.currentText()))

    def set_pause(self):
        if self.line_selection:
            self.edit(pause=self.pause.value())

    def delete(self):
        rows = set(self.line_selection)
        if not rows or len(rows) >= len(self.strokes):
            self.count.setText('At least one line has to stay.'); return
        self.strokes = [s for i, s in enumerate(self.strokes) if i not in rows]
        self.line_selection = set()
        self.fill()

    # ------------------------------------------------------------ play
    def toggle_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop(); self.play_button.setText('Play order'); return
        if self.picture.shown is None or self.picture.shown >= len(self.items()):
            self.picture.shown = 0
        self.play_button.setText('Pause')
        self.play_timer.setInterval(70 if self.mode == 'draw' else 260)
        self.play_timer.start()

    def play_step(self):
        self.picture.shown = (self.picture.shown or 0) + 1
        if self.picture.shown >= len(self.items()):
            self.play_timer.stop(); self.play_button.setText('Play order'); self.picture.shown = None
        self.picture.update()

    # ------------------------------------------------------------ trace the order
    def set_tracing(self, on):
        self.tracing = bool(on)
        if on and self.circle_button.isChecked():
            self.circle_button.setChecked(False)
        self.trace_base = list(self.items())
        self.trace_restart(circles=False)
        self.picture.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        if on:
            self.hint.setText('Trace: hold the mouse down and move over the picture the way it should be '
                              + ('painted' if self.mode == 'paint' else 'drawn')
                              + '. Everything you pass gets the next number. Let go and start again anywhere to '
                              'go on; what you never touch comes after, in its present order. Ctrl+click a '
                              'numbered one to take it out again.')
        else:
            self.set_mode(self.mode)

    def trace_restart(self, circles=True):
        if circles and self.circles.get(self.mode):
            self.circles[self.mode] = []
            self.apply_circles()
        self.traced = []
        self.picture.trail = []
        self.selected = set()
        self.fill()

    def trace_remove(self, index):
        """Take the item at `index` out of the trace: it goes back after the traced ones."""
        items = list(self.items())
        if not 0 <= index < len(items) or self._key(items[index]) not in self.traced:
            return
        self.traced.remove(self._key(items[index]))
        base = getattr(self, 'trace_base', items)
        where = {self._name(x): n for n, x in enumerate(base)}
        place = {k: n for n, k in enumerate(self.traced)}
        first = sorted((x for x in items if self._key(x) in place), key=lambda x: place[self._key(x)])
        rest = sorted((x for x in items if self._key(x) not in place), key=lambda x: where.get(self._name(x), 0))
        ordered = self._with_pinned_first(first + rest)
        self._set_items(ordered)
        self.selected = {n for n, x in enumerate(ordered) if self._key(x) in place}
        self.fill()

    def _name(self, item):
        return item if self.mode == 'paint' else item.name

    # ------------------------------------------------------------ circles
    def set_circling(self, on):
        self.circling = bool(on)
        if on and self.trace_button.isChecked():
            self.trace_button.setChecked(False)
        self.picture.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        if on:
            self.hint.setText('Circle: draw a loop around what should come first; everything inside becomes '
                              'group 1. The next loop is group 2, and so on. '
                              + ('A loop cuts its own part out of the picture, so only what is inside is painted '
                                 'together. ' if self.mode == 'paint' else
                                 'A line belongs to a loop when most of it is inside. ')
                              + 'Ctrl+click in a loop removes it. What is not circled comes after.')
        else:
            self.set_mode(self.mode)

    def circle_done(self, poly):
        self.circles[self.mode].append([tuple(map(float, pt)) for pt in poly])
        self.apply_circles()

    def circle_remove_at(self, x, y):
        for k in reversed(range(len(self.circles[self.mode]))):
            if _inside(self.circles[self.mode][k], x, y):
                del self.circles[self.mode][k]
                self.apply_circles()
                return

    def apply_circles(self):
        """The order from the circles: group 1, group 2…, then everything else as it was."""
        if self.mode == 'paint':
            from painter_paint import parts_for_window
            previous = [r for r in self.parts if r not in set(self.circled_ids)]
            self.grid, self.default_parts, self.centres, self.circled_ids = parts_for_window(
                self.drawing, self.colours, self.circles['paint'])
            known = set(self.centres)
            rest = [r for r in previous if r in known and r not in set(self.circled_ids)]
            rest += [r for r in self.default_parts if r not in set(rest) and r not in set(self.circled_ids)]
            self.parts = list(self.circled_ids) + rest
            self.parts_changed = True
            self.selected = set(range(len(self.circled_ids)))
        else:
            groups, used = [], set()
            for poly in self.circles['draw']:
                group = [s for s in self.strokes if id(s) not in used and _mostly_inside(poly, s.points)]
                used |= {id(s) for s in group}
                groups.extend(group)
            base = getattr(self, 'circle_base', None)
            if base is None or {id(s) for s in base} != {id(s) for s in self.strokes}:
                base = self.circle_base = list(self.strokes)
            self.strokes = groups + [s for s in base if id(s) not in used]
            self.circle_keys = [id(s) for s in groups]
            self.selected = set(range(len(groups)))
        self.fill()

    def painting_circles(self):
        return [list(map(list, c)) for c in self.circles['paint']] or None

    # ------------------------------------------------------------ saved orders
    def saved_orders(self):
        return [o for o in (getattr(self.drawing, 'saved_orders', None) or []) if o.get('kind') == self.mode]

    def fill_saved(self):
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem('Default')
        current = 0
        for n, o in enumerate(self.saved_orders(), 1):
            self.saved.addItem(o['name'])
            if self.matches_saved(o):
                current = n
        # The order in use shows its name (exp.101: it always said "Default", so a saved
        # order looked lost when the window was opened again).
        self.saved.setCurrentIndex(current)
        self.saved.blockSignals(False)
        self.forget.setEnabled(current > 0)

    def matches_saved(self, entry):
        if self.mode == 'paint':
            circles = [[list(map(float, pt)) for pt in c] for c in (entry.get('circles') or [])]
            mine = [[list(map(float, pt)) for pt in c] for c in self.circles['paint']]
            return bool(entry.get('parts')) and [int(r) for r in entry['parts']] == [int(r) for r in self.parts] \
                and circles == mine
        lines = entry.get('lines') or []
        seen, mine = {}, []
        for st in self.strokes:
            seen[st.name] = seen.get(st.name, 0) + 1
            mine.append([st.name, seen[st.name], bool(getattr(st, 'reversed', False))])
        return bool(lines) and [list(x) for x in lines] == mine

    def save_order(self):
        """Keep the current order of this tab under a name (saved with the project)."""
        everything = list(getattr(self.drawing, 'saved_orders', None) or [])
        name = f'Order {len(self.saved_orders()) + 1}'
        if self.mode == 'paint':
            entry = dict(kind='paint', name=name, parts=[int(r) for r in self.parts],
                         circles=self.painting_circles() or [])
        else:
            seen = {}
            lines = []
            for s in self.strokes:
                seen[s.name] = seen.get(s.name, 0) + 1
                lines.append([s.name, seen[s.name], bool(getattr(s, 'reversed', False))])
            entry = dict(kind='draw', name=name, lines=lines)
        everything.append(entry)
        self.drawing.saved_orders = everything
        self.saved_changed = True
        self.fill_saved()
        self.saved.setCurrentIndex(self.saved.count() - 1)
        self.forget.setEnabled(True)
        self.count.setText(f'Saved as "{name}".')

    def use_saved(self, index):
        self.forget.setEnabled(index > 0)
        if index == 0:
            self.circles[self.mode] = []
            if self.mode == 'paint':
                self.apply_circles()
            self.default(); return
        entry = self.saved_orders()[index - 1]
        if self.mode == 'paint':
            self.circles['paint'] = [list(map(tuple, c)) for c in entry.get('circles') or []]
            self.apply_circles()
            known = set(self.centres)
            first = [int(r) for r in entry.get('parts', []) if int(r) in known]
            self.parts = first + [r for r in self.parts if r not in set(first)]
            self.parts_changed = True
        else:
            from history import edited_stroke
            pool = {}
            for s in self.strokes:
                pool.setdefault(s.name, []).append(s)
            new = []
            for name, n, rev in entry.get('lines', []):
                options = pool.get(name) or []
                if n - 1 < len(options) and options[n - 1] is not None:
                    s = options[n - 1]; options[n - 1] = None
                    if bool(getattr(s, 'reversed', False)) != bool(rev):
                        s = edited_stroke(s, reverse=True)
                    new.append(s)
            used = {id(s) for s in new}
            left = [s for group in pool.values() for s in group if s is not None and id(s) not in used]
            left_ids = {id(s) for s in left}
            self.strokes = new + [s for s in self.strokes if id(s) in left_ids]
        self.selected = set()
        self.fill()

    def delete_saved(self):
        index = self.saved.currentIndex()
        if index <= 0:
            return
        entry = self.saved_orders()[index - 1]
        self.drawing.saved_orders = [o for o in (self.drawing.saved_orders or []) if o is not entry]
        self.saved_changed = True
        self.fill_saved()

    def _key(self, item):
        return item if self.mode == 'paint' else id(item)

    def pinned(self):
        """Keys of the circled groups: they stay first, before what is traced (exp.101: a
        trace used to push the circled group behind everything traced)."""
        if self.mode == 'paint':
            return list(self.circled_ids)
        return list(getattr(self, 'circle_keys', None) or [])

    def _with_pinned_first(self, items):
        pins = self.pinned()
        if not pins:
            return items
        place = {k: n for n, k in enumerate(pins)}
        first = sorted((x for x in items if self._key(x) in place), key=lambda x: place[self._key(x)])
        return first + [x for x in items if self._key(x) not in place]

    def trace_add(self, index, flip=False):
        """The item at `index` comes next in the order (after the circled groups and what
        was traced before)."""
        items = list(self.items())
        if not 0 <= index < len(items):
            return
        item = items[index]
        if self._key(item) in self.traced or self._key(item) in set(self.pinned()):
            return
        if flip and self.mode == 'draw' and self.trace_follow.isChecked():
            from history import edited_stroke
            item = edited_stroke(item, reverse=True)
            items[index] = item
        self.traced.append(self._key(item))
        place = {k: n for n, k in enumerate(self.traced)}
        first = sorted((x for x in items if self._key(x) in place), key=lambda x: place[self._key(x)])
        rest = [x for x in items if self._key(x) not in place]
        ordered = self._with_pinned_first(first + rest)
        self._set_items(ordered)
        self.selected = {n for n, x in enumerate(ordered) if self._key(x) in place}
        self.fill()

    def painting_order(self):
        """The chosen painting order to keep on the element (None: the default)."""
        if not self.parts_changed:
            return getattr(self.drawing, 'paint_part_order', None)
        return None if list(self.parts) == list(self.default_parts) else [int(r) for r in self.parts]

    def done(self, result):
        self.play_timer.stop()
        super().done(result)


def _inside(poly, x, y):
    """Is (x, y) inside the polygon `poly` (ray casting)?"""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def _mostly_inside(poly, points, share=.6):
    """True when most of a line's points are inside the loop."""
    if not points:
        return False
    step = max(1, len(points) // 40)
    sample = points[::step]
    return sum(1 for x, y in sample if _inside(poly, x, y)) >= share * len(sample)
