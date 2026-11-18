"""The Stickers panel (exp.27): the library of arrows, circles and lines (click one: it is put
in the video at the playhead), and the chosen sticker's settings, changed live."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout, QLabel,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

import overlays
import stickers


def build(w, Section, form_layout, linked_slider):
    """The page (a QWidget). Sets w.sticker_* fields and w.sync_sticker_panel()."""
    page = QWidget()
    lay = QVBoxLayout(page); lay.setContentsMargins(9, 12, 9, 8); lay.setSpacing(12)

    # the gallery: always shown (not a section that opens and closes)
    heading = QLabel('Click one: it is put in the video at the playhead and draws itself.')
    heading.setWordWrap(True); heading.setObjectName('caption')
    lay.addWidget(heading)
    grid = QGridLayout(); grid.setSpacing(8)
    w.sticker_buttons = {}
    for i, shape in enumerate(stickers.SHAPES):
        b = QToolButton(); b.setObjectName('stickerTile')
        b.setIcon(stickers.preview(shape, 56)); b.setIconSize(QSize(56, 56))
        b.setText(shape); b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        b.setToolTip(f'{shape}: put it in the video at the playhead (it draws itself)')
        b.clicked.connect(lambda checked=False, s=shape: w.add_sticker(s))
        from PySide6.QtWidgets import QSizePolicy
        b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)   # two equal columns
        grid.addWidget(b, i // 2, i % 2)
        w.sticker_buttons[shape] = b
    grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
    lay.addLayout(grid)

    chosen = Section('Sticker settings')
    w.sticker_section = chosen
    w.sticker_hint = QLabel('Choose a sticker in the video or on the timeline to change it.')
    w.sticker_hint.setWordWrap(True); w.sticker_hint.setObjectName('caption')
    chosen.body.addWidget(w.sticker_hint)
    form = form_layout(); chosen.body.addLayout(form)
    w.sticker_form = form
    w.sticker_shape = QComboBox(); w.sticker_shape.addItems(stickers.SHAPES)
    form.addRow('Shape', w.sticker_shape)
    # exp.29 (the user): it draws itself, or the hand draws it (only its outline, or everything)
    w.sticker_drawing = QComboBox(); w.sticker_drawing.addItems(stickers.DRAWING)
    w.sticker_drawing.setToolTip('Animated: it draws itself. Hand: outline: the hand draws its main shape '
                                 '(an arrow\'s line; the head pops in). Hand: everything: the hand draws every stroke.')
    form.addRow('Appears', w.sticker_drawing)
    w.sticker_hand_way = QComboBox(); w.sticker_hand_way.addItems(stickers.HAND_WAYS)
    w.sticker_hand_way.setToolTip('Where the hand comes from and goes back to: its resting corner, or in from '
                                  'the bottom and out again.')
    form.addRow('Hand', w.sticker_hand_way)
    w.sticker_hand_ways = QPushButton('Hand ways…')
    w.sticker_hand_ways.setToolTip('How the hand goes to the line and back: time, How, Turn, Path (like an '
                                   'element\'s hand; or double-click its bar on the Hand row).')
    w.sticker_hand_ways.clicked.connect(lambda checked=False: chosen_item() is not None and
                                        w.edit_sticker_hand(chosen_item()['id']))
    form.addRow('', w.sticker_hand_ways)
    w.sticker_color = QPushButton(); w.sticker_color.setObjectName('colorButton')
    w.sticker_color.setToolTip('The colour of the lines')
    form.addRow('Colour', w.sticker_color)

    def number(lo, hi, step, decimals, suffix=''):
        box = QDoubleSpinBox(); box.setRange(lo, hi); box.setSingleStep(step); box.setDecimals(decimals)
        if suffix: box.setSuffix(suffix)
        return box

    def slider_row(title, box, lo, hi):
        holder = QWidget(); row = QVBoxLayout(holder); row.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QHBoxLayout
        line = QHBoxLayout(); line.setContentsMargins(0, 0, 0, 0); line.setSpacing(8)
        line.addWidget(box); line.addWidget(linked_slider(box, lo, hi), 1)
        row.addLayout(line)
        form.addRow(title, holder)

    w.sticker_thickness = number(1, 40, .5, 1)
    w.sticker_thickness.setToolTip('Line width (as a share of the video height, ×1000)')
    slider_row('Thickness', w.sticker_thickness, 1, 40)
    w.sticker_size = number(2, 150, 1, 0, ' %')
    w.sticker_size.setToolTip('Width, as a share of the video width')
    slider_row('Size', w.sticker_size, 2, 150)
    w.sticker_aspect = number(2, 200, 1, 0, ' %')
    w.sticker_aspect.setToolTip('Height, as a share of its width (a flatter or taller shape)')
    slider_row('Height', w.sticker_aspect, 2, 200)
    w.sticker_rotation = number(-180, 180, 5, 0, '°')
    slider_row('Rotation', w.sticker_rotation, -180, 180)
    w.sticker_flip = QCheckBox('Mirrored (left ↔ right)')
    form.addRow('', w.sticker_flip)
    w.sticker_draw = number(.1, 10, .1, 1, ' s')
    w.sticker_draw.setToolTip('How long it takes to draw itself')
    form.addRow('Draw time', w.sticker_draw)
    w.sticker_length = number(.3, 600, .5, 1, ' s')
    w.sticker_length.setToolTip('How long it is in the video (its clip on the timeline)')
    form.addRow('Length', w.sticker_length)
    w.sticker_out = QComboBox(); w.sticker_out.addItems(overlays.EFFECTS)
    w.sticker_out.setToolTip('How it leaves at the end of its clip (None: it stays, like a drawing)')
    form.addRow('Goes out', w.sticker_out)
    w.sticker_delete = QPushButton('Delete sticker')
    form.addRow('', w.sticker_delete)
    lay.addWidget(chosen)
    lay.addStretch(1)

    fields = [w.sticker_shape, w.sticker_drawing, w.sticker_hand_way, w.sticker_hand_ways, w.sticker_thickness, w.sticker_size, w.sticker_aspect, w.sticker_rotation,
              w.sticker_flip, w.sticker_draw, w.sticker_length, w.sticker_out, w.sticker_color, w.sticker_delete]
    state = dict(filling=False, last=(None, 0.))

    def chosen_item():
        item = w.find_overlay(getattr(w, 'selected_overlay', None)) if hasattr(w, 'find_overlay') else None
        return item if item is not None and item.get('kind') == 'sticker' else None

    def paint_color(colour):
        w.sticker_color.setText(colour.upper())
        w.sticker_color.setStyleSheet(f'QPushButton#colorButton {{ border-left: 18px solid {colour}; }}')

    def sync():
        item = chosen_item()
        state['filling'] = True
        try:
            for f in fields:
                f.setEnabled(item is not None)
            w.sticker_hint.setVisible(item is None)
            if item is None:
                return
            if not chosen.expanded:
                chosen.set_expanded(True)      # a sticker chosen: its settings open
            w.sticker_shape.setCurrentText(item.get('shape', 'Arrow'))
            w.sticker_drawing.setCurrentText(item.get('drawing', 'Animated'))
            w.sticker_hand_way.setCurrentText(item.get('hand_way', 'Rests in its corner'))
            w.sticker_hand_way.setEnabled(stickers.hand_mode(item) is not None)
            w.sticker_hand_ways.setEnabled(stickers.hand_mode(item) is not None)
            paint_color(item.get('color', '#E0463C'))
            w.sticker_thickness.setValue(float(item.get('thickness', .012)) * 1000)
            w.sticker_size.setValue(float(item.get('size', .3)) * 100)
            w.sticker_aspect.setValue(float(item.get('aspect', .4)) * 100)
            w.sticker_rotation.setValue(float(item.get('rotation', 0) or 0))
            w.sticker_flip.setChecked(bool(item.get('flip')))
            w.sticker_draw.setValue(float(item.get('draw_seconds', .8)))
            w.sticker_length.setValue(float(item.get('duration', 3)))
            w.sticker_out.setCurrentText(item.get('effect_out', 'Fade'))
        finally:
            state['filling'] = False

    def change(**values):
        item = chosen_item()
        if item is None or state['filling']:
            return
        # one undo step for a burst of changes to the same sticker (dragging a slider)
        last_id, last_time = state['last']
        if last_id != item['id'] or time.monotonic() - last_time > 1.5:
            w.record_structure('sticker settings')
        state['last'] = (item['id'], time.monotonic())
        if 'shape' in values and values['shape'] != item.get('shape'):
            values.update(name=values['shape'], aspect=stickers.ASPECT[values['shape']])
        item.update(values)
        if stickers.hand_mode(item) and ({'drawing', 'draw_seconds', 'hand_way'} & set(values)):
            w.place_hand_sticker(item)          # exp.29: a hand draws one thing at a time
        w.project_changes.mark_changed()
        if {'aspect', 'drawing'} & set(values):
            sync()
        w.refresh()
        if {'drawing', 'draw_seconds', 'duration'} & set(values) and hasattr(w, 'sync_camera_timeline'):
            w.sync_camera_timeline()            # exp.30: the hand's bar on the Hand row

    def pick_color():
        item = chosen_item()
        if item is None:
            return
        colour = QColorDialog.getColor(QColor(item.get('color', '#E0463C')), w, 'Sticker colour')
        if colour.isValid():
            change(color=colour.name())
            paint_color(colour.name())

    w.sticker_shape.currentTextChanged.connect(lambda s: change(shape=s))
    w.sticker_drawing.currentTextChanged.connect(lambda s: change(drawing=s))
    w.sticker_hand_way.currentTextChanged.connect(lambda s: change(hand_way=s))
    w.sticker_thickness.valueChanged.connect(lambda v: change(thickness=round(v / 1000, 4)))
    w.sticker_size.valueChanged.connect(lambda v: change(size=round(v / 100, 4)))
    w.sticker_aspect.valueChanged.connect(lambda v: change(aspect=round(v / 100, 4)))
    w.sticker_rotation.valueChanged.connect(lambda v: change(rotation=round(v, 1)))
    w.sticker_flip.toggled.connect(lambda on: change(flip=bool(on)))
    w.sticker_draw.valueChanged.connect(lambda v: change(draw_seconds=round(v, 2)))
    w.sticker_length.valueChanged.connect(lambda v: change(duration=round(v, 2)))
    w.sticker_out.currentTextChanged.connect(lambda s: change(effect_out=s))
    w.sticker_color.clicked.connect(lambda checked=False: pick_color())
    w.sticker_delete.clicked.connect(lambda checked=False: chosen_item() is not None and
                                     w.overlay_action(chosen_item()['id'], 'delete'))
    w.sync_sticker_panel = sync
    sync()
    return page
