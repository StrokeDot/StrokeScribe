"""Pre-render window, like Filmora's "Creating preview render for smooth playback":
a progress bar, the frame being made, the time left, Cancel, and whether to keep
the render after StrokeScribe closes (off: it is deleted, it takes no disk space).
"""
from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

KEEP_KEY = 'preview/keep_render'


def keep_render():
    """True: ready frames stay on disk after closing (faster next time). Default: deleted."""
    value = QSettings('StrokeScribe', 'Studio').value(KEEP_KEY, False)
    return value in (True, 'true', '1', 1)


def set_keep_render(on):
    QSettings('StrokeScribe', 'Studio').setValue(KEEP_KEY, bool(on))


def clock(seconds):
    seconds = max(0, int(round(seconds)))
    return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


class PrerenderDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle('Pre-render')
        self.setObjectName('prerenderDialog')
        self.window_ = window
        self.started = time.monotonic()
        self.first_ready = None
        outer = QVBoxLayout(self); outer.setContentsMargins(24, 20, 24, 18); outer.setSpacing(12)
        outer.addWidget(QLabel('Creating the preview render for smooth playback'))
        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setFixedHeight(8)
        outer.addWidget(self.bar)
        self.frames = QLabel('Getting ready…'); outer.addWidget(self.frames)
        self.left = QLabel(''); outer.addWidget(self.left)
        self.keep = QCheckBox('Keep the render after closing StrokeScribe')
        self.keep.setToolTip('Off (recommended): the ready frames are deleted when StrokeScribe closes, so '
                             'they take no disk space. On: they stay, and playback is smooth at once next time.')
        self.keep.setChecked(keep_render())
        self.keep.toggled.connect(set_keep_render)
        outer.addWidget(self.keep)
        row = QHBoxLayout(); row.addStretch(1); outer.addLayout(row)
        self.cancel = QPushButton('Cancel'); self.cancel.clicked.connect(self.reject)
        row.addWidget(self.cancel)
        self.setMinimumWidth(460)
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def show_progress(self, ready, total):
        """`ready` of `total` frames are ready (frames that were ready before count too)."""
        if self.first_ready is None:
            self.first_ready = ready
        self.bar.setMaximum(max(1, total)); self.bar.setValue(min(ready, total))
        self.frames.setText(f'Rendering frame {min(ready + 1, total)} / {total}')
        made = ready - self.first_ready
        spent = time.monotonic() - self.started
        if made >= 3 and spent > .5:
            self.left.setText('Estimated time left: ' + clock(spent / made * max(0, total - ready)))
        else:
            self.left.setText('Estimated time left: working it out…')
