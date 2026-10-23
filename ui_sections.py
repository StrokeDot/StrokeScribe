"""Filmora-style panel sections: a header you click to open or close, an optional
on/off switch on the header, and the settings underneath.

    section = Section('Painting hand', switch=w.show_paint_hand)
    panel_layout.addWidget(section)
    form = form_layout(); section.body.addLayout(form)

The switch is a copy of an existing check box (kept in step both ways), so the
check box can stay where projects, undo and tests expect it.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


def _colours():
    try:
        import theme
        return theme.colors()
    except Exception:
        return {'accent': '#7C5CFF', 'raised': '#2A2833', 'muted': '#A9A6B8', 'text': '#ECEAF4',
                'border': '#3A3744', 'panel': '#1E1D24'}


class ToggleSwitch(QAbstractButton):
    """A small on/off switch (a pill with a knob) for a check box `source`: it always
    shows the check box's own state (also after a project or undo restored it
    quietly) and clicking it flips the check box."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(34, 18)
        self.clicked.connect(lambda checked=False: self.source.setChecked(not self.source.isChecked()))
        source.toggled.connect(lambda on: self.update())

    def isChecked(self):
        return self.source.isChecked()

    def isEnabled(self):
        return super().isEnabled() and self.source.isEnabled()

    def sizeHint(self):
        return QSize(34, 18)

    def paintEvent(self, event):
        c = _colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QColor(c['accent']) if on else QColor(c.get('border', '#3A3744'))
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 9, 9)
        p.setBrush(QColor('white') if self.isEnabled() else QColor(200, 200, 200))
        x = self.width() - 16 if on else 2
        p.drawEllipse(QRectF(x, 2, 14, 14))
        p.end()


class _Caret(QWidget):
    """A small triangle: pointing right when closed, down when open."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.open = False
        self.setFixedSize(12, 12)

    def paintEvent(self, event):
        c = _colours()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c.get('muted', '#A9A6B8')))
        path = QPainterPath()
        if self.open:
            path.moveTo(QPointF(2, 4)); path.lineTo(QPointF(10, 4)); path.lineTo(QPointF(6, 9))
        else:
            path.moveTo(QPointF(4, 2)); path.lineTo(QPointF(9, 6)); path.lineTo(QPointF(4, 10))
        path.closeSubpath()
        p.drawPath(path)
        p.end()


class _Header(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Section(QWidget):
    """A section of a side panel that opens and closes."""
    toggled = Signal(bool)

    def __init__(self, title, expanded=False, switch=None, tip=''):
        super().__init__()
        self.setObjectName('panelSection')
        self.setMinimumWidth(0)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.header = _Header(); self.header.setObjectName('sectionHeader')
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        if tip:
            self.header.setToolTip(tip)
        row = QHBoxLayout(self.header); row.setContentsMargins(8, 8, 8, 8); row.setSpacing(8)
        self.switch = None
        if switch is not None:
            self.switch = ToggleSwitch(switch)
            self.switch.setToolTip(switch.toolTip() or f'{title} on / off')
            row.addWidget(self.switch)
        self.title = QLabel(title); self.title.setObjectName('sectionHeaderTitle')
        row.addWidget(self.title)
        self.caret = _Caret()
        row.addWidget(self.caret)
        row.addStretch(1)
        outer.addWidget(self.header)
        self.content = QWidget(); self.content.setObjectName('sectionBody'); self.content.setMinimumWidth(0)
        self.body = QVBoxLayout(self.content); self.body.setContentsMargins(6, 6, 2, 10); self.body.setSpacing(8)
        outer.addWidget(self.content)
        self.header.clicked.connect(lambda: self.set_expanded(not self.expanded))
        self.expanded = None
        self.set_expanded(expanded)

    def setText(self, text):
        self.title.setText(text)

    def text(self):
        return self.title.text()

    def attach_switch(self, source, tip=''):
        """Add the on/off switch for check box `source` (when it is made after the section)."""
        if self.switch is not None:
            return self.switch
        self.switch = ToggleSwitch(source)
        self.switch.setToolTip(tip or source.toolTip() or 'On / off')
        self.header.layout().insertWidget(0, self.switch)
        return self.switch

    def set_expanded(self, on):
        on = bool(on)
        if on == self.expanded:
            return
        self.expanded = on
        self.content.setVisible(on)
        self.caret.open = on
        self.caret.update()
        self.toggled.emit(on)


def reveal(widget):
    """Open every closed section around `widget` (so it can be seen and used)."""
    parent = widget
    while parent is not None:
        if isinstance(parent, Section) and not parent.expanded:
            parent.set_expanded(True)
        parent = parent.parentWidget()
