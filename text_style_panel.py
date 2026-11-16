"""The Text panel's Filmora-style controls (exp.16).

The user asked for Filmora's text settings. Chosen: Style basics (bold, italic, underline,
alignment, letter and line spacing), Effects (fill, outline, shadow, glow, background box, each
with its own switch) and Out / Loop animations (the hand writing is the "In"). Letter detail
and Natural handwriting move to an Advanced section.

Style basics change where the letters are, so the text is written again (a moment after the
last change). Effects only change how the ink looks, so they apply at once. Both are kept with
each text element (Window.letter_state).
"""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
                               QHBoxLayout, QPushButton, QSlider, QToolButton, QWidget)

from font_stroke_reveal import EFFECTS_DEFAULT, LAYOUT_DEFAULT, text_effects, text_layout

OUT_CHOICES = ('None', 'Fade out', 'Blur out', 'Wipe out', 'Zoom out', 'Pop out', 'Spin out',
               'Move out to the left', 'Move out to the right', 'Move out to the top',
               'Move out to the bottom', 'Eraser')


def _align_icon(kind, colour='#C9C7D3'):
    pix = QPixmap(36, 36); pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(colour))
    for i, length in enumerate((26, 18, 26, 14)):
        x = {'left': 5, 'center': 18 - length / 2, 'right': 31 - length}[kind]
        p.drawRoundedRect(QRectF(x, 7 + i * 6.4, length, 3), 1.5, 1.5)
    p.end()
    pix.setDevicePixelRatio(2.)
    return QIcon(pix)


def _style_button(text, tip, font_change):
    b = QToolButton(); b.setObjectName('textStyle'); b.setCheckable(True); b.setText(text)
    f = QFont(b.font()); font_change(f); b.setFont(f)
    b.setToolTip(tip); b.setFixedWidth(34)
    return b


def _slider_row(w, minimum, maximum, value, step, suffix='', decimals=0, scale=1):
    """A slider with its number (the number is the value)."""
    spin = QDoubleSpinBox(); spin.setRange(minimum, maximum); spin.setDecimals(decimals)
    spin.setSingleStep(step); spin.setValue(value); spin.setSuffix(suffix); spin.setFixedWidth(74)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
    slider.setValue(int(round(value * scale)))
    slider.valueChanged.connect(lambda v: (spin.blockSignals(True), spin.setValue(v / scale),
                                           spin.blockSignals(False), spin.valueChanged.emit(v / scale)))
    spin.valueChanged.connect(lambda v: (slider.blockSignals(True), slider.setValue(int(round(v * scale))),
                                         slider.blockSignals(False)))
    row = QWidget(); row.setMinimumWidth(0)
    lay = QHBoxLayout(row); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
    lay.addWidget(slider, 1); lay.addWidget(spin)
    spin.slider = slider
    return spin, row


class ColourButton(QPushButton):
    def __init__(self, colour, title):
        super().__init__()
        self.title = title
        self.colour = QColor(colour).name().upper()
        self.clicked.connect(self.choose)
        self.show_colour()

    def show_colour(self):
        pix = QPixmap(16, 16); pix.fill(QColor(self.colour))
        self.setIcon(QIcon(pix)); self.setText(self.colour)

    def set_colour(self, colour, notify=True):
        c = QColor(colour)
        if not c.isValid():
            return
        self.colour = c.name().upper(); self.show_colour()
        if notify and getattr(self, 'changed', None):
            self.changed()

    def choose(self):
        c = QColorDialog.getColor(QColor(self.colour), self, self.title)
        if c.isValid():
            self.set_colour(c.name())


# ------------------------------------------------------------------ building

