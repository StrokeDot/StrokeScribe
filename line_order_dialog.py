"""The Line order window: see the drawing big, pick lines, move them together,
or let StrokeScribe order them automatically.

* Click a line on the picture to select it; click it again to unselect it. Drag a
  box on the picture to select every line inside it. The list works too (Ctrl or
  Shift + click, or drag several lines to a new place).
* Selected lines are bright orange with their number; the other lines are coloured
  by when they are drawn (blue = early, red = late), so you can see the order.
* Move the selected lines together: to the start, up, down, to the end, or to a
  position. They keep their order among themselves.
* Automatic order: for all lines or only the selected ones.
* Play shows the order line by line (Pause stops it).
Nothing changes in the project until you press "Use this order" (one undo step).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

ACCENT = QColor(255, 122, 26)


def order_colour(i, n):
    """Blue for early lines to red for late ones."""
    t = i / max(1, n - 1)
    return QColor.fromHsvF(.66 * (1 - t), .75, .85)


class LinePicture(QWidget):
    """The drawing, big: click to select lines, drag a box to select several."""
    clicked = Signal(int)              # index of a line, or -1 for empty space
    boxed = Signal(list)               # indexes of the lines inside a dragged box

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setMinimumSize(520, 420)
        self.setMouseTracking(True)
        self._press = None
        self._drag = None
        self.shown = None              # Play: only the first `shown` lines

    # Geometry: drawing coordinates -> widget pixels.
    def transform(self):
        x0, y0, x1, y1 = self.dialog.bounds
        w, h = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
        pad = 18
        scale = min((self.width() - 2 * pad) / w, (self.height() - 2 * pad) / h)
        ox = (self.width() - w * scale) / 2 - x0 * scale
        oy = (self.height() - h * scale) / 2 - y0 * scale
        return scale, ox, oy

    def polylines(self):
        scale, ox, oy = self.transform()
        return [[(x * scale + ox, y * scale + oy) for x, y in s.points] for s in self.dialog.strokes]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(250, 248, 243))
        d = self.dialog
        lines = self.polylines()
        n = len(lines)
        limit = n if self.shown is None else self.shown
        colours = d.colour_order.isChecked()
        for i, line in enumerate(lines[:limit]):
            if len(line) < 2 or i in d.selected:
                continue
            colour = order_colour(i, n) if colours else QColor(70, 70, 80)
            if self.shown is not None and i == limit - 1:
                colour = ACCENT
            p.setPen(QPen(colour, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath(QPointF(*line[0]))
            for pt in line[1:]:
                path.lineTo(QPointF(*pt))
            p.drawPath(path)
        font = QFont(); font.setBold(True); font.setPointSizeF(8.5); p.setFont(font)
        for i in sorted(d.selected):
            if i >= limit or i >= n or len(lines[i]) < 2:
                continue
            line = lines[i]
            p.setPen(QPen(ACCENT, 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath(QPointF(*line[0]))
            for pt in line[1:]:
                path.lineTo(QPointF(*pt))
            p.drawPath(path)
            # Its number in the drawing order, at its start.
            x, y = line[0]
            label = QRectF(x - 13, y - 22, 26, 17)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(ACCENT); p.drawRoundedRect(label, 5, 5)
            p.setPen(QColor('white')); p.drawText(label, Qt.AlignmentFlag.AlignCenter, str(i + 1))
        if self._drag is not None:
            p.setPen(QPen(ACCENT, 1.4, Qt.PenStyle.DashLine)); p.setBrush(QColor(255, 122, 26, 30))
            p.drawRect(self._drag)
        p.end()

    def line_at(self, x, y, tolerance=9.):
        best, best_d = -1, tolerance
        for i, line in enumerate(self.polylines()):
            for a, b in zip(line, line[1:]):
                ax, ay = a; bx, by = b
                dx, dy = bx - ax, by - ay
                t = max(0., min(1., ((x - ax) * dx + (y - ay) * dy) / max(1e-9, dx * dx + dy * dy)))
                dist = ((ax + dx * t - x) ** 2 + (ay + dy * t - y) ** 2) ** .5
                if dist < best_d:
                    best, best_d = i, dist
        return best

    def mousePressEvent(self, event):
        self._press = event.position()

    def mouseMoveEvent(self, event):
        if self._press is None:
            return
        a, b = self._press, event.position()
        if abs(a.x() - b.x()) + abs(a.y() - b.y()) > 6:
            self._drag = QRectF(a, b).normalized(); self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            box = self._drag
            inside = [i for i, line in enumerate(self.polylines())
                      if line and all(box.contains(QPointF(x, y)) for x, y in line)]
            self._drag = None; self._press = None
            self.boxed.emit(inside); self.update(); return
        self._press = None
        self.clicked.emit(self.line_at(event.position().x(), event.position().y()))


class DropList(QListWidget):
    """The line list; says when lines were dragged to a new place."""
    dropped = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.dropped.emit()


class LineOrderDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        from line_order import AUTO
        self.setWindowTitle('Line order')
        self.window_ = window
        drawing = window.drawing
        self.original = list(drawing.strokes)
        self.strokes = list(drawing.strokes)
        self.bounds = tuple(drawing.bounds)
        self.selected = set(window.selected_rows()) if hasattr(window, 'selected_rows') else set()
        outer = QVBoxLayout(self)
        body = QHBoxLayout(); outer.addLayout(body, 1)
        left = QVBoxLayout(); body.addLayout(left, 3)
        self.picture = LinePicture(self)
        self.picture.clicked.connect(self.picture_clicked)
        self.picture.boxed.connect(self.picture_boxed)
        left.addWidget(self.picture, 1)
        hint = QLabel('Click a line to select it, click it again to unselect it. Drag a box to select '
                      'every line inside. Selected lines are orange, with their number.')
        hint.setWordWrap(True); hint.setObjectName('caption'); left.addWidget(hint)
        view = QHBoxLayout(); left.addLayout(view)
        self.colour_order = QCheckBox('Colour by order (blue = first, red = last)')
        self.colour_order.setChecked(True); self.colour_order.toggled.connect(self.picture.update)
        view.addWidget(self.colour_order); view.addStretch(1)
        self.play_button = QPushButton('▶ Play order')
        self.play_button.setToolTip('Show the lines one by one in their drawing order. Click again to pause.')
        self.play_button.clicked.connect(lambda checked=False: self.toggle_play())
        view.addWidget(self.play_button)
        self.play_timer = QTimer(self); self.play_timer.setInterval(70)
        self.play_timer.timeout.connect(self.play_step)

        right = QVBoxLayout(); body.addLayout(right, 2)
        right.addWidget(self._title('LINES (drawing order)'))
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

        right.addWidget(self._title('MOVE THE SELECTED LINES TOGETHER'))
        grid = QGridLayout(); right.addLayout(grid)
        self.move_buttons = []
        for col, (text, how) in enumerate((('To start', 'start'), ('Up', 'up'), ('Down', 'down'), ('To end', 'end'))):
            b = QPushButton(text); b.clicked.connect(lambda checked=False, h=how: self.move(h))
            grid.addWidget(b, 0, col); self.move_buttons.append(b)
        grid.addWidget(QLabel('To position'), 1, 0)
        self.position = QSpinBox(); self.position.setRange(1, max(1, len(self.strokes)))
        grid.addWidget(self.position, 1, 1, 1, 2)
        self.to_position = QPushButton('Move'); self.to_position.clicked.connect(lambda checked=False: self.move('at'))
        grid.addWidget(self.to_position, 1, 3); self.move_buttons.append(self.to_position)

        right.addWidget(self._title('AUTOMATIC ORDER'))
        auto = QGridLayout(); right.addLayout(auto)
        self.auto = QComboBox(); self.auto.addItems([name for name, _ in AUTO])
        self.auto_about = QLabel(''); self.auto_about.setWordWrap(True); self.auto_about.setObjectName('caption')
        self.auto.currentIndexChanged.connect(lambda i: self.auto_about.setText(AUTO[i][1]))
        self.auto_about.setText(AUTO[0][1])
        self.auto_scope = QComboBox(); self.auto_scope.addItems(['All lines', 'Only the selected lines'])
        apply = QPushButton('Apply'); apply.clicked.connect(lambda checked=False: self.apply_auto())
        auto.addWidget(self.auto, 0, 0, 1, 2); auto.addWidget(self.auto_scope, 1, 0); auto.addWidget(apply, 1, 1)
        right.addWidget(self.auto_about)
        reset = QPushButton('Back to how it was'); reset.clicked.connect(lambda checked=False: self.reset())
        right.addWidget(reset)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Use this order')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.resize(1120, 700)
        self.fill()

    def _title(self, text):
        label = QLabel(text); label.setObjectName('sectionTitle'); return label

    # ------------------------------------------------------------ list and selection
    def fill(self):
        from history import describe
        self.list.blockSignals(True)
        self.list.clear()
        n = len(self.strokes)
        for i, stroke in enumerate(self.strokes):
            item = QListWidgetItem(f'{i + 1:>3} · {describe(stroke)}')
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setForeground(order_colour(i, n).darker(115))
            self.list.addItem(item)
            item.setSelected(i in self.selected)
        self.list.blockSignals(False)
        self.position.setRange(1, max(1, n))
        self.update_state()

    def update_state(self):
        k = len(self.selected)
        self.count.setText(f'{k} line{"s" if k != 1 else ""} selected' if k else 'No line selected')
        for b in self.move_buttons:
            b.setEnabled(bool(k))
        self.picture.update()

    def list_selected(self):
        self.selected = {self.list.row(item) for item in self.list.selectedItems()}
        self.update_state()

    def list_dropped(self):
        """Lines dragged to a new place in the list (several at once is fine)."""
        order = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        if sorted(order) != list(range(len(self.strokes))):
            return
        chosen = {id(self.strokes[i]) for i in self.selected}
        self.strokes = [self.strokes[i] for i in order]
        self.selected = {i for i, s in enumerate(self.strokes) if id(s) in chosen}
        self.fill()

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
        self.set_selected(range(len(self.strokes)))

    def clear_selection(self):
        self.set_selected(())

    # ------------------------------------------------------------ moving and ordering
    def move(self, how):
        from line_order import move_block
        rows = sorted(self.selected)
        if not rows:
            return
        count = len(self.strokes) - len(rows)          # places in the list without the block
        rest_before = len([i for i in range(rows[0]) if i not in self.selected])
        target = {'start': 0, 'end': count, 'up': max(0, rest_before - 1),
                  'down': min(count, rest_before + 1),
                  'at': self.position.value() - 1}[how]
        self.strokes, new = move_block(self.strokes, rows, target)
        self.selected = set(new)
        self.fill()

    def apply_auto(self):
        from line_order import apply_order
        only = self.auto_scope.currentIndex() == 1
        if only and not self.selected:
            self.auto_about.setText('Select some lines first, or choose "All lines".')
            return
        self.strokes, rows = apply_order(self.strokes, self.auto.currentText(),
                                         sorted(self.selected) if only else None)
        self.selected = set(rows) if only else set()
        self.fill()

    def reset(self):
        self.strokes = list(self.original); self.selected = set(); self.fill()

    # ------------------------------------------------------------ play
    def toggle_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop(); self.play_button.setText('▶ Play order'); return
        if self.picture.shown is None or self.picture.shown >= len(self.strokes):
            self.picture.shown = 0
        self.play_button.setText('❚❚ Pause')
        self.play_timer.start()

    def play_step(self):
        self.picture.shown = (self.picture.shown or 0) + 1
        if self.picture.shown >= len(self.strokes):
            self.play_timer.stop(); self.play_button.setText('▶ Play order'); self.picture.shown = None
        self.picture.update()

    def done(self, result):
        self.play_timer.stop()
        super().done(result)
