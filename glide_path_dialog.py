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
        line = path_polyline(self.a, self.b, self.keys)
        path = QPainterPath(self.to_widget(line[0]))
        for q in line[1:]:
            path.lineTo(self.to_widget(q))
        p.setPen(QPen(QColor(255, 255, 255, 200), 5)); p.drawPath(path)
        p.setPen(QPen(QColor('#e5484d'), 2.5)); p.drawPath(path)
        for i, q in enumerate(self.points()):
            c = self.to_widget(q)
            if i == 0 or i == len(self.keys) + 1:
                p.setPen(QPen(QColor('white'), 2)); p.setBrush(QColor('#2ecc71' if i == 0 else '#e5484d'))
                p.drawEllipse(c, 7, 7)
            else:
                p.setPen(QPen(QColor('white'), 2)); p.setBrush(QColor('#6c5ce7'))
                p.drawEllipse(c, 9, 9)
        if self.try_at is not None:
            spot = _along_polyline(line, _glide_ease(self.try_at, self.style))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#ffd166')); p.drawEllipse(self.to_widget(spot), 8, 8)
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
            from frame_render import to_keyframe
            self.keys[self.drag] = to_keyframe(self.a, self.b, self.to_frame(event.position()))
            self.update()
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._key_at(event.position()) is not None
                           else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseDoubleClickEvent(self, event):
        """A new keyframe where the path was double-clicked (between the two around it)."""
        from frame_render import path_polyline, to_keyframe
        spot = self.to_frame(event.position())
        new = to_keyframe(self.a, self.b, spot)
        # put it in order along the way: after the keyframes that come before it on the path
        line = path_polyline(self.a, self.b, self.keys, 24)
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
        self.slider.setValue(0); self.timer.start(20)

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