def build_style(w, layout):
    """Bold / italic / underline and alignment buttons, letter and line spacing (after the font)."""
    from ui_sections import Section
    bar = QWidget(); bar.setMinimumWidth(0)
    row = QHBoxLayout(bar); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
    w.text_bold = _style_button('B', 'Bold', lambda f: f.setBold(True))
    w.text_italic = _style_button('I', 'Italic', lambda f: f.setItalic(True))
    w.text_underline = _style_button('U', 'Underline (the pen underlines each line after it)',
                                     lambda f: f.setUnderline(True))
    for b in (w.text_bold, w.text_italic, w.text_underline):
        row.addWidget(b)
    row.addSpacing(10)
    w.text_align_group = QButtonGroup(bar); w.text_align_group.setExclusive(True)
    w.text_align = {}
    for kind, tip in (('left', 'Align left'), ('center', 'Centre'), ('right', 'Align right')):
        b = QToolButton(); b.setObjectName('textStyle'); b.setCheckable(True); b.setIcon(_align_icon(kind))
        b.setToolTip(tip); b.setFixedWidth(34)
        w.text_align_group.addButton(b); w.text_align[kind] = b; row.addWidget(b)
    w.text_align['left'].setChecked(True)
    row.addStretch(1)
    layout.addWidget(bar)
    from studio_workspace import form_layout
    form = form_layout()
    w.letter_spacing, spacing_row = _slider_row(w, -20, 80, 0, 1)
    w.letter_spacing.setToolTip('Extra room between letters.')
    form.addRow('Letter spacing', spacing_row)
    w.line_spacing, line_row = _slider_row(w, .6, 3., 1., .1, '×', 1, 10)
    w.line_spacing.setToolTip('Room between lines (1 = normal).')
    form.addRow('Line spacing', line_row)
    layout.addLayout(form)
    changed = lambda *_: _layout_changed(w)
    for b in (w.text_bold, w.text_italic, w.text_underline, *w.text_align.values()):
        b.toggled.connect(changed)
    w.letter_spacing.valueChanged.connect(changed)
    w.line_spacing.valueChanged.connect(changed)


def build_effects(w, layout):
    """Fill, Outline, Shadow, Glow, Background, Animation (Out / Loop) and Advanced."""
    from ui_sections import Section
    from studio_workspace import form_layout
    w.text_fx = {}

    def section(name, title, rows, switch=True, tip=''):
        box = None
        if switch:
            box = QCheckBox(f'{title}'); box.setToolTip(f'{title} on / off'); box.hide()
            box.toggled.connect(lambda on: _effects_changed(w))
        sec = Section(title, switch=box, tip=tip)
        form = form_layout(); sec.body.addLayout(form)
        controls = {'on': box}
        for key, label, kind, args in rows:
            if kind == 'colour':
                c = ColourButton(args, f'{title} colour'); c.changed = lambda: _effects_changed(w)
                form.addRow(label, c); controls[key] = c
            else:
                spin, line = _slider_row(w, *args)
                spin.valueChanged.connect(lambda *_: _effects_changed(w))
                form.addRow(label, line); controls[key] = spin
        w.text_fx[name] = controls
        layout.addWidget(sec)
        return sec
    d = EFFECTS_DEFAULT
    w.section_text_fill = section('fill', 'Fill', [
        ('opacity', 'Opacity', 'slider', (0, 100, d['fill']['opacity'], 1, '%')),
        ('blur', 'Blur', 'slider', (0, 20, d['fill']['blur'], .5, '', 1, 10))], switch=False,
        tip='How the letters themselves look.')
    w.section_text_outline = section('outline', 'Outline', [
        ('color', 'Color', 'colour', d['outline']['color']),
        ('opacity', 'Opacity', 'slider', (0, 100, d['outline']['opacity'], 1, '%')),
        ('blur', 'Blur', 'slider', (0, 20, d['outline']['blur'], .5, '', 1, 10)),
        ('thickness', 'Thickness', 'slider', (0, 20, d['outline']['thickness'], .5, '', 1, 10))],
        tip='A line around the letters.')
    w.section_text_shadow = section('shadow', 'Shadow', [
        ('color', 'Color', 'colour', d['shadow']['color']),
        ('opacity', 'Opacity', 'slider', (0, 100, d['shadow']['opacity'], 1, '%')),
        ('blur', 'Blur', 'slider', (0, 30, d['shadow']['blur'], .5, '', 1, 10)),
        ('distance', 'Distance', 'slider', (0, 40, d['shadow']['distance'], .5, '', 1, 10))],
        tip='A shadow under the letters (down and to the right).')
    w.section_text_glow = section('glow', 'Glow', [
        ('color', 'Color', 'colour', d['glow']['color']),
        ('intensity', 'Intensity', 'slider', (0, 100, d['glow']['intensity'], 1)),
        ('range', 'Range', 'slider', (0, 100, d['glow']['range'], 1))],
        tip='A soft light around the letters.')
    w.section_text_background = section('background', 'Background', [
        ('color', 'Color', 'colour', d['background']['color']),
        ('opacity', 'Opacity', 'slider', (0, 100, d['background']['opacity'], 1, '%')),
        ('radius', 'Radius', 'slider', (0, 60, d['background']['radius'], 1)),
        ('spread', 'Spread', 'slider', (0, 60, d['background']['spread'], 1))],
        tip='A box behind the text; it appears as the writing starts.')
    # Animation: the hand writing is the In; Out (a Goes out clip right after it) and Loop
    anim = Section('Animation', tip='The hand writing it is the way in. Out: how it goes away. '
                                    'Loop: how it moves while it stays on screen.')
    form = form_layout(); anim.body.addLayout(form)
    w.text_out = QComboBox(); w.text_out.addItems(list(OUT_CHOICES))
    w.text_out.setToolTip('How the text goes away after it is written: a "Goes out" clip right after it '
                          'on the timeline (drag it there to choose when).')
    w.text_out_time = QDoubleSpinBox(); w.text_out_time.setRange(.3, 10.); w.text_out_time.setSingleStep(.1)
    w.text_out_time.setDecimals(1); w.text_out_time.setValue(.8); w.text_out_time.setSuffix(' s')
    form.addRow('Out', w.text_out)
    form.addRow('Out time', w.text_out_time)
    from frame_render import LOOPS
    w.loop_style = QComboBox(); w.loop_style.addItems(list(LOOPS))
    w.loop_style.setToolTip('A gentle movement, round and round, while the text stays on screen.')
    form.addRow('Loop', w.loop_style)
    w.text_out.currentIndexChanged.connect(lambda *_: w.set_text_out())
    w.text_out_time.valueChanged.connect(lambda *_: w.set_text_out())
    w.loop_style.currentIndexChanged.connect(lambda *_: w.refresh())
    layout.addWidget(anim)
    w.section_text_animation = anim
    adv = Section('Advanced', tip='Letter detail and Natural handwriting.')
    w.section_text_advanced = adv
    layout.addWidget(adv)
    return adv


