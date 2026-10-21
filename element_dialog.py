"""Edit one element in a window of its own (like VideoScribe): its own little
player, how it comes in, its times, colours, how it goes out and the camera move
to the next element. Set keeps the changes; Cancel puts everything back.

The window works on the element being edited in the main window: every change
is made on the main window's own controls, so the timeline, the board and the
export always see the same settings.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

PREVIEW_W, PREVIEW_H = 560, 315


def _section(text):
    label = QLabel(text); label.setObjectName('section')
    return label


class ElementDialog(QDialog):
    def __init__(self, window, k):
        super().__init__(window)
        self.w = window
        self.k = k
        self.playing = False
        self.position = 0.
        self._last = 0.
        w = window
        self.scope=w.preview_scope.currentIndex()       # given back when the window closes
        self.main_position=w.position
        if self.scope:
            w.preview_scope.setCurrentIndex(0)           # the element itself
        scene = w.scenes[k]
        self.saved = dict(snapshot=w.snapshot(), transition=scene['transition'],
                          seconds=scene['transition_seconds'], name=scene.get('name'))
        self.setWindowTitle(f'Element {k + 1}: {w.scene_label(k)}')
        self.resize(1000, 600)
        root = QHBoxLayout(self); root.setContentsMargins(18, 16, 18, 14); root.setSpacing(18)

        # ---------------------------------------------------------- player
        left = QVBoxLayout(); left.setSpacing(8)
        self.preview = QLabel(); self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview.setObjectName('monitorWell'); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.preview)
        player = QHBoxLayout()
        self.play_button = QPushButton('▶ Play'); self.play_button.setObjectName('primary')
        self.play_button.clicked.connect(self.toggle)
        player.addWidget(self.play_button)
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(lambda v: self.seek(v / 1000))
        player.addWidget(self.slider, 1)
        self.clock = QLabel('0.0 s'); self.clock.setMinimumWidth(80)
        player.addWidget(self.clock)
        left.addLayout(player)
        note = QLabel('Only this element plays here. Set keeps your changes; Cancel puts everything back.')
        note.setWordWrap(True); note.setObjectName('note')
        left.addWidget(note); left.addStretch(1)
        root.addLayout(left)

        # ---------------------------------------------------------- settings
        right = QVBoxLayout(); right.setSpacing(6)
        form = QFormLayout(); form.setSpacing(7)
        self.name = QLineEdit(scene.get('name') or w.scene_label(k))
        self.name.textChanged.connect(self.rename)
        form.addRow('Name', self.name)
        right.addLayout(form)
        image = w.source_type.currentIndex() == 1
        self.pairs = []

        def add(form, text, mine, theirs):
            form.addRow(text, mine)
            self.pairs.append((mine, theirs))
            return mine

        right.addWidget(_section('COMES IN'))
        f1 = QFormLayout(); f1.setSpacing(7); right.addLayout(f1)
        add(f1, 'How', self._combo(w.entrance), w.entrance)
        add(f1, 'Time (s)', self._number(w.duration), w.duration)

        right.addWidget(_section('COLOURS'))
        f2 = QFormLayout(); f2.setSpacing(7); right.addLayout(f2)
        colour_box = w.preserve_colors if image else w.use_color
        self.colour = add(f2, '', self._check(colour_box, 'Paint the colours after drawing'), colour_box)
        add(f2, 'Painting', self._combo(w.reveal_mode), w.reveal_mode)
        paint = w.image_duration if image else w.color_fade
        add(f2, 'Paint time (s)', self._number(paint), paint)
        add(f2, 'Colour hold (s)', self._number(w.color_hold), w.color_hold)

        right.addWidget(_section('APPEARANCE & BLENDING'))
        appearance=QFormLayout(); appearance.setSpacing(7); right.addLayout(appearance)
        add(appearance,'Blend mode',self._combo(w.blend_mode),w.blend_mode)
        add(appearance,'Opacity',self._number(w.artwork_opacity),w.artwork_opacity)
        self.paper_checkbox=add(appearance,'',
            self._check(w.paper_cleanup,'Clean white / paper background'),
            w.paper_cleanup)
        self.paper_tol=add(appearance,'Tolerance',self._number(w.paper_tolerance),w.paper_tolerance)
        self.paper_soft=add(appearance,'Edge softness',self._number(w.paper_softness),w.paper_softness)
        self.paper_checkbox.setToolTip(
            'Remove only near-white pixels connected to the outside paper edge. '
            'Original pixels and painted stroke routes stay unchanged.')
        self.paper_tol.setToolTip('Maximum color departure from white: 0–80.')
        self.paper_soft.setToolTip('Fade near-white paper edges gradually, without erasing enclosed white areas.')
        self.paper_checkbox.setEnabled(image)
        self.paper_tol.setEnabled(image)
        self.paper_soft.setEnabled(image)

        right.addWidget(_section('STAYS'))
        f3 = QFormLayout(); f3.setSpacing(7); right.addLayout(f3)
        add(f3, 'Pause (s)', self._number(w.pause_after), w.pause_after)

        right.addWidget(_section('GOES OUT'))
        f4 = QFormLayout(); f4.setSpacing(7); right.addLayout(f4)
        add(f4, 'How', self._combo(w.erase_mode), w.erase_mode)
        add(f4, 'Time (s)', self._number(w.erase_time), w.erase_time)

        right.addWidget(_section('THEN, TO THE NEXT ELEMENT'))
        f5 = QFormLayout(); f5.setSpacing(7); right.addLayout(f5)
        from scenes import TRANSITIONS
        self.transition = QComboBox(); self.transition.addItems(list(TRANSITIONS))
        self.transition.setCurrentText(scene['transition'])
        self.transition.currentIndexChanged.connect(lambda i: self.move_changed())
        f5.addRow('Camera', self.transition)
        self.move = QDoubleSpinBox(); self.move.setRange(.2, 6); self.move.setSingleStep(.1)
        self.move.setValue(float(scene['transition_seconds']))
        self.move.valueChanged.connect(lambda v: self.move_changed())
        f5.addRow('Move (s)', self.move)

        right.addWidget(_section('HAND'))
        f6 = QFormLayout(); f6.setSpacing(7); right.addLayout(f6)
        add(f6, '', self._check(w.showhand, 'Show the hand'), w.showhand)
        add(f6, '', self._check(w.left_handed, 'Left-handed'), w.left_handed)

        right.addStretch(1)
        buttons = QHBoxLayout()
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject)
        buttons.addStretch(1); buttons.addWidget(cancel)
        done = QPushButton('Set'); done.setObjectName('primary'); done.clicked.connect(self.accept)
        buttons.addWidget(done)
        right.addLayout(buttons)
        holder = QWidget(); holder.setLayout(right); holder.setMinimumWidth(0)
        # Appearance introduces additional fields: scroll rather than clip the
        # Hand/Set/Cancel controls on 600px-high and scaled Windows desktops.
        settings_scroll=QScrollArea()
        settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setMinimumWidth(330)
        settings_scroll.setWidget(holder)
        root.addWidget(settings_scroll,1)

        for mine, theirs in self.pairs:
            self._connect(mine, theirs)
        self.sync_enabled()
        self.timer = QTimer(self); self.timer.setInterval(33); self.timer.timeout.connect(self.tick)
        self.seek(1.)                              # show the finished element first

    # ---------------------------------------------------------- controls that mirror the window
    def _combo(self, theirs):
        box = QComboBox()
        for i in range(theirs.count()):
            box.addItem(theirs.itemText(i))
            item = theirs.model().item(i) if hasattr(theirs.model(), 'item') else None
            if item is not None and not item.isEnabled():
                box.model().item(i).setEnabled(False)
        box.setCurrentIndex(theirs.currentIndex())
        box.setToolTip(theirs.toolTip())
        return box

    def _number(self, theirs):
        box = QDoubleSpinBox()
        box.setRange(theirs.minimum(), theirs.maximum()); box.setSingleStep(theirs.singleStep())
        box.setDecimals(2); box.setValue(theirs.value()); box.setToolTip(theirs.toolTip())
        return box

    def _check(self, theirs, text):
        box = QCheckBox(text); box.setChecked(theirs.isChecked()); box.setToolTip(theirs.toolTip())
        return box

    def _connect(self, mine, theirs):
        if isinstance(mine, QComboBox):
            mine.currentIndexChanged.connect(lambda i, t=theirs: self.change(lambda: t.setCurrentIndex(i)))
        elif isinstance(mine, QDoubleSpinBox):
            mine.valueChanged.connect(lambda v, t=theirs: self.change(lambda: t.setValue(v)))
        else:
            mine.toggled.connect(lambda on, t=theirs: self.change(lambda: t.setChecked(on)))

    def change(self, action):
        action()
        self.sync_enabled()
        self.w.refresh()
        self.seek(self.position)

    def sync_enabled(self):
        for mine, theirs in self.pairs:
            if mine in (self.paper_checkbox,self.paper_tol,self.paper_soft):
                mine.setEnabled(self.w.is_image_artwork())
            else:
                # Hidden Inspector widgets are still active and persisted;
                # only their Element Editor mirrors are visible.
                mine.setEnabled(theirs.isEnabled())

    def rename(self, text):
        self.w.scenes[self.k]['name'] = text.strip() or None

    def move_changed(self):
        w = self.w
        w.scene_transition.setCurrentText(self.transition.currentText())
        w.scene_transition_time.blockSignals(True); w.scene_transition_time.setValue(self.move.value())
        w.scene_transition_time.blockSignals(False)
        w.scene_transition_changed()

    # ---------------------------------------------------------- the little player
    def length(self):
        try:
            return max(.1, self.w.timeline_length())
        except Exception:
            return 4.

    def seek(self, fraction):
        self.position = max(0., min(1., fraction))
        if not self.playing:
            self.slider.blockSignals(True); self.slider.setValue(round(self.position * 1000))
            self.slider.blockSignals(False)
        self.clock.setText(f'{self.position * self.length():.1f} s')
        w = self.w
        try:
            if getattr(w, '_view', None) is None:
                w.refresh()
            frame = w.render_view(self.position, PREVIEW_W)
        except Exception as exc:
            import applog; applog.error('Element preview', exc)
            return
        card = QImage(PREVIEW_W, PREVIEW_H, QImage.Format.Format_ARGB32_Premultiplied)
        card.fill(QColor('#ffffff') if w.background_spec() == 'transparent' else QColor(0, 0, 0, 0))
        painter = QPainter(card)
        if w.background_spec() != 'transparent':
            from backgrounds import picture_png
            painter.fillRect(0, 0, PREVIEW_W, PREVIEW_H, QColor('#ffffff'))
            spec = w.background_spec()
            if spec.startswith('#') or spec in ('white', 'dark', 'black'):
                painter.fillRect(0, 0, PREVIEW_W, PREVIEW_H,
                                 QColor(spec if spec.startswith('#') else
                                        {'white': '#ffffff', 'dark': '#242d3b', 'black': '#000000'}[spec]))
            else:
                from backgrounds import TEXTURES, texture_qimage
                name = {t.lower(): t for t in TEXTURES}.get(spec)
                if name:
                    painter.drawImage(0, 0, texture_qimage(name, PREVIEW_W, PREVIEW_H))
        scaled = frame.scaled(PREVIEW_W, PREVIEW_H, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        painter.drawImage((PREVIEW_W - scaled.width()) // 2, (PREVIEW_H - scaled.height()) // 2, scaled)
        painter.end()
        self.preview.setPixmap(QPixmap.fromImage(card))

    def toggle(self):
        self.playing = not self.playing
        if self.playing:
            if self.position >= 1:
                self.position = 0.
            self._last = time.perf_counter()
            self.timer.start(); self.play_button.setText('■ Stop')
        else:
            self.timer.stop(); self.play_button.setText('▶ Play')

    def tick(self):
        now = time.perf_counter()
        self.position = min(1., self.position + (now - self._last) / self.length())
        self._last = now
        self.slider.blockSignals(True); self.slider.setValue(round(self.position * 1000))
        self.slider.blockSignals(False)
        self.seek(self.position)
        if self.position >= 1:
            self.toggle()

    # ---------------------------------------------------------- Set / Cancel
    def give_back_view(self):
        w=self.w
        if self.scope and w.preview_scope.currentIndex()!=self.scope and len(w.scenes)>1:
            w.preview_scope.setCurrentIndex(self.scope)
        w.position=self.main_position
        w.slider.blockSignals(True); w.slider.setValue(round(w.position*1000)); w.slider.blockSignals(False)

    def accept(self):
        self.timer.stop()
        self.w.commit_history()
        self.give_back_view()
        self.w.fill_scenes(); self.back_to_scope(); self.w.refresh()
        super().accept()

    def reject(self):
        self.timer.stop()
        w = self.w
        w.restore(self.saved['snapshot'])
        scene = w.scenes[self.k]
        scene['name'] = self.saved['name']
        scene['transition'], scene['transition_seconds'] = self.saved['transition'], self.saved['seconds']
        self.give_back_view()
        w.fill_scenes(); self.back_to_scope(); w.refresh()
        super().reject()

    def back_to_scope(self):
        """Back to what the main timeline showed before (the whole video, usually)."""
        scope = self.w.preview_scope
        if self.scope and scope.currentIndex() != self.scope and len(self.w.scenes) > 1:
            scope.blockSignals(True); scope.setCurrentIndex(self.scope); scope.blockSignals(False)
