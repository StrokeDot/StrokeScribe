"""Set camera (exp.200, the user, like VideoScribe): the whole board seen from above, with a
frame for what the camera shows for one element. Drag the frame to move it, mouse wheel on it
(or the slider) to go closer or further; Set camera keeps it for that element.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)


class BoardFrame(QWidget):
    changed = Signal()

    def __init__(self, image, view, frame, aspect, page):
        super().__init__()
        self.image, self.board_view, self.aspect = image, view, aspect
        self.frame = list(frame)            # cx, cy, w in board units
        self.page = page                    # the element's page (dashed)
        self._drag = None
        self.setMinimumSize(720, round(720 * image.height() / max(1, image.width())))
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # board <-> widget
    def _scale(self):
        return self.width() / self.board_view[2]

    def to_widget(self, x, y):
        vx, vy, vw = self.board_view
        s = self._scale()
        return (x - (vx - vw / 2)) * s, (y - (vy - vw * self.aspect / 2)) * s

    def to_board(self, px, py):
        vx, vy, vw = self.board_view
        s = self._scale()
        return vx - vw / 2 + px / s, vy - vw * self.aspect / 2 + py / s

    def rect_of(self, f):
        x0, y0 = self.to_widget(f[0] - f[2] / 2, f[1] - f[2] * self.aspect / 2)
        x1, y1 = self.to_widget(f[0] + f[2] / 2, f[1] + f[2] * self.aspect / 2)
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(self.rect(), QPixmap.fromImage(self.image))
        p.setPen(QPen(QColor(150, 150, 170), 1.2, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect_of(self.page))
        r = self.rect_of(self.frame)
        shade = QColor(10, 10, 16, 120)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(shade)
        full = QRectF(self.rect())
        for part in (QRectF(0, 0, full.width(), r.top()), QRectF(0, r.bottom(), full.width(), full.height() - r.bottom()),
                     QRectF(0, r.top(), r.left(), r.height()), QRectF(r.right(), r.top(), full.width() - r.right(), r.height())):
            p.drawRect(part)
        p.setPen(QPen(QColor('#FFB020'), 2.5)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
        tag = QRectF(r.left(), r.top() - 22, 70, 20)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#FFB020')); p.drawRoundedRect(tag, 5, 5)
        p.setPen(QColor('#1A1A1A')); p.drawText(tag, Qt.AlignmentFlag.AlignCenter, 'Camera')
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = (event.position(), tuple(self.frame))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        start, f = self._drag
        s = self._scale()
        d = event.position() - start
        self.frame[0], self.frame[1] = f[0] + d.x() / s, f[1] + d.y() / s
        self.update(); self.changed.emit()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event):
        step = 1.12 if event.angleDelta().y() < 0 else 1 / 1.12
        self.set_width(self.frame[2] * step)
        event.accept()

    def set_width(self, w):
        self.frame[2] = max(self.page[2] * .1, min(self.board_view[2] * 1.5, float(w)))
        self.update(); self.changed.emit()


class SetCameraDialog(QDialog):
    def __init__(self, parent, image, board_view, frame, page, aspect, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.page = tuple(page)
        box = QVBoxLayout(self)
        help_ = QLabel('Drag the orange frame to where the camera should look; mouse wheel (or the slider) '
                       'to go closer or further. The dashed frame is the element\'s page.')
        help_.setWordWrap(True); box.addWidget(help_)
        self.board = BoardFrame(image, board_view, frame, aspect, page)
        box.addWidget(self.board, 1)
        row = QHBoxLayout(); box.addLayout(row)
        row.addWidget(QLabel('Closer'))
        self.zoom = QSlider(Qt.Orientation.Horizontal); self.zoom.setRange(10, 300)
        row.addWidget(self.zoom, 1); row.addWidget(QLabel('Further'))
        self.zoom.setValue(round(frame[2] / page[2] * 100))
        self.zoom.valueChanged.connect(lambda v: self.board.set_width(self.page[2] * v / 100.))
        self.board.changed.connect(self._sync)
        whole = QPushButton('The whole page'); whole.setToolTip('The camera shows the element\'s whole page (as before).')
        whole.clicked.connect(self.reset)
        row.addWidget(whole)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Set camera')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self.cleared = False

    def _sync(self):
        self.zoom.blockSignals(True)
        self.zoom.setValue(round(self.board.frame[2] / self.page[2] * 100))
        self.zoom.blockSignals(False)

    def reset(self):
        self.board.frame = list(self.page); self.board.update(); self._sync(); self.cleared = True

    def chosen(self):
        """(cx, cy, w), or None for the whole page."""
        f = tuple(round(v, 5) for v in self.board.frame)
        if all(abs(a - b) < 1e-4 for a, b in zip(f, self.page)):
            return None
        return f
