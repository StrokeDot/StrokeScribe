"""The Paint mode picker: a bigger window than a dropdown, with the modes grouped,
a short description of each, and a live preview on the element being edited.

The modes themselves (and the Paint mode list's order, which projects and menus
rely on) are unchanged; this only presents them.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QVBoxLayout)

# (group title, [(mode text, description)]) in the order they are shown.
GROUPS = (
    ('ADAPTIVE — paints the picture part by part', (
        ('Adaptive Hand Painting',
         'The hand paints one part of the picture at a time, brushing back and forth inside '
         'each part. It starts where the drawing ended and moves on to the nearest part.'),
        ('Adaptive — Short up/down strokes',
         'The same part-by-part route as Adaptive, with quick short up and down flicks of '
         'the brush along the way.'),
    )),
    ('PAINTER — new: paints like a person', (
        ('Painter — real parts, strokes follow the shape',
         'Paints the picture the way a person would: the big parts first, then smaller '
         'parts, details last. Each part is brushed around its own shape, from the edge '
         'inwards. Tiny specks join the part next to them, so the hand does not hop around.'),
    )),
    ('SWEEPS — across the whole picture', (
        ('Zigzag sweep',
         'The hand follows one route along the object, scribbling colour back and forth '
         'across it (wider on broad parts).'),
        ('Top to bottom (rows)',
         'Like a painter: the colours are brushed in band by band from the top down, '
         'sweeping left and right across the whole picture.'),
        ('Left to right (columns)',
         'The colours are brushed in band by band from the left to the right, sweeping '
         'up and down across the whole picture.'),
    )),
    ('SIMPLE', (
        ('Brush painting',
         'A simple brush sweep that reveals the colours over the drawing (SVG pictures only).'),
    )),
)
DESCRIPTIONS = {text: about for _, modes in GROUPS for text, about in modes}

PREVIEW_WIDTH = 400
PREVIEW_FRAMES = 18


class PaintModeDialog(QDialog):
    """Choose a paint mode. `allowed(text)` says whether a mode can be used for this element."""

    def __init__(self, window, current, allowed=lambda text: True):
        super().__init__(window)
        self.setWindowTitle('Paint mode')
        self.setObjectName('paintModeDialog')
        self.window_ = window
        self.chosen = current
        self._frames = {}           # mode -> [QPixmap]
        self._pending = None        # (mode, [fractions], index)
        self._shown = 0
        outer = QVBoxLayout(self)
        body = QHBoxLayout(); outer.addLayout(body, 1)
        self.list = QListWidget(); self.list.setMinimumWidth(340)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self.list)
        side = QVBoxLayout(); body.addLayout(side, 1)
        self.title = QLabel(); self.title.setObjectName('sectionTitle')
        side.addWidget(self.title)
        self.about = QLabel(); self.about.setWordWrap(True); self.about.setMinimumWidth(PREVIEW_WIDTH)
        side.addWidget(self.about)
        self.preview = QLabel('Preview'); self.preview.setObjectName('monitorWell')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_WIDTH, round(PREVIEW_WIDTH * 9 / 16))
        side.addWidget(self.preview, 1)
        self.preview.mousePressEvent = lambda event: self.toggle_pause()    # click the preview: pause / play
        from PySide6.QtWidgets import QPushButton
        controls = QHBoxLayout(); side.addLayout(controls)
        self.pause_button = QPushButton('Pause')
        self.pause_button.setToolTip('Pause or play the preview (or click the preview).')
        self.pause_button.clicked.connect(lambda checked=False: self.toggle_pause())
        controls.addWidget(self.pause_button); controls.addStretch(1)
        self.paused = False
        self.note = QLabel(''); self.note.setWordWrap(True); self.note.setObjectName('caption')
        side.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Use this mode')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.items = {}
        for group, modes in GROUPS:
            header = QListWidgetItem(group)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font(); font.setBold(True); font.setPointSizeF(font.pointSizeF() * .85); header.setFont(font)
            self.list.addItem(header)
            for text, _ in modes:
                item = QListWidgetItem('    ' + text)
                item.setData(Qt.ItemDataRole.UserRole, text)
                if not allowed(text):
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setToolTip('Not available for this element.')
                self.list.addItem(item)
                self.items[text] = item
        self.list.currentItemChanged.connect(lambda item, _old: self.select(item))
        self.list.itemDoubleClicked.connect(lambda item: self.accept() if self.chosen == item.data(Qt.ItemDataRole.UserRole) else None)
        self.render_timer = QTimer(self); self.render_timer.setInterval(0)
        self.render_timer.timeout.connect(self.render_next)
        self.play_timer = QTimer(self); self.play_timer.setInterval(110)
        self.play_timer.timeout.connect(self.play_next)
        start = self.items.get(current) or next(iter(self.items.values()))
        self.list.setCurrentItem(start)
        self.resize(900, 480)

    # ------------------------------------------------------------ choosing
    def select(self, item):
        mode = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not mode:
            return
        self.chosen = mode
        self.title.setText(mode)
        self.about.setText(DESCRIPTIONS.get(mode, ''))
        self.start_preview(mode)

    # ------------------------------------------------------------ preview
    def preview_plan(self, mode):
        """(options, [fractions]) for a preview of `mode` on the edited element, or (None, note)."""
        w = self.window_
        if getattr(w, 'drawing', None) is None:
            return None, 'Add a picture to see a preview here.'
        options = w.options(overrides={'reveal_mode': mode})
        if options.get('final_image') is None:
            return None, 'This element has no colours to paint, so there is nothing to preview.'
        from frame_render import timeline_seconds
        total = timeline_seconds(w.drawing, options)
        start = min(.99, float(options.get('duration', 0) or 0) / max(.001, total))
        end = min(1., (float(options.get('duration', 0) or 0) + float(options.get('fade_duration', 0) or 0))
                  / max(.001, total))
        fractions = [start + (end - start) * (i + 1) / PREVIEW_FRAMES for i in range(PREVIEW_FRAMES)]
        ratio = float(options.get('height', 1080)) / max(1., float(options.get('width', 1920)))
        options = dict(options, width=PREVIEW_WIDTH, height=round(PREVIEW_WIDTH * ratio),
                       erase=None, overlays=[], camera_zoom=1.)
        options['hand_scale'] = options.get('hand_scale', .75) / max(.01, options.get('artwork_scale', 1.))
        return options, fractions

    def start_preview(self, mode):
        self.play_timer.stop(); self.render_timer.stop()
        self._shown = 0
        if mode in self._frames and len(self._frames[mode]) == PREVIEW_FRAMES:
            self.note.setText('')
            self.play(); return
        try:
            options, fractions = self.preview_plan(mode)
        except Exception as exc:
            options, fractions = None, f'No preview: {exc}'
        if options is None:
            self.preview.clear(); self.preview.setText(fractions); self.note.setText(''); return
        self._frames[mode] = []
        self._pending = (mode, options, fractions)
        self.preview.setText('Preparing the preview…')
        self.note.setText('The first frame can take a few seconds while the brush route is planned.')
        QTimer.singleShot(30, self.render_timer.start)        # let the text show first

    def render_next(self):
        if self._pending is None:
            self.render_timer.stop(); return
        mode, options, fractions = self._pending
        frames = self._frames[mode]
        if len(frames) >= len(fractions) or mode != self.chosen:
            self.render_timer.stop(); self._pending = None
            if mode == self.chosen:
                self.note.setText(''); self.play()
            return
        from frame_render import compose_frame
        try:
            image = compose_frame(self.window_.drawing, fractions[len(frames)], options)
        except Exception as exc:
            self.render_timer.stop(); self._pending = None
            self.preview.setText(f'No preview: {exc}'); return
        frames.append(self._on_paper(image))
        self.preview.setPixmap(frames[-1])
        self.note.setText(f'Preparing the preview… {len(frames)}/{len(fractions)}')

    def _on_paper(self, image):
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtGui import QImage
        out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(QColor(246, 244, 238))
        p = QPainter(out); p.drawImage(0, 0, image); p.end()
        return QPixmap.fromImage(out)

    def play(self):
        """Loop the ready preview, unless it is paused."""
        if not self.paused:
            self.play_timer.start()
        else:
            self.play_next()

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.setText('Play' if self.paused else 'Pause')
        if self.paused:
            self.play_timer.stop()
        elif self._frames.get(self.chosen) and self._pending is None:
            self.play_timer.start()

    def play_next(self):
        frames = self._frames.get(self.chosen) or []
        if not frames:
            self.play_timer.stop(); return
        self.preview.setPixmap(frames[self._shown % len(frames)])
        self._shown += 1

    def done(self, result):
        self.render_timer.stop(); self.play_timer.stop()
        super().done(result)
