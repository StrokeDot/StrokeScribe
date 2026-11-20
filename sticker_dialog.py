"""exp.60 (the user: a sticker double-clicked opens its own window, like Set camera or the
picture's, with what is around it; size, rotation, colour and shadow).

The window shows the video at a moment of the sticker (everything else in it: the elements,
the other stickers and texts) and the sticker drawn on top exactly as the video draws it.
Drag it to move it, drag a corner (or the mouse wheel) to make it bigger or smaller, drag the
round handle above it to turn it (Shift: steps of 15°). The settings on the right change it
live; Apply keeps the changes, Cancel leaves the sticker as it was."""

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

import overlays
import stickers

# what the window may change (copied back to the sticker on Apply)
KEYS = ('shape', 'name', 'aspect', 'color', 'thickness', 'size', 'rotation', 'flip', 'x', 'y', 'shadow')


def _shadow_settings(item):
    """The sticker's shadow with every setting (on: False when it has none)."""
    sh = dict(overlays.SHADOW, on=False)
    sh.update(item.get('shadow') or {})
    return sh


class StickerCanvas(QWidget):
    """The moment of the video with the sticker on top, to move, resize and turn it."""
    changed = Signal()

    HANDLE = 26          # the rotate handle: pixels above the box

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.base = None            # QImage W × H: the video at this moment, without the sticker
        self.page = (0., 0., 1., 1.)  # the sticker's page in base pixels (x, y, w, h)
        self.t = 0.
        self._drag = None
        self.setMinimumSize(560, 330)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------ geometry
    def target(self):
        """Where the base picture is drawn in the widget, and its scale."""
        if self.base is None:
            return QRectF(self.rect()), 1.
        W, H = self.base.width(), self.base.height()
        k = min((self.width() - 16) / W, (self.height() - 16) / H)
        w, h = W * k, H * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), k

    def _map(self):
        """(ox, oy, s): a point (px, py) of the sticker's layer (W × H) is at ox + px * s, oy + py * s."""
        r, k = self.target()
        W = self.base.width() if self.base is not None else 1
        px, py, pw, ph = self.page
        s = pw / max(1., W) * k
        return r.x() + px * k, r.y() + py * k, s

    def frame(self):
        """(centre, half width, half height, angle in radians) of the sticker's box in widget pixels."""
        item = self.dialog.item
        W = self.base.width() if self.base is not None else 960
        H = self.base.height() if self.base is not None else 540
        bx, by, bw, bh = overlays.box(item, W, H)
        ox, oy, s = self._map()
        c = QPointF(ox + (bx + bw / 2) * s, oy + (by + bh / 2) * s)
        return c, bw * s / 2 + 6, bh * s / 2 + 6, math.radians(float(item.get('rotation', 0) or 0))

    def corners(self):
        c, hw, hh, a = self.frame()
        ca, sa = math.cos(a), math.sin(a)
        pts = []
        for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
            pts.append(QPointF(c.x() + x * ca - y * sa, c.y() + x * sa + y * ca))
        return pts

    def handle(self):
        c, hw, hh, a = self.frame()
        d = hh + self.HANDLE
        return QPointF(c.x() + d * math.sin(a), c.y() - d * math.cos(a))

    def inside(self, pos):
        c, hw, hh, a = self.frame()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        ca, sa = math.cos(-a), math.sin(-a)
        x, y = dx * ca - dy * sa, dx * sa + dy * ca
        return abs(x) <= hw + 4 and abs(y) <= hh + 4

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor('#1b1d23'))
        if self.base is None:
            p.end(); return
        r, k = self.target()
        # a light checker under a transparent video
        p.save(); p.setClipRect(r)
        size = 14
        for j in range(int(r.height() // size) + 1):
            for i in range(int(r.width() // size) + 1):
                p.fillRect(QRectF(r.x() + i * size, r.y() + j * size, size, size),
                           QColor('#e9ecef') if (i + j) % 2 == 0 else QColor('#d5d9de'))
        p.restore()
        p.drawImage(r, self.base)
        W, H = self.base.width(), self.base.height()
        layer = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied); layer.fill(0)
        overlays.paint(layer, [self.dialog.item], self.t, hands=False)
        px, py, pw, ph = self.page
        p.drawImage(QRectF(r.x() + px * k, r.y() + py * k, pw * k, ph * k), layer)
        # the box, its corners and the rotate handle
        accent = QColor('#7c6cff')
        pts = self.corners()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 190), 3)); p.drawPolygon(QPolygonF(pts))
        p.setPen(QPen(accent, 1.6, Qt.PenStyle.DashLine)); p.drawPolygon(QPolygonF(pts))
        top = QPointF((pts[0].x() + pts[1].x()) / 2, (pts[0].y() + pts[1].y()) / 2)
        h = self.handle()
        p.setPen(QPen(accent, 1.6)); p.drawLine(top, h)
        p.setBrush(QColor('white'))
        for q in pts:
            p.drawRect(QRectF(q.x() - 5, q.y() - 5, 10, 10))
        p.setBrush(accent); p.setPen(QPen(QColor('white'), 2)); p.drawEllipse(h, 7, 7)
        p.end()

    # ------------------------------------------------------------------ mouse
    def _near(self, a, b, d=10):
        return abs(a.x() - b.x()) <= d and abs(a.y() - b.y()) <= d

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.base is None:
            return
        pos = event.position()
        item = self.dialog.item
        c, _, _, _ = self.frame()
        if self._near(pos, self.handle(), 12):
            self._drag = ('rotate', math.atan2(pos.y() - c.y(), pos.x() - c.x()), float(item.get('rotation', 0) or 0))
        elif any(self._near(pos, q) for q in self.corners()):
            self._drag = ('size', max(4., math.hypot(pos.x() - c.x(), pos.y() - c.y())), float(item.get('size', .3)))
        elif self.inside(pos):
            self._drag = ('move', pos, float(item.get('x', .5)), float(item.get('y', .5)))
        else:
            self._drag = None
        event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._drag is None:
            if self.base is None:
                return
            if self._near(pos, self.handle(), 12):
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif any(self._near(pos, q) for q in self.corners()):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif self.inside(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.unsetCursor()
            return
        item = self.dialog.item
        c, _, _, _ = self.frame()
        kind = self._drag[0]
        if kind == 'move':
            _, p0, x0, y0 = self._drag
            ox, oy, s = self._map()
            W, H = self.base.width(), self.base.height()
            item['x'] = round(x0 + (pos.x() - p0.x()) / max(1e-6, s * W), 4)
            item['y'] = round(y0 + (pos.y() - p0.y()) / max(1e-6, s * H), 4)
        elif kind == 'size':
            _, d0, size0 = self._drag
            d = math.hypot(pos.x() - c.x(), pos.y() - c.y())
            item['size'] = round(max(.02, min(1.5, size0 * d / d0)), 4)
        elif kind == 'rotate':
            _, a0, r0 = self._drag
            a = math.atan2(pos.y() - c.y(), pos.x() - c.x())
            r = r0 + math.degrees(a - a0)
            r = (r + 180.) % 360. - 180.
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                r = round(r / 15.) * 15.
            item['rotation'] = round(r, 1)
        self.changed.emit(); self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.
        if not steps:
            return
        item = self.dialog.item
        item['size'] = round(max(.02, min(1.5, float(item.get('size', .3)) * (1.06 ** steps))), 4)
        self.changed.emit(); self.update(); event.accept()


class StickerDialog(QDialog):
    """moment(item, t) -> (base QImage, page rect): the video at t without this sticker."""

    def __init__(self, parent, item, moment, t):
        super().__init__(parent)
        self.original = item
        self.item = copy.deepcopy(item)
        self.moment = moment
        self.setWindowTitle(f'Sticker · {item.get("name") or item.get("shape", "sticker")}')
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1180, 700)
        self._filling = False
        root = QVBoxLayout(self); root.setContentsMargins(14, 12, 14, 12); root.setSpacing(10)
        help_ = QLabel('Drag the sticker to move it, drag a corner (or the mouse wheel) to make it bigger or smaller, '
                       'drag the round handle to turn it (Shift: steps of 15°). Around it: the video at that moment.')
        help_.setWordWrap(True)
        root.addWidget(help_)
        body = QHBoxLayout(); body.setSpacing(14)
        left = QVBoxLayout(); left.setSpacing(6)
        self.canvas = StickerCanvas(self)
        self.canvas.changed.connect(self.sync)
        left.addWidget(self.canvas, 1)
        # the moment shown (inside the sticker's clip)
        start, length = float(item.get('start', 0)), max(.1, float(item.get('duration', 3)))
        self.start, self.length = start, length
        row = QHBoxLayout(); row.addWidget(QLabel('Moment'))
        self.when = QSlider(Qt.Orientation.Horizontal); self.when.setRange(0, 1000)
        self.when.setValue(round(1000 * max(0., min(1., (t - start) / length))))
        self.when_label = QLabel('')
        row.addWidget(self.when, 1); row.addWidget(self.when_label)
        left.addLayout(row)
        self._moment_timer = QTimer(self); self._moment_timer.setSingleShot(True); self._moment_timer.setInterval(120)
        self._moment_timer.timeout.connect(self.load_moment)
        self.when.valueChanged.connect(lambda v: (self._show_when(), self._moment_timer.start()))
        body.addLayout(left, 3)

        side = QWidget(); side.setMinimumWidth(330); form = QFormLayout(side)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.shape = QComboBox(); self.shape.addItems(stickers.SHAPES)
        form.addRow('Shape', self.shape)
        self.color = QPushButton(); self.color.setObjectName('colorButton')
        form.addRow('Colour', self.color)
        self.size = self._slider(form, 'Size', 2, 150, ' %')
        self.aspect = self._slider(form, 'Height', 2, 200, ' %')
        self.thickness = self._slider(form, 'Thickness', 1, 40, '', 1)
        self.rotation = self._slider(form, 'Rotation', -180, 180, '°')
        turns = QHBoxLayout()
        for label, step in (('⟲ 15°', -15), ('⟳ 15°', 15), ('⟲ 90°', -90), ('⟳ 90°', 90)):
            b = QPushButton(label); b.clicked.connect(lambda checked=False, s=step: self.turn(s)); turns.addWidget(b)
        form.addRow('', turns)
        self.flip = QCheckBox('Mirrored (left ↔ right)')
        form.addRow('', self.flip)
        head = QLabel('SHADOW'); head.setObjectName('sectionLabel')
        form.addRow(head)
        self.shadow = QCheckBox('Shadow under the sticker')
        form.addRow('', self.shadow)
        self.shadow_color = QPushButton(); self.shadow_color.setObjectName('colorButton')
        form.addRow('Shadow colour', self.shadow_color)
        self.shadow_opacity = self._slider(form, 'Strength', 0, 100, ' %')
        self.shadow_blur = self._slider(form, 'Softness', 0, 40, '', 1)
        self.shadow_distance = self._slider(form, 'Distance', 0, 60, '', 1)
        self.shadow_angle = self._slider(form, 'Direction', 0, 359, '°')
        body.addWidget(side, 2)
        root.addLayout(body, 1)

        buttons = QHBoxLayout(); buttons.addStretch(1)
        reset = QPushButton('As it was'); reset.setToolTip('Every change in this window undone.')
        reset.clicked.connect(self.reset)
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject)
        ok = QPushButton('Apply'); ok.setDefault(True); ok.clicked.connect(self.accept)
        for b in (reset, cancel, ok):
            buttons.addWidget(b)
        root.addLayout(buttons)

        self.shape.currentTextChanged.connect(self.set_shape)
        self.color.clicked.connect(lambda checked=False: self.pick('color'))
        self.shadow_color.clicked.connect(lambda checked=False: self.pick('shadow'))
        self.size.valueChanged.connect(lambda v: self.set(size=round(v / 100, 4)))
        self.aspect.valueChanged.connect(lambda v: self.set(aspect=round(v / 100, 4)))
        self.thickness.valueChanged.connect(lambda v: self.set(thickness=round(v / 1000, 4)))
        self.rotation.valueChanged.connect(lambda v: self.set(rotation=round(v, 1)))
        self.flip.toggled.connect(lambda on: self.set(flip=bool(on)))
        self.shadow.toggled.connect(lambda on: self.set_shadow(on=bool(on)))
        self.shadow_opacity.valueChanged.connect(lambda v: self.set_shadow(opacity=round(v / 100, 3)))
        self.shadow_blur.valueChanged.connect(lambda v: self.set_shadow(blur=round(v / 1000, 4)))
        self.shadow_distance.valueChanged.connect(lambda v: self.set_shadow(distance=round(v / 1000, 4)))
        self.shadow_angle.valueChanged.connect(lambda v: self.set_shadow(angle=round(v, 1)))
        self.sync()
        self.load_moment()

    # ------------------------------------------------------------------ building
    def _slider(self, form, title, lo, hi, suffix, decimals=0):
        box = QDoubleSpinBox(); box.setRange(lo, hi); box.setDecimals(decimals); box.setSuffix(suffix)
        box.setSingleStep(1 if not decimals else .5); box.setKeyboardTracking(False)
        slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(int(lo * 10), int(hi * 10))
        slider.valueChanged.connect(lambda v: box.setValue(v / 10.))
        box.valueChanged.connect(lambda v: (slider.blockSignals(True), slider.setValue(round(v * 10)),
                                            slider.blockSignals(False)))
        holder = QWidget(); line = QHBoxLayout(holder); line.setContentsMargins(0, 0, 0, 0); line.setSpacing(8)
        box.setFixedWidth(100); line.addWidget(box); line.addWidget(slider, 1)
        form.addRow(title, holder)
        box.slider = slider
        return box

    # ------------------------------------------------------------------ the moment
    def time(self):
        return self.start + self.length * self.when.value() / 1000.

    def _show_when(self):
        self.when_label.setText(f'{self.time():.2f} s')

    def load_moment(self):
        t = self.time()
        self._show_when()
        try:
            base, page = self.moment(self.item, t)
        except Exception as exc:
            import applog; applog.error('Sticker window: the moment', exc)
            base, page = None, None
        if base is None:
            base = QImage(960, 540, QImage.Format.Format_ARGB32_Premultiplied); base.fill(0)
        self.canvas.base = base
        self.canvas.page = page or (0., 0., float(base.width()), float(base.height()))
        self.canvas.t = t
        self.canvas.update()

    # ------------------------------------------------------------------ changes
    def set(self, **values):
        if self._filling:
            return
        self.item.update(values)
        self.canvas.update()

    def set_shape(self, shape):
        if self._filling or shape == self.item.get('shape'):
            return
        values = dict(shape=shape, name=shape, aspect=stickers.ASPECT[shape])
        import sticker_art
        if shape in sticker_art.RICH:                 # as the Stickers panel: its own colour and line
            values.update(color=sticker_art.COLOR[shape], thickness=sticker_art.THICKNESS[shape])
        self.item.update(values)
        self.sync(); self.canvas.update()

    def set_shadow(self, **values):
        if self._filling:
            return
        sh = _shadow_settings(self.item)
        if values and 'on' not in values:
            sh['on'] = True                            # changing it means you want it
        sh.update(values)
        self.item['shadow'] = sh
        self.sync(); self.canvas.update()

    def turn(self, step):
        r = float(self.item.get('rotation', 0) or 0) + step
        self.item['rotation'] = round((r + 180.) % 360. - 180., 1)
        self.sync(); self.canvas.update()

    def pick(self, which):
        if which == 'color':
            now = QColor(self.item.get('color', '#E0463C'))
        else:
            now = QColor((self.item.get('shadow') or {}).get('color', overlays.SHADOW['color']))
        colour = QColorDialog.getColor(now, self, 'Sticker colour' if which == 'color' else 'Shadow colour')
        if not colour.isValid():
            return
        if which == 'color':
            self.item['color'] = colour.name(); self.sync(); self.canvas.update()
        else:
            self.set_shadow(color=colour.name())

    def reset(self):
        self.item = copy.deepcopy(self.original)
        self.sync(); self.canvas.update()

    def sync(self):
        """The settings show the sticker as it is now."""
        item = self.item
        self._filling = True
        try:
            self.shape.setCurrentText(item.get('shape', 'Arrow'))
            colour = item.get('color', '#E0463C')
            self.color.setText(colour.upper())
            self.color.setStyleSheet(f'QPushButton#colorButton {{ border-left: 18px solid {colour}; }}')
            self.size.setValue(float(item.get('size', .3)) * 100)
            self.aspect.setValue(float(item.get('aspect', .4)) * 100)
            self.thickness.setValue(float(item.get('thickness', .012)) * 1000)
            self.rotation.setValue(float(item.get('rotation', 0) or 0))
            self.flip.setChecked(bool(item.get('flip')))
            sh = _shadow_settings(item)
            self.shadow.setChecked(bool(sh.get('on')))
            self.shadow_color.setText(str(sh['color']).upper())
            self.shadow_color.setStyleSheet(f'QPushButton#colorButton {{ border-left: 18px solid {sh["color"]}; }}')
            self.shadow_opacity.setValue(float(sh['opacity']) * 100)
            self.shadow_blur.setValue(float(sh['blur']) * 1000)
            self.shadow_distance.setValue(float(sh['distance']) * 1000)
            self.shadow_angle.setValue(float(sh['angle']) % 360)
            for box in (self.shadow_color, self.shadow_opacity, self.shadow_blur, self.shadow_distance, self.shadow_angle):
                box.setEnabled(bool(sh.get('on')))
                if hasattr(box, 'slider'):
                    box.slider.setEnabled(bool(sh.get('on')))
        finally:
            self._filling = False

    def values(self):
        """What changed, to put on the sticker ({} when nothing did)."""
        out = {}
        for key in KEYS:
            if key in self.item and self.item.get(key) != self.original.get(key):
                out[key] = copy.deepcopy(self.item[key])
        return out