# ------------------------------------------------------------------ state

def layout_state(w):
    align = next((k for k, b in w.text_align.items() if b.isChecked()), 'left')
    return text_layout(dict(bold=w.text_bold.isChecked(), italic=w.text_italic.isChecked(),
                            underline=w.text_underline.isChecked(), align=align,
                            spacing=w.letter_spacing.value(), line=w.line_spacing.value()))


def effects_state(w):
    out = {}
    for part, controls in w.text_fx.items():
        got = {}
        for key, c in controls.items():
            if c is None:
                continue
            if key == 'on':
                got['on'] = c.isChecked()
            elif isinstance(c, ColourButton):
                got[key] = c.colour
            else:
                got[key] = float(c.value())
        out[part] = got
    return text_effects(out)


def set_state(w, layout=None, effects=None):
    """Show a text element's own style (no signals, nothing written again)."""
    lay = text_layout(layout)
    eff = text_effects(effects)
    widgets = [w.text_bold, w.text_italic, w.text_underline, *w.text_align.values(),
               w.letter_spacing, w.letter_spacing.slider, w.line_spacing, w.line_spacing.slider]
    for part in w.text_fx.values():
        widgets += [c for c in part.values() if c is not None]
        widgets += [c.slider for c in part.values() if hasattr(c, 'slider')]
    for x in widgets:
        x.blockSignals(True)
    try:
        w.text_bold.setChecked(lay['bold']); w.text_italic.setChecked(lay['italic'])
        w.text_underline.setChecked(lay['underline'])
        w.text_align[lay['align']].setChecked(True)
        for spin, value, scale in ((w.letter_spacing, lay['spacing'], 1), (w.line_spacing, lay['line'], 10)):
            spin.setValue(value); spin.slider.setValue(int(round(value * scale)))
        for part, controls in w.text_fx.items():
            for key, c in controls.items():
                if c is None:
                    continue
                value = eff[part][key]
                if key == 'on':
                    c.setChecked(bool(value))
                elif isinstance(c, ColourButton):
                    c.set_colour(value, notify=False)
                else:
                    c.setValue(float(value))
                    c.slider.setValue(int(round(float(value) * (c.slider.maximum() / max(1e-9, c.maximum())))))
    finally:
        for x in widgets:
            x.blockSignals(False)
    for sec in (w.section_text_outline, w.section_text_shadow, w.section_text_glow, w.section_text_background):
        if sec.switch is not None:
            sec.switch.update()


def _layout_changed(w):
    if getattr(w.drawing, 'source_kind', None) == 'font':
        w.letter_timer.start()                 # written again a moment after the last change


def _effects_changed(w):
    if getattr(w, '_suspend_refresh', False):
        return
    w.apply_letter_style()
    w.schedule_refresh()
