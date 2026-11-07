"""exp.217 (the user: "keyframes inside the trajectory"): Edit path of a hand's way.

The video frame of that moment, with the hand's way from where it starts (green) to where it
arrives (red) and its keyframes: round handles to drag. The chosen way (Swoop, Curve...) gives
the first keyframes; drag them to change the path; double-click the path to add a keyframe,
right-click one to remove it. There is room around the picture: a keyframe can be outside it.
The hand keeps the speed of its way (Smooth, Swoop...).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

ROOM = .3          # room around the picture (share of its size) for keyframes outside it


class PathCanvas(QWidget):
    def __init__(self, frame, a, b, keys, parent=None):
        super().__init__(parent)
        self.frame, self.a, self.b = frame, tuple(a), tuple(b)
        self.keys = [tuple(k) for k in keys]
        self.drag = None
        self.try_at = None                     # 0..1: the hand shown along the path (Try)
        self.style = 'Smooth'
        self.hand = None                       # exp.219: (picture, grip, width in frame pixels)
        self.setMinimumSize(760, 520)
        self.setMouseTracking(True)

    # frame pixels <-> widget pixels
    def _box(self):
        fw, fh = self.frame.width(), self.frame.height()
        total_w, total_h = fw * (1 + 2 * ROOM), fh * (1 + 2 * ROOM)
        k = min(self.width() / total_w, self.height() / total_h)
        ox = (self.width() - total_w * k) / 2 + fw * ROOM * k
        oy = (self.height() - total_h * k) / 2 + fh * ROOM * k
        return ox, oy, k

    def to_widget(self, p):
        ox, oy, k = self._box()
        return QPointF(ox + p[0] * k, oy + p[1] * k)

    def to_frame(self, q):
        ox, oy, k = self._box()
        return ((q.x() - ox) / k, (q.y() - oy) / k)

    def points(self):
        from frame_render import _path_points
        return _path_points(self.a, self.b, self.keys)

    def line(self, steps=24):
        from frame_render import path_polyline
        return path_polyline(self.a, self.b, self.keys, steps)

    def key_of(self, spot):
        """A keyframe for this spot of the frame."""
        from frame_render import to_keyframe
        return to_keyframe(self.a, self.b, spot)

    def paintEvent(self, event):
        from frame_render import path_polyline, _along_polyline, _glide_ease
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#1d1d24'))
        ox, oy, k = self._box()
        rect = QRectF(ox, oy, self.frame.width() * k, self.frame.height() * k)
        p.fillRect(rect, QColor('white'))           # the video's background (the picture is clear)
        p.drawImage(rect, self.frame)
        p.setPen(QPen(QColor('#8a7cff'), 1.5, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)                         # the edge of the video
        line = self.line()
        path = QPainterPath(self.to_widget(line[0]))
        for q in line[1:]:
            path.lineTo(self.to_widget(q))
        p.setPen(QPen(QColor(255, 255, 255, 200), 5)); p.drawPath(path)
        p.setPen(QPen(QColor('#e5484d'), 2.5)); p.drawPath(path)
        spot = _along_polyline(line, _glide_ease(self.try_at or 0., self.style))
        c = self.to_widget(spot)
        if self.hand is not None:
            # exp.219 (the user): the hand itself, at its size in the video, its pen on the path
            image, (gx, gy), size = self.hand
            hw = size * k; hh = hw * image.height() / max(1, image.width())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.setOpacity(.92)
            p.drawImage(QRectF(c.x() - gx * hw, c.y() - gy * hh, hw, hh), image)
            p.setOpacity(1.)
        elif self.try_at is not None:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#ffd166')); p.drawEllipse(c, 8, 8)
        for i, q in enumerate(self.points()):
            c = self.to_widget(q)
            if i == 0 or i == len(self.keys) + 1:
                p.setPen(QPen(QColor('white'), 2)); p.setBrush(QColor('#2ecc71' if i == 0 else '#e5484d'))
                p.drawEllipse(c, 7, 7)
            else:
                p.setPen(QPen(QColor('white'), 2)); p.setBrush(QColor('#6c5ce7'))
                p.drawEllipse(c, 9, 9)
        p.end()

    def _key_at(self, pos):
        for i, q in enumerate(self.points()[1:-1]):
            c = self.to_widget(q)
            if math.hypot(c.x() - pos.x(), c.y() - pos.y()) <= 12:
                return i
        return None

    def mousePressEvent(self, event):
        i = self._key_at(event.position())
        if event.button() == Qt.MouseButton.RightButton:
            if i is not None:
                del self.keys[i]; self.update()
            return
        if i is not None:
            self.drag = i

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self.keys[self.drag] = self.key_of(self.to_frame(event.position()))
            self.update()
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._key_at(event.position()) is not None
                           else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseDoubleClickEvent(self, event):
        """A new keyframe where the path was double-clicked (between the two around it)."""
        spot = self.to_frame(event.position())
        new = self.key_of(spot)
        # put it in order along the way: after the keyframes that come before it on the path
        line = self.line(24)
        nearest = min(range(len(line)), key=lambda j: math.hypot(line[j][0] - spot[0], line[j][1] - spot[1]))
        index = min(len(self.keys), nearest // 24)
        self.keys.insert(index, new)
        self.update()


class GlidePathDialog(QDialog):
    def __init__(self, parent, frame, a, b, keys, preset, style, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.preset = [tuple(k) for k in preset]
        layout = QVBoxLayout(self)
        help_text = QLabel('Drag the purple keyframes to shape the hand\'s way from the green dot to the red one. '
                           'Double-click the path to add a keyframe, right-click one to remove it. '
                           'They can go outside the video (the dashed edge).')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.canvas = PathCanvas(frame, a, b, keys or preset)
        self.canvas.style = style
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        reset = QPushButton('Back to the preset'); reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addWidget(QLabel('Try:'))
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setRange(0, 100)
        self.slider.valueChanged.connect(self.tried)
        row.addWidget(self.slider, 1)
        play = QPushButton('Play'); play.clicked.connect(self.play)
        row.addWidget(play)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self); self.timer.timeout.connect(self._step)

    def reset(self):
        self.canvas.keys = list(self.preset); self.canvas.update()

    def tried(self, value):
        self.canvas.try_at = value / 100.; self.canvas.update()

    def play(self):
        self.slider.setValue(0); self.timer.start(25)

    def _step(self):
        if self.slider.value() >= 100:
            self.timer.stop(); return
        self.slider.setValue(self.slider.value() + 2)

    def keyframes(self):
        """The keyframes, or None when they are the preset's (no path of its own)."""
        keys = [tuple(round(v, 4) for v in k) for k in self.canvas.keys]
        if keys == [tuple(round(v, 4) for v in k) for k in self.preset]:
            return None
        return keys


