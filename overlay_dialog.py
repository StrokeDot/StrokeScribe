"""Settings of one overlay (picture or title): every change shows at once in the preview."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFontComboBox,
                               QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout)

import overlays


def _number(minimum, maximum, value, step, suffix=''):
    box = QDoubleSpinBox(); box.setRange(minimum, maximum); box.setSingleStep(step); box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


class OverlayDialog(QDialog):
    def __init__(self, parent, item, scene_seconds, changed=lambda item: None):
        super().__init__(parent)
        self.item = item
        self.changed = changed
        self.deleted = False
        text = item.get('kind') == 'text'
        self.setWindowTitle('Title' if text else 'Picture overlay')
        self.resize(420, 560 if text else 470)
        root = QVBoxLayout(self); root.setContentsMargins(20, 18, 20, 16); root.setSpacing(10)
        title = QLabel('Title' if text else 'Picture overlay'); title.setObjectName('dialogTitle')
        root.addWidget(title)
        hint = QLabel('Changes show in the preview right away. You can also drag it on the preview, '
                      'and drag its clip on the timeline.')
        hint.setWordWrap(True); hint.setObjectName('note'); root.addWidget(hint)
        form = QFormLayout(); form.setSpacing(8); root.addLayout(form)
        if text:
            self.text = QPlainTextEdit(item.get('text', '')); self.text.setFixedHeight(64)
            self.text.textChanged.connect(self.apply)
            form.addRow('Text', self.text)
            self.font_box = QFontComboBox(); self.font_box.setCurrentText(item.get('font') or 'Segoe UI')
            self.font_box.currentFontChanged.connect(lambda f: self.apply())
            form.addRow('Font', self.font_box)
            row = QHBoxLayout()
            self.colour = QPushButton(); self.colour.clicked.connect(self.pick_colour)
            row.addWidget(self.colour, 1)
            self.bold = QCheckBox('Bold'); self.bold.setChecked(bool(item.get('bold', True)))
            self.bold.toggled.connect(lambda on: self.apply())
            row.addWidget(self.bold)
            form.addRow('Colour', row)
            self.size = _number(2, 40, float(item.get('size', .09)) * 100, .5, ' %')
            self.size.setToolTip('Height of a line of text, in % of the video height.')
        else:
            self.name = QLabel(item.get('name', '')); form.addRow('Picture', self.name)
            self.size = _number(3, 200, float(item.get('size', .35)) * 100, 1, ' %')
            self.size.setToolTip('Width of the picture, in % of the video width.')
        form.addRow('Size', self.size)
        self.x = _number(-50, 150, float(item.get('x', .5)) * 100, 1, ' %')
        self.y = _number(-50, 150, float(item.get('y', .5)) * 100, 1, ' %')
        pos = QHBoxLayout(); pos.addWidget(self.x); pos.addWidget(self.y)
        form.addRow('Position X / Y', pos)
        total = max(.5, float(scene_seconds))
        self.start = _number(0, total, min(total, float(item.get('start', 0))), .1, ' s')
        self.length = _number(.2, max(.2, total), min(total, float(item.get('duration', 3))), .1, ' s')
        form.addRow('Appears at', self.start)
        form.addRow('Stays for', self.length)
        self.effect_in = QComboBox(); self.effect_in.addItems(overlays.EFFECTS)
        self.effect_in.setCurrentText(item.get('effect_in', overlays.DEFAULT_IN))
        self.in_seconds = _number(.1, 5, float(item.get('in_seconds', .5)), .1, ' s')
        row = QHBoxLayout(); row.addWidget(self.effect_in, 1); row.addWidget(self.in_seconds)
        form.addRow('Comes in', row)
        self.effect_out = QComboBox(); self.effect_out.addItems(overlays.EFFECTS)
        self.effect_out.setCurrentText(item.get('effect_out', overlays.DEFAULT_OUT))
        self.out_seconds = _number(.1, 5, float(item.get('out_seconds', .4)), .1, ' s')
        row = QHBoxLayout(); row.addWidget(self.effect_out, 1); row.addWidget(self.out_seconds)
        form.addRow('Goes out', row)
        for box in (self.size, self.x, self.y, self.start, self.length, self.in_seconds, self.out_seconds):
            box.valueChanged.connect(lambda value: self.apply())
        for box in (self.effect_in, self.effect_out):
            box.currentIndexChanged.connect(lambda index: self.apply())
        root.addStretch(1)
        buttons = QHBoxLayout()
        delete = QPushButton('Delete'); delete.setObjectName('subtle'); delete.clicked.connect(self.delete)
        buttons.addWidget(delete); buttons.addStretch(1)
        done = QPushButton('Done'); done.setObjectName('primary'); done.clicked.connect(self.accept)
        buttons.addWidget(done)
        root.addLayout(buttons)
        self._colour = item.get('color') or '#1E2A3A'
        if text:
            self.show_colour()

    def show_colour(self):
        self.colour.setText(self._colour.upper())
        self.colour.setStyleSheet(f'background: {self._colour}; color: '
                                  f'{"#000" if QColor(self._colour).lightness() > 140 else "#fff"};')

    def pick_colour(self):
        colour = QColorDialog.getColor(QColor(self._colour), self, 'Text colour')
        if colour.isValid():
            self._colour = colour.name(); self.show_colour(); self.apply()

    def apply(self):
        it = self.item
        if it.get('kind') == 'text':
            it['text'] = self.text.toPlainText() or ' '
            it['name'] = it['text'].split('\n')[0][:30]
            it['font'] = self.font_box.currentFont().family()
            it['bold'] = self.bold.isChecked()
            it['color'] = self._colour
        it['size'] = self.size.value() / 100
        it['x'], it['y'] = self.x.value() / 100, self.y.value() / 100
        it['start'] = self.start.value()
        it['duration'] = self.length.value()
        it['effect_in'], it['in_seconds'] = self.effect_in.currentText(), self.in_seconds.value()
        it['effect_out'], it['out_seconds'] = self.effect_out.currentText(), self.out_seconds.value()
        self.changed(it)

    def delete(self):
        self.deleted = True
        self.accept()
