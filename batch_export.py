"""Batch export: a queue of images, SVGs and projects exported one after another.

Images and SVGs use the Studio's current settings (detail, timing, hand,
painting, formats, sound). Projects use the settings saved in them. An SVG is
painted with a colour PNG of the same name next to it (name.png or
name_color.png), if there is one. Each item gets its own folder; a failed item
is reported and the queue continues.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QProgressBar, QAbstractItemView, QMessageBox,
)

IMAGE_TYPES = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')


def item_kind(path):
    suffix = Path(path).suffix.lower()
    if suffix == '.svg':
        return 'SVG'
    if suffix == '.strokescribe':
        return 'Project'
    if suffix in IMAGE_TYPES:
        return 'Image'
    return None


def matching_color(svg_path):
    svg = Path(svg_path)
    for name in (svg.stem + '_color.png', svg.stem + '.png'):
        candidate = svg.with_name(name)
        if candidate.is_file():
            return candidate
    return None


def prepare(path, settings, hand):
    """(drawing, options, formats) for one queue item. Runs in the worker thread."""
    from export_job import formats_from_settings, options_from_settings
    kind = item_kind(path)
    if kind == 'Project':
        import projects
        from scenes import job_from_state
        drawing, options, s = job_from_state(projects.load(path), hand)
        return drawing, options, formats_from_settings(s)
    if kind == 'SVG':
        from color_reveal import load_color_image
        from engine import import_svg
        drawing = import_svg(path)
        color = matching_color(path)
        s = dict(settings)
        image = None
        if color is not None:
            image = load_color_image(str(color), clean=bool(settings.get('clean_color', True)))
            s['use_color'] = True
        else:
            s['use_color'] = False
        return drawing, options_from_settings(s, drawing, color_image=image, hand=hand), \
            formats_from_settings(settings)
    if kind == 'Image':
        from adaptive_hand import plan_for
        from image_reconstruct import reconstruct
        result = reconstruct(path, 'line_art', str(settings.get('image_detail', 'Medium')).lower(),
                             clean_faint=bool(settings.get('clean_faint')),
                             style='detailed' if str(settings.get('image_style', '')).startswith('Detailed')
                             else 'clean',
                             animation='artist' if str(settings.get('image_animation_style', '')).startswith('Artist')
                             else 'standard')
        options = options_from_settings(settings, result.drawing, hand=hand, image_source=result.image)
        if options.get('final_image') is not None:
            result.drawing.paint_method = options['reveal_mode']
            plan_for(result.drawing, result.image, options['brush_width'], options['stroke_spacing'])
        return result.drawing, options, formats_from_settings(settings)
    raise ValueError('Unsupported file type')


def project_scenes(path):
    """Scene list of a multi-scene project (None for anything else)."""
    if item_kind(path) != 'Project':
        return None
    import projects
    from scenes import scenes_from_project
    data = projects.load(path)
    scene_list = scenes_from_project(data)
    if len(scene_list) < 2:
        return None
    scene_list[0]['project'] = data
    return scene_list


class BatchWorker(QThread):
    item_state = Signal(int, str)          # row, status text
    item_progress = Signal(int, int)       # frame i of n (0, 0 = encoding)
    finished_all = Signal(int, int)        # done, failed

    def __init__(self, paths, destination, settings, hand):
        super().__init__()
        self.paths = list(paths)
        self.destination = Path(destination)
        self.settings = dict(settings)
        self.hand = hand

    def run(self):
        from export_job import run_export
        done = failed = 0
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        for row, path in enumerate(self.paths):
            if self.isInterruptionRequested():
                self.item_state.emit(row, 'Skipped (cancelled)')
                continue
            started = time.perf_counter()
            try:
                self.item_state.emit(row, 'Preparing…')
                folder = self.destination / f'{Path(path).stem}_{stamp}'
                n = 1
                while folder.exists():
                    n += 1
                    folder = self.destination / f'{Path(path).stem}_{stamp}_{n}'
                scene_list = project_scenes(path)
                if scene_list:
                    # A project with several scenes becomes one video with all of them.
                    from scenes import export_scenes
                    self.item_state.emit(row, f'Exporting {len(scene_list)} scenes…')
                    data = scene_list[0]['project']
                    message = export_scenes(scene_list, folder, data.get('settings', {}), self.hand,
                                            progress=self.item_progress.emit,
                                            interrupted=self.isInterruptionRequested)
                else:
                    drawing, options, formats = prepare(path, self.settings, self.hand)
                    self.item_state.emit(row, 'Exporting…')
                    message = run_export(drawing, folder, options, **formats,
                                         progress=self.item_progress.emit,
                                         interrupted=self.isInterruptionRequested)
                done += 1
                from app import format_seconds
                self.item_state.emit(row, f'Done in {format_seconds(time.perf_counter() - started)} — '
                                     + message.replace('Saved: ', '').replace('Saved PNG sequence: ', 'PNG frames: '))
            except Exception as exc:
                failed += 1
                self.item_state.emit(row, 'Failed: ' + str(exc).splitlines()[0][:200])
        self.finished_all.emit(done, failed)


class BatchExportDialog(QDialog):
    def __init__(self, parent=None, settings=None, hand=None, play_sound=None):
        super().__init__(parent)
        self.setWindowTitle('Batch export')
        self.resize(900, 560)
        self.settings = settings or {}
        self.hand = hand
        self.play_sound = play_sound
        self.worker = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16); root.setSpacing(10)
        title = QLabel('Batch export'); title.setStyleSheet('font-size: 18px; font-weight: 700;')
        root.addWidget(title)
        note = QLabel('Add images, SVGs or saved projects. Images and SVGs use the current Studio settings '
                      '(detail, timing, hand, painting, formats and sound); projects use their own. '
                      'An SVG is coloured with a PNG of the same name next to it, if there is one.')
        note.setWordWrap(True); note.setObjectName('note')
        root.addWidget(note)
        buttons = QHBoxLayout()
        for text, filt in (('Add images…', 'Images (*.png *.jpg *.jpeg *.webp *.bmp)'),
                           ('Add SVGs…', 'SVG (*.svg)'),
                           ('Add projects…', 'StrokeScribe project (*.strokescribe)')):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, f=filt: self.add_files(f))
            buttons.addWidget(button)
        self.remove_button = QPushButton('Remove selected'); self.remove_button.clicked.connect(self.remove_selected)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        root.addLayout(buttons)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['File', 'Type', 'Status'])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 300)
        root.addWidget(self.table, 1)
        dest = QHBoxLayout()
        self.dest_label = QLabel('Destination: not chosen'); self.dest_label.setObjectName('note')
        dest.addWidget(self.dest_label, 1)
        choose = QPushButton('Choose folder…'); choose.clicked.connect(self.choose_destination)
        dest.addWidget(choose)
        root.addLayout(dest)
        self.overall = QProgressBar(); self.overall.setTextVisible(False); self.overall.setFixedHeight(8)
        root.addWidget(self.overall)
        bottom = QHBoxLayout()
        self.status = QLabel('Add files to begin.'); self.status.setObjectName('status')
        bottom.addWidget(self.status, 1)
        self.cancel_button = QPushButton('Cancel'); self.cancel_button.clicked.connect(self.cancel)
        bottom.addWidget(self.cancel_button)
        self.start_button = QPushButton('Start batch export'); self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.start)
        bottom.addWidget(self.start_button)
        root.addLayout(bottom)
        self.destination = None
        self.paths = []
        self.refresh()

    # ------------------------------------------------------------ queue
    def add_paths(self, paths):
        for path in paths:
            kind = item_kind(path)
            if not kind or path in self.paths:
                continue
            self.paths.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(Path(path).name))
            self.table.item(row, 0).setToolTip(path)
            extra = ''
            if kind == 'SVG' and matching_color(path):
                extra = ' + colour'
            self.table.setItem(row, 1, QTableWidgetItem(kind + extra))
            self.table.setItem(row, 2, QTableWidgetItem('Waiting'))
        if self.destination is None and self.paths:
            self.destination = str(Path(self.paths[0]).parent)
        self.refresh()

    def add_files(self, filt):
        names, _ = QFileDialog.getOpenFileNames(self, 'Add to batch', '', filt)
        self.add_paths(names)

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.paths[row]
        self.refresh()

    def choose_destination(self):
        folder = QFileDialog.getExistingDirectory(self, 'Folder for the batch (one subfolder per file)',
                                                  self.destination or '')
        if folder:
            self.destination = folder
            self.refresh()

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def refresh(self):
        self.dest_label.setText('Destination: ' + (self.destination or 'not chosen')
                                + ('  (one subfolder per file)' if self.destination else ''))
        self.start_button.setEnabled(bool(self.paths) and bool(self.destination) and not self.busy())
        self.cancel_button.setEnabled(self.busy())
        self.remove_button.setEnabled(not self.busy())

    # ------------------------------------------------------------ running
    def start(self):
        if not self.paths or not self.destination:
            return
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText('Waiting')
        self.overall.setRange(0, len(self.paths)); self.overall.setValue(0)
        self.current = 0
        self.started = time.perf_counter()
        self.worker = BatchWorker(self.paths, self.destination, self.settings, self.hand)
        self.worker.item_state.connect(self.on_state)
        self.worker.item_progress.connect(self.on_progress)
        self.worker.finished_all.connect(self.on_finished)
        self.worker.finished.connect(self.refresh)
        self.worker.start()
        self.status.setText(f'Exporting {len(self.paths)} files…')
        self.refresh()

    def on_state(self, row, text):
        self.current = row
        self.table.item(row, 2).setText(text)
        self.table.item(row, 2).setToolTip(text)
        if text.startswith(('Done', 'Failed', 'Skipped')):
            self.overall.setValue(row + 1)

    def on_progress(self, i, n):
        name = Path(self.paths[self.current]).name if self.current < len(self.paths) else ''
        self.status.setText(f'{name}: frame {i} / {n}' if n else f'{name}: encoding video…')

    def on_finished(self, done, failed):
        from app import format_seconds
        took = format_seconds(time.perf_counter() - self.started)
        self.status.setText(f'Batch finished in {took}: {done} exported' + (f', {failed} failed' if failed else '') + '.')
        if self.play_sound and done:
            self.play_sound()

    def cancel(self):
        if self.busy():
            self.worker.requestInterruption()
            self.status.setText('Stopping after the current frame…')

    def closeEvent(self, event):
        if self.busy():
            QMessageBox.information(self, 'Batch export', 'Cancel the batch first, or wait until it finishes.')
            event.ignore()
            return
        super().closeEvent(event)