class PathsCanvas(PathCanvas):
    """exp.220: the canvas of Hand paths: the chosen way with its keyframes, the other ways
    faint (with their element number) so they are seen together."""

    def __init__(self, parent=None):
        from PySide6.QtGui import QImage
        blank = QImage(960, 540, QImage.Format.Format_ARGB32); blank.fill(0)
        super().__init__(blank, (0, 0), (1, 1), [], parent)
        self.others = []                       # [(a, b, keys, label, done)]

    def paintEvent(self, event):
        super().paintEvent(event)
        from frame_render import path_polyline
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for a, b, keys, label, done in self.others:
            line = path_polyline(a, b, keys or [])
            path = QPainterPath(self.to_widget(line[0]))
            for q in line[1:]:
                path.lineTo(self.to_widget(q))
            colour = QColor('#8a7cff') if not done else QColor(160, 160, 170)
            colour.setAlpha(150)
            p.setPen(QPen(colour, 2, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
            mid = self.to_widget(line[len(line) // 2])
            p.setPen(QColor('white')); p.drawText(QRectF(mid.x() + 6, mid.y() - 9, 140, 18),
                                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        p.end()


class HandPathsDialog(QDialog):
    """exp.220 (the user): every way of the hands in the video together: a list of the ways in
    the order they happen, the chosen one with its keyframes on the picture of its moment, the
    others faint; Play goes through them all with the hand; OK keeps every change."""

    def __init__(self, parent, moves):
        from PySide6.QtWidgets import QListWidget, QSplitter
        super().__init__(parent)
        self.setWindowTitle('Hand paths')
        self.resize(1180, 760)
        self.moves = moves
        for mv in self.moves:
            mv['edit'] = list(mv['keys'] or mv['preset'])
        layout = QVBoxLayout(self)
        tip = QLabel('Every way of the hands, in the order they happen. Choose one to shape it: drag its purple '
                     'keyframes (double-click the path to add one, right-click to remove one). The other ways are '
                     'the dashed lines. Play goes through them all.')
        tip.setWordWrap(True)
        layout.addWidget(tip)
        split = QSplitter()
        self.list = QListWidget()
        for mv in self.moves:
            t0, t1 = mv['times']
            self.list.addItem(f"{t0:.1f}–{t1:.1f} s   Element {mv['k'] + 1}: "
                              + ('to the drawing' if mv['which'] == 'in' else 'back to the corner'))
        self.list.setMinimumWidth(330)
        split.addWidget(self.list)
        self.canvas = PathsCanvas()
        split.addWidget(self.canvas)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        reset = QPushButton('Back to the preset'); reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addWidget(QLabel('Try:'))
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setRange(0, 100)
        self.slider.valueChanged.connect(self.tried)
        row.addWidget(self.slider, 1)
        play = QPushButton('Play this one'); play.clicked.connect(lambda: self.play(False))
        row.addWidget(play)
        play_all = QPushButton('Play all'); play_all.clicked.connect(lambda: self.play(True))
        row.addWidget(play_all)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self); self.timer.timeout.connect(self._step)
        self.all = False
        self.current = -1
        self.list.currentRowChanged.connect(self.choose)
        self.list.setCurrentRow(0)

    def _keep(self):
        if 0 <= self.current < len(self.moves):
            self.moves[self.current]['edit'] = list(self.canvas.keys)

    def choose(self, row):
        self._keep()
        if not 0 <= row < len(self.moves):
            return
        self.current = row
        mv = self.moves[row]
        c = self.canvas
        c.frame, c.a, c.b, c.keys, c.style, c.hand = mv['image'], tuple(mv['a']), tuple(mv['b']), \
            list(mv['edit']), mv['style'], mv['hand']
        c.others = [(o['a'], o['b'], o['edit'], f"{o['k'] + 1} " + ('in' if o['which'] == 'in' else 'back'),
                     o['times'][1] <= mv['times'][0])
                    for i, o in enumerate(self.moves) if i != row]
        c.try_at = self.slider.value() / 100.
        c.update()

    def reset(self):
        if 0 <= self.current < len(self.moves):
            self.canvas.keys = list(self.moves[self.current]['preset']); self.canvas.update()

    def tried(self, value):
        self.canvas.try_at = value / 100.; self.canvas.update()

    def play(self, everything):
        self.all = everything
        if everything:
            self.list.setCurrentRow(0)
        self.slider.setValue(0)
        self.timer.start(25)

    def _step(self):
        mv = self.moves[self.current] if 0 <= self.current < len(self.moves) else None
        seconds = max(.2, (mv['times'][1] - mv['times'][0])) if mv else 1.
        step = max(1, round(100 * .025 / seconds))       # about its real speed
        if self.slider.value() >= 100:
            if self.all and self.current + 1 < len(self.moves):
                self.list.setCurrentRow(self.current + 1); self.slider.setValue(0); return
            self.timer.stop(); return
        self.slider.setValue(min(100, self.slider.value() + step))

    def changed(self):
        """{(element, 'in' / 'out'): keyframes (None: back to the preset)} of the ways changed."""
        self._keep()
        out = {}
        for mv in self.moves:
            now = [tuple(round(v, 4) for v in k) for k in mv['edit']]
            preset = [tuple(round(v, 4) for v in k) for k in mv['preset']]
            before = [tuple(round(v, 4) for v in k) for k in mv['keys']] if mv['keys'] else None
            new = None if now == preset else now
            if new != before:
                out[(mv['k'], mv['which'])] = new
        return out


class MotionCanvas(PathCanvas):
    """exp.224 (the user): a Hand motion: from the corner (green) through points anywhere
    (frame pixels, also outside the picture) and back to the corner."""

    def points(self):
        return [self.a] + list(self.keys) + [self.b]

    def line(self, steps=24):
        from frame_render import spline
        return spline(self.points(), steps)

    def key_of(self, spot):
        return (float(spot[0]), float(spot[1]))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and len(self.keys) <= 1:
            return                                   # at least one point to go to
        super().mousePressEvent(event)


class HandMotionDialog(QDialog):
    """exp.224: double-click a Hand motion clip: when, how long, how it moves, and its path."""

    def __init__(self, parent, frame, home, keys, hand, start, length, how, styles, preset):
        from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout
        super().__init__(parent)
        self.setWindowTitle('Hand motion')
        self.preset = [tuple(k) for k in preset]
        layout = QVBoxLayout(self)
        help_text = QLabel('The waiting hand leaves its corner (green), goes through the purple points and comes '
                           'back. Drag the points anywhere, also outside the video (the dashed edge). Double-click '
                           'the path to add a point, right-click one to remove it. No picture is needed.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QFormLayout()

        def number(value, low, high):
            box = QDoubleSpinBox(); box.setRange(low, high); box.setSingleStep(.1); box.setDecimals(1)
            box.setSuffix(' s'); box.setValue(float(value)); return box
        self.start = number(start, 0, 3600)
        self.length = number(length, .4, 600)
        self.how = QComboBox(); self.how.addItems(list(styles))
        self.how.setCurrentText(how if how in styles else 'Smooth')
        form.addRow('Starts', self.start)
        form.addRow('Length', self.length)
        form.addRow('How it moves', self.how)
        layout.addLayout(form)
        self.canvas = MotionCanvas(frame, home, home, keys)
        self.canvas.hand = hand
        self.canvas.style = self.how.currentText()
        self.how.currentTextChanged.connect(self._style)
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        reset = QPushButton('Back to the start'); reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addWidget(QLabel('Try:'))
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(lambda v: (setattr(self.canvas, 'try_at', v / 1000.), self.canvas.update()))
        row.addWidget(self.slider, 1)
        play = QPushButton('Play'); play.clicked.connect(self.play)
        row.addWidget(play)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.remove = buttons.addButton('Delete', QDialogButtonBox.ButtonRole.DestructiveRole)
        self.deleted = False
        self.remove.clicked.connect(lambda: (setattr(self, 'deleted', True), self.accept()))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self); self.timer.timeout.connect(self._step)

    def _style(self, text):
        self.canvas.style = text; self.canvas.update()

    def reset(self):
        self.canvas.keys = list(self.preset); self.canvas.update()

    def play(self):
        """At the clip's own speed (its Length)."""
        import time
        self._t0 = time.monotonic(); self.slider.setValue(0); self.timer.start(20)

    def _step(self):
        import time
        u = (time.monotonic() - self._t0) / max(.2, self.length.value())
        self.slider.setValue(min(1000, round(u * 1000)))
        if u >= 1:
            self.timer.stop()
