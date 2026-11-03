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

    def __init__(self, image, view, frame, aspect, page, picture=None, place=None):
        super().__init__()
        self.image, self.board_view, self.aspect = image, view, aspect
        self._pixmap = QPixmap.fromImage(image)       # exp.202: made once (it lagged on every move)
        self.frame = list(frame)            # cx, cy, w in board units
        self.page = page                    # the element's page (dashed)
        # exp.202 (the user): the picture's own place, moved apart from the camera.
        # picture: the element alone on its page (a QImage of the page); place: [x %, y %, size %]
        self.picture = QPixmap.fromImage(picture) if picture is not None else None
        self.place0 = list(place) if place else [0., 0., 100.]
        self.place = list(self.place0)
        self.mode = 'camera'
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
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), self._pixmap)
        page = self.rect_of(self.page)
        if self.picture is not None:
            # the picture where it is now: moved by its place, sized about the page's middle
            k = self.place[2] / max(1e-6, self.place0[2])
            c = page.center()
            old = QPointF(c.x() + self.place0[0] / 100. * page.width(), c.y() + self.place0[1] / 100. * page.height())
            new = QPointF(c.x() + self.place[0] / 100. * page.width(), c.y() + self.place[1] / 100. * page.height())
            # the page picture scaled about the picture's own middle, which goes to its new place
            target = QRectF(new.x() - (old.x() - page.left()) * k, new.y() - (old.y() - page.top()) * k,
                            page.width() * k, page.height() * k)
            p.drawPixmap(target, self.picture, QRectF(self.picture.rect()))
            if self.mode == 'picture':
                bw, bh = page.width() * .82 * self.place[2] / 100., page.height() * .78 * self.place[2] / 100.
                p.setPen(QPen(QColor('#6E4FF2'), 2, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(new.x() - bw / 2, new.y() - bh / 2, bw, bh))
        p.setPen(QPen(QColor(150, 150, 170), 1.2, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(page)
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
            self._drag = (event.position(), tuple(self.frame) if self.mode == 'camera' else tuple(self.place))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        start, f = self._drag
        s = self._scale()
        d = event.position() - start
        if self.mode == 'picture':
            page = self.rect_of(self.page)
            self.place[0] = f[0] + d.x() / max(1., page.width()) * 100.
            self.place[1] = f[1] + d.y() / max(1., page.height()) * 100.
            self.update(); self.changed.emit(); return
        self.frame[0], self.frame[1] = f[0] + d.x() / s, f[1] + d.y() / s
        self.update(); self.changed.emit()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event):
        step = 1.12 if event.angleDelta().y() < 0 else 1 / 1.12
        if self.mode == 'picture':
            self.place[2] = max(10., min(300., self.place[2] / step))
            self.update(); self.changed.emit(); event.accept(); return
        self.set_width(self.frame[2] * step)
        event.accept()

    def set_width(self, w):
        self.frame[2] = max(self.page[2] * .1, min(self.board_view[2] * 1.5, float(w)))
        self.update(); self.changed.emit()


class SetCameraDialog(QDialog):
    def __init__(self, parent, image, board_view, frame, page, aspect, title, others=(), picture=None, place=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.page = tuple(page)
        box = QVBoxLayout(self)
        help_ = QLabel('Move the camera: drag the orange frame, mouse wheel (or the slider) to go closer or '
                       'further. Move the picture: drag this element\'s picture where it goes on the page, mouse '
                       'wheel to make it bigger or smaller. The dashed frame is the element\'s page.')
        help_.setWordWrap(True); box.addWidget(help_)
        self.board = BoardFrame(image, board_view, frame, aspect, page, picture, place)
        if picture is not None:
            # exp.202 (the user): the camera and the picture's place are two things
            modes = QHBoxLayout(); box.addLayout(modes)
            self.mode_buttons = {}
            for key, text, tip in (('camera', 'Move the camera', 'Drag / wheel: where the camera looks.'),
                                   ('picture', 'Move the picture', 'Drag / wheel: where this element\'s picture '
                                                                   'is on the page, and how big.')):
                b = QPushButton(text); b.setCheckable(True); b.setToolTip(tip); b.setChecked(key == 'camera')
                b.clicked.connect(lambda checked=False, k=key: self.set_mode(k))
                modes.addWidget(b); self.mode_buttons[key] = b
            modes.addStretch(1)
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
        # exp.201 (the user): Match camera: the same camera as another element
        if others:
            from PySide6.QtWidgets import QComboBox
            match = QHBoxLayout(); box.addLayout(match)
            match.addWidget(QLabel('Match camera of'))
            self.match = QComboBox(); self.match.addItem('—', None)
            for name, view in others:
                self.match.addItem(name, list(view))
            self.match.setToolTip('The camera looks exactly where another element\'s camera looks.')
            self.match.currentIndexChanged.connect(self._match)
            match.addWidget(self.match, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Set camera')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self.cleared = False

    def set_mode(self, key):
        self.board.mode = key
        for k, b in self.mode_buttons.items():
            b.setChecked(k == key)
        self.board.update()

    def picture_place(self):
        """[x %, y %, size %] of the picture, or None when it did not move."""
        p = [round(v, 1) for v in self.board.place]
        return None if all(abs(a - b) < .05 for a, b in zip(p, self.board.place0)) else p

    def _match(self, i):
        view = self.match.itemData(i)
        if view:
            self.board.frame = list(view); self.board.update(); self._sync()

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
