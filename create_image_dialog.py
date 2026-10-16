"""Create Image window: local AI models for line art, new images and edits.

Three jobs:
  * Line art for my image: the AI redraws your image as clean black line art;
    StrokeScribe traces those lines and paints your original colours.
  * Create an image from text.
  * Edit an image with an instruction.

Models run on this PC through the AI engine (ComfyUI), installed on request.
The version of each model is chosen for this PC's graphics card and memory.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox,
    QPlainTextEdit, QProgressBar, QSpinBox, QCheckBox, QFileDialog, QMessageBox, QFrame,
    QButtonGroup, QSizePolicy,
)

import ai_engine
import ai_models
from ai_workflows import LINE_ART_PROMPT, SIZES, SOUND_PROMPTS, build

TASKS = (('lineart', 'Line art for my image'), ('generate', 'Create from text'),
         ('edit', 'Edit an image'), ('sound', 'Create a sound'))
SOUND_SETTINGS = {'Pencil': 'sound_pencil_file', 'Brush': 'sound_brush_file', 'Eraser': 'sound_eraser_file'}


class AIWorker(QThread):
    """Install, download or generate in the background."""
    progress = Signal(int, str)        # percent (-1 = unknown), message
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, job, **kw):
        super().__init__()
        self.job = job
        self.kw = kw
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def cancelled(self):
        return self._cancel

    def run(self):
        try:
            getattr(self, '_' + self.job)(**self.kw)
        except ai_engine.Cancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _install(self, paths, nvidia):
        ai_engine.install_engine(
            paths, nvidia, log=self.log.emit,
            step=lambda i, n, text: self.progress.emit(round(100 * i / n), text + '…'),
            cancelled=self.cancelled)
        self.done.emit('installed')

    def _download(self, paths, files, name):
        started = time.time()

        def report(done, total, file_name):
            rate = done / max(1., time.time() - started) / 1e6
            self.progress.emit(round(100 * done / max(1, total)),
                               f'Downloading {name}: {done / 1e9:.1f} of {total / 1e9:.1f} GB '
                               f'({rate:.0f} MB/s) — {file_name}')
        ai_engine.download_model(paths, files, report, self.cancelled)
        self.done.emit('downloaded')

    def _generate(self, engine, workflow, image_path):
        self.progress.emit(-1, 'Starting the AI engine (the first time takes a minute)…')
        engine.start(cancelled=self.cancelled)
        if image_path:
            name = engine.put_input(image_path)
            for node in workflow.values():
                if node['class_type'] == 'LoadImage':
                    node['inputs']['image'] = name
        self.progress.emit(-1, 'Loading the model…')
        engine.percent = None
        import threading
        result = {}

        def job():
            try:
                result['path'] = engine.run(workflow, cancelled=self.cancelled)
            except Exception as exc:
                result['error'] = exc
        thread = threading.Thread(target=job, daemon=True)
        thread.start()
        while thread.is_alive():
            thread.join(.5)
            if engine.percent is not None:
                self.progress.emit(engine.percent, f'Creating… {engine.percent}%')
        if 'error' in result:
            raise result['error']
        self.done.emit(str(result['path']))


class CreateImageDialog(QDialog):
    """use_result(kind, path, original) is called with kind 'lineart' or 'image'."""

    def __init__(self, parent=None, current_image=None, use_result=None, engine=None,
                 hardware=None, task=None):
        super().__init__(parent)
        self.setWindowTitle('Create Image or Sound (AI)')
        self.resize(980, 720)
        self.use_result = use_result
        self.settings = ai_engine.load_settings()
        self.paths = ai_engine.Paths(self.settings['root'])
        self.engine = engine or ai_engine.Engine(self.paths)
        self.hw = hardware or ai_models.detect_hardware()
        self.image_path = current_image
        self.result_path = None
        self.worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16); root.setSpacing(10)
        title = QLabel('Create Image'); title.setObjectName('dialogTitle')
        title.setStyleSheet('font-size: 18px; font-weight: 700;')
        root.addWidget(title)
        self.hw_label = QLabel('Your PC: ' + self.hw.summary()); self.hw_label.setObjectName('note')
        self.hw_label.setWordWrap(True)
        root.addWidget(self.hw_label)

        # Engine row
        engine_row = QHBoxLayout()
        self.engine_label = QLabel(); self.engine_label.setWordWrap(True)
        engine_row.addWidget(self.engine_label, 1)
        self.folder_button = QPushButton('Change folder…'); self.folder_button.setObjectName('subtle')
        self.folder_button.clicked.connect(self.change_folder)
        engine_row.addWidget(self.folder_button)
        self.install_button = QPushButton('Install AI engine')
        self.install_button.clicked.connect(self.install_engine)
        engine_row.addWidget(self.install_button)
        root.addLayout(engine_row)

        # Task buttons
        tasks = QHBoxLayout(); tasks.setSpacing(6)
        self.task_group = QButtonGroup(self); self.task_buttons = {}
        for key, text in TASKS:
            button = QPushButton(text); button.setCheckable(True); button.setMinimumHeight(34)
            button.clicked.connect(lambda checked=False, k=key: self.set_task(k))
            self.task_group.addButton(button); self.task_buttons[key] = button
            tasks.addWidget(button)
        root.addLayout(tasks)

        body = QHBoxLayout(); body.setSpacing(16)
        root.addLayout(body, 1)
        form = QGridLayout(); form.setHorizontalSpacing(10); form.setVerticalSpacing(8)
        left = QFrame(); left.setLayout(form); left.setMinimumWidth(430)
        body.addWidget(left, 0)
        row = 0
        form.addWidget(QLabel('Model'), row, 0)
        self.model_box = QComboBox(); self.model_box.currentIndexChanged.connect(self.refresh)
        form.addWidget(self.model_box, row, 1); row += 1
        self.model_info = QLabel(); self.model_info.setWordWrap(True); self.model_info.setObjectName('note')
        self.model_info.setTextFormat(Qt.TextFormat.RichText)
        self.model_info.setOpenExternalLinks(True)
        form.addWidget(self.model_info, row, 0, 1, 2); row += 1
        form.addWidget(QLabel('Version'), row, 0)
        self.variant_box = QComboBox(); self.variant_box.currentIndexChanged.connect(self.variant_changed)
        self.variant_box.setToolTip('Auto picks the best version for your graphics card. '
                                    'Larger versions look better but need more memory.')
        form.addWidget(self.variant_box, row, 1); row += 1
        self.accept_license = QCheckBox('I accept this model\'s license')
        self.accept_license.toggled.connect(self.license_toggled)
        form.addWidget(self.accept_license, row, 0, 1, 2); row += 1
        self.download_button = QPushButton('Download model'); self.download_button.setObjectName('primary')
        self.download_button.clicked.connect(self.download_model)
        form.addWidget(self.download_button, row, 0, 1, 2); row += 1

        self.image_title = QLabel('Image')
        form.addWidget(self.image_title, row, 0)
        image_row = QHBoxLayout()
        self.image_label = QLabel(); self.image_label.setObjectName('note'); self.image_label.setWordWrap(True)
        image_row.addWidget(self.image_label, 1)
        choose = QPushButton('Choose…'); choose.clicked.connect(self.choose_image)
        image_row.addWidget(choose)
        self.image_widgets = (self.image_title, self.image_label, choose)
        form.addLayout(image_row, row, 1); row += 1
        form.addWidget(QLabel('Prompt'), row, 0, Qt.AlignmentFlag.AlignTop)
        self.prompt = QPlainTextEdit(); self.prompt.setMinimumHeight(96)
        form.addWidget(self.prompt, row, 1); row += 1
        self.size_label = QLabel('Size')
        form.addWidget(self.size_label, row, 0)
        self.size_box = QComboBox(); self.size_box.addItems(list(SIZES))
        form.addWidget(self.size_box, row, 1); row += 1
        # Create a sound: what the sound is for, and how long.
        self.sound_for_label = QLabel('Sound for')
        form.addWidget(self.sound_for_label, row, 0)
        self.sound_for = QComboBox(); self.sound_for.addItems(list(SOUND_PROMPTS))
        self.sound_for.setToolTip('Fills in a description for that sound; you can change the words.')
        self.sound_for.activated.connect(lambda i: self.prompt.setPlainText(SOUND_PROMPTS[self.sound_for.currentText()]))
        self.sound_for.activated.connect(lambda i: self.use_button.setText(self.use_text()))
        form.addWidget(self.sound_for, row, 1); row += 1
        self.length_label = QLabel('Length (s)')
        form.addWidget(self.length_label, row, 0)
        self.sound_seconds = QSpinBox(); self.sound_seconds.setRange(2, 30); self.sound_seconds.setValue(8)
        self.sound_seconds.setToolTip('A few seconds is enough: StrokeScribe loops it while the pen moves.')
        form.addWidget(self.sound_seconds, row, 1); row += 1
        self.sound_widgets = (self.sound_for_label, self.sound_for, self.length_label, self.sound_seconds)
        form.addWidget(QLabel('Seed'), row, 0)
        seed_row = QHBoxLayout()
        self.seed = QSpinBox(); self.seed.setRange(1, 2**31 - 1); self.seed.setValue(ai_engine.new_seed() % (2**31 - 1))
        seed_row.addWidget(self.seed, 1)
        self.new_seed = QCheckBox('New seed each time'); self.new_seed.setChecked(True)
        seed_row.addWidget(self.new_seed)
        form.addLayout(seed_row, row, 1); row += 1
        form.setRowStretch(row, 1)

        right = QVBoxLayout(); body.addLayout(right, 1)
        self.preview = QLabel('The result appears here.')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(360, 300)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setObjectName('monitorWell')
        self.preview.setStyleSheet('border-radius: 6px;')
        right.addWidget(self.preview, 1)
        actions = QHBoxLayout()
        self.use_button = QPushButton('Draw it in StrokeScribe'); self.use_button.setObjectName('primary')
        self.use_button.clicked.connect(self.use)
        self.save_button = QPushButton('Save image…'); self.save_button.clicked.connect(self.save)
        self.play_button = QPushButton('▶ Listen'); self.play_button.clicked.connect(self.listen)
        actions.addWidget(self.play_button)
        actions.addWidget(self.use_button, 1); actions.addWidget(self.save_button)
        right.addLayout(actions)
        self.player = None

        bottom = QHBoxLayout()
        self.status = QLabel('Ready.'); self.status.setObjectName('status'); self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.progress = QProgressBar(); self.progress.setFixedWidth(220); self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        bottom.addWidget(self.progress)
        self.log_button = QPushButton('Engine log'); self.log_button.setObjectName('subtle')
        self.log_button.setCheckable(True)
        bottom.addWidget(self.log_button)
        self.cancel_button = QPushButton('Cancel'); self.cancel_button.clicked.connect(self.cancel)
        bottom.addWidget(self.cancel_button)
        self.generate_button = QPushButton('Generate'); self.generate_button.setObjectName('primary')
        self.generate_button.clicked.connect(self.generate)
        bottom.addWidget(self.generate_button)
        root.addLayout(bottom)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(140)
        self.log_view.setVisible(False)
        self.log_button.toggled.connect(self.log_view.setVisible)
        root.addWidget(self.log_view)

        self.task = None
        self.set_task(task or ('lineart' if current_image else 'generate'))

    # ------------------------------------------------------------ state
    def models_for_task(self):
        need = self.task if self.task in ('generate', 'sound') else 'edit'
        return [m for m in ai_models.MODELS if need in m.tasks]

    def set_task(self, key):
        self.task = key
        for k, button in self.task_buttons.items():
            button.setChecked(k == key)
        self.model_box.blockSignals(True)
        self.model_box.clear()
        best = 0
        for i, m in enumerate(self.models_for_task()):
            variant, fit = ai_models.choose_variant(m, self.hw)
            self.model_box.addItem(f'{m.name}  —  {ai_models.fit_text(fit)}', m.id)
        self.model_box.blockSignals(False)
        self.model_box.setCurrentIndex(best)
        self.prompt.setPlainText(LINE_ART_PROMPT if key == 'lineart' else
                                 'Make the background plain white.' if key == 'edit' else
                                 SOUND_PROMPTS[self.sound_for.currentText()] if key == 'sound' else
                                 'A friendly cartoon coffee cup with steam, bold clean shapes, '
                                 'flat colours, white background')
        for w in self.image_widgets:
            w.setVisible(key not in ('generate', 'sound'))
        self.size_box.setVisible(key == 'generate'); self.size_label.setVisible(key == 'generate')
        for w in self.sound_widgets:
            w.setVisible(key == 'sound')
        self.play_button.setVisible(key == 'sound')
        self.result_path = None
        self.preview.setPixmap(QPixmap()); self.preview.setText('The result appears here.')
        self.use_button.setText(self.use_text())
        self.save_button.setText('Save sound…' if key == 'sound' else 'Save image…')
        self.refresh()

    def use_text(self):
        if self.task == 'sound':
            return f'Use as {self.sound_for.currentText().lower()} sound'
        return 'Draw it in StrokeScribe' if self.task == 'lineart' else 'Use as image source'

    def model(self):
        return ai_models.BY_ID.get(self.model_box.currentData()) or self.models_for_task()[0]

    def variant(self):
        model = self.model()
        chosen = self.variant_box.currentData()
        for v in model.variants:
            if v.id == chosen:
                return v
        return ai_models.choose_variant(model, self.hw)[0]

    def model_files(self):
        return self.model().files(self.variant(), self.hw.ram_gb)

    def variant_changed(self, *args):
        if self.variant_box.signalsBlocked():
            return
        overrides = self.settings.setdefault('variant_override', {})
        overrides[self.model().id] = self.variant_box.currentData() or ''
        ai_engine.save_settings(self.settings)
        self.refresh()

    def refresh(self, *args):
        model = self.model()
        auto, fit = ai_models.choose_variant(model, self.hw)
        self.variant_box.blockSignals(True)
        self.variant_box.clear()
        self.variant_box.addItem(f'Auto: {auto.label}', '')
        for v in model.variants:
            self.variant_box.addItem(f'{v.label} — needs about {v.min_vram_gb:.0f} GB', v.id)
        saved = self.settings.get('variant_override', {}).get(model.id, '')
        index = self.variant_box.findData(saved)
        self.variant_box.setCurrentIndex(max(0, index))
        self.variant_box.blockSignals(False)
        variant = self.variant()
        files = self.model_files()
        size = sum(f.size for f in files)
        have = self.paths.has_files(files)
        import theme
        license_link = (f'<a style="color:{theme.colors()["accent"]}" href="{model.license_url}">'
                        f'{model.license}</a>')
        note = f' {variant.note}' if variant.note else ''
        self.model_info.setText(
            f'<b>{model.maker}</b> — {model.summary}<br>License: {license_link}. {model.commercial}<br>'
            f'This PC: <b>{ai_models.fit_text(fit)}</b> → {variant.label}, '
            f'{ai_models.gb(size)} download.{note}')
        self.accept_license.setVisible(model.needs_acceptance)
        accepted = model.id in self.settings.get('accepted_licenses', [])
        self.accept_license.blockSignals(True)
        self.accept_license.setChecked(accepted)
        self.accept_license.blockSignals(False)
        license_ok = not model.needs_acceptance or accepted
        engine_ok = self.paths.engine_installed()
        busy = self.worker is not None and self.worker.isRunning()
        self.engine_label.setText(
            ('AI engine: installed' if engine_ok else
             'AI engine: not installed yet (about 5 GB; needs internet once)')
            + f'  •  Folder: {self.paths.root}'
            + (f'  •  {ai_engine.free_space_gb(self.paths.root):.0f} GB free'
               if ai_engine.free_space_gb(self.paths.root) is not None else ''))
        self.install_button.setVisible(not engine_ok)
        self.install_button.setEnabled(not busy)
        self.download_button.setVisible(not have)
        self.download_button.setText(f'Download model ({ai_models.gb(size)})')
        self.download_button.setToolTip(f'{model.name} — {variant.label}: model, text encoder and '
                                        'helper files. Downloads continue where they stopped.')
        self.download_button.setEnabled(license_ok and not busy)
        self.image_label.setText(Path(self.image_path).name if self.image_path else 'No image chosen')
        need_image = self.task not in ('generate', 'sound')
        self.use_button.setText(self.use_text())
        self.play_button.setEnabled(self.result_path is not None and not busy)
        ready = engine_ok and have and license_ok and (self.image_path or not need_image)
        self.generate_button.setEnabled(bool(ready) and not busy)
        self.cancel_button.setEnabled(busy)
        self.use_button.setEnabled(self.result_path is not None and not busy)
        self.save_button.setEnabled(self.result_path is not None and not busy)
        if not busy:
            if not engine_ok:
                self.status.setText('Step 1: install the AI engine.')
            elif not have:
                self.status.setText('Step 2: download the model.')
            elif need_image and not self.image_path:
                self.status.setText('Choose an image.')
            elif self.status.text() in ('Step 1: install the AI engine.', 'Step 2: download the model.',
                                        'Choose an image.'):
                self.status.setText('Ready.')

    def license_toggled(self, checked):
        accepted = self.settings.setdefault('accepted_licenses', [])
        model_id = self.model().id
        if checked and model_id not in accepted:
            accepted.append(model_id)
        elif not checked and model_id in accepted:
            accepted.remove(model_id)
        ai_engine.save_settings(self.settings)
        self.refresh()

    # ------------------------------------------------------------ actions
    def change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Folder for the AI engine and models (needs 20–80 GB)',
                                                  str(self.paths.root.parent))
        if not folder:
            return
        self.settings['root'] = str(Path(folder) / 'StrokeScribe-AI')
        ai_engine.save_settings(self.settings)
        self.engine.stop()
        self.paths = ai_engine.Paths(self.settings['root'])
        self.engine.paths = self.paths
        self.refresh()

    def choose_image(self):
        name, _ = QFileDialog.getOpenFileName(self, 'Choose an image', '',
                                              'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if name:
            self.image_path = name
            self.refresh()

    def _start(self, worker, on_done):
        self.worker = worker
        worker.progress.connect(self.on_progress)
        worker.log.connect(self.log_view.appendPlainText)
        worker.done.connect(on_done)
        worker.failed.connect(self.on_failed)
        worker.finished.connect(self.refresh)
        worker.start()
        self.refresh()

    def install_engine(self):
        if not self.hw.nvidia and self.task != 'sound' and QMessageBox.question(
                self, 'No NVIDIA graphics card',
                'No NVIDIA graphics card was found. The engine can be installed for the processor '
                'only, but making an image will be very slow (many minutes). Install anyway?') \
                != QMessageBox.StandardButton.Yes:
            return
        self.log_view.setVisible(True); self.log_button.setChecked(True)
        self._start(AIWorker('install', paths=self.paths, nvidia=self.hw.nvidia),
                    lambda _: self.status.setText('AI engine installed.'))

    def download_model(self):
        model, variant = self.model(), self.variant()
        files = [f for f in self.model_files() if not self.paths.has_files([f])]
        need = sum(f.size for f in files) / 1e9
        free = ai_engine.free_space_gb(self.paths.root)
        if free is not None and free < need + 2:
            QMessageBox.warning(self, 'Not enough space',
                                f'This needs about {need:.0f} GB but only {free:.0f} GB is free. '
                                'Free some space or choose another folder.')
            return
        self._start(AIWorker('download', paths=self.paths, files=files, name=model.name),
                    lambda _: self.status.setText(f'{model.name} is ready.'))

    def generate(self):
        model, variant = self.model(), self.variant()
        if self.new_seed.isChecked():
            self.seed.setValue(ai_engine.new_seed() % (2**31 - 1))
        width, height = SIZES[self.size_box.currentText()]
        image = self.image_path if self.task != 'generate' else None
        if self.task == 'sound':
            image = None
        workflow = build(model, variant, self.prompt.toPlainText().strip(), self.seed.value(),
                         image_name='input.png' if image else None, width=width, height=height,
                         ram_gb=self.hw.ram_gb, seconds=self.sound_seconds.value())
        self.result_path = None
        self._start(AIWorker('generate', engine=self.engine, workflow=workflow, image_path=image),
                    self.on_result)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText('Stopping…')

    def on_progress(self, percent, text):
        if percent < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100); self.progress.setValue(percent)
        self.status.setText(text)

    def on_failed(self, message):
        self.progress.setRange(0, 100); self.progress.setValue(0)
        self.status.setText(message.splitlines()[0][:200] if message else 'Stopped.')
        if message and 'cancel' not in message.lower() and 'paused' not in message.lower():
            self.log_view.appendPlainText(message)
            QMessageBox.warning(self, 'Create Image', message[:1500])

    def on_result(self, path):
        if self.task == 'sound':
            # AI sounds come out quiet: bring them to a normal level first.
            from sound import normalized_copy
            louder = normalized_copy(path, Path(path).with_name(Path(path).stem + '_normal.wav'))
            if louder is not None:
                path = str(louder)
        self.result_path = path
        self.progress.setRange(0, 100); self.progress.setValue(100)
        if self.task == 'sound':
            self.status.setText('Done. Click ▶ Listen; if you like it, click “' + self.use_text() + '”. '
                                'Not right? Generate again (new seed) or change the words.')
            self.preview.setPixmap(waveform(path, self.preview.width(), self.preview.height()))
            self.refresh()
            from PySide6.QtGui import QGuiApplication
            if QGuiApplication.platformName() != 'offscreen':
                self.listen()                     # play it right away
            return
        self.status.setText('Done. ' + ('Click “Draw it in StrokeScribe” to trace these lines and paint '
                                        'your original colours.' if self.task == 'lineart' else
                                        'Use it as an image source or save it.'))
        pix = QPixmap(path)
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        self.refresh()

    def listen(self):
        if not self.result_path:
            return
        try:
            if self.player is None:
                from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
                self.player = QMediaPlayer(self); self.audio_out = QAudioOutput(self)
                self.player.setAudioOutput(self.audio_out)
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(str(self.result_path)))
            self.player.play()
        except Exception as exc:
            self.status.setText('Cannot play here: ' + str(exc)[:120] + ' — use Save sound… to listen.')

    def use(self):
        if not self.result_path or not self.use_result:
            return
        if self.task == 'sound':
            self.use_result('sound', self.result_path, SOUND_SETTINGS[self.sound_for.currentText()])
            self.accept()
            return
        if self.task == 'lineart':
            self.use_result('lineart', self.result_path, self.image_path)
        else:
            self.use_result('image', self.result_path, None)
        self.accept()

    def save(self):
        if not self.result_path:
            return
        sound = self.task == 'sound'
        kind = Path(self.result_path).suffix.lower().lstrip('.') or 'flac'
        name, _ = QFileDialog.getSaveFileName(self, 'Save sound' if sound else 'Save image',
                                              Path(self.result_path).name,
                                              f'{kind.upper()} (*.{kind})' if sound else 'PNG (*.png)')
        if name:
            import shutil
            shutil.copy(self.result_path, name)
            self.status.setText('Saved ' + name)

    def closeEvent(self, event):
        if self.player is not None:
            self.player.stop()
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


def waveform(path, width, height):
    """A simple picture of the sound (loudness over time)."""
    from PySide6.QtGui import QColor, QPainter, QPen
    import numpy as np
    import theme
    from sound import RATE, load_recording
    width, height = max(200, width), max(120, height)
    pix = QPixmap(width, height); pix.fill(QColor(theme.colors().get('panel', '#1d2430')))
    data = load_recording(path)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if data is None or not len(data):
        p.setPen(QColor(theme.colors()['muted']))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, 'The sound could not be read.')
        p.end(); return pix
    columns = np.array_split(np.abs(data), width - 20)
    peak = max(1e-6, float(np.abs(data).max()))
    p.setPen(QPen(QColor(theme.colors()['accent']), 1))
    mid = height / 2
    for x, col in enumerate(columns):
        h = (float(col.max()) if len(col) else 0) / peak * (height * .42)
        p.drawLine(10 + x, int(mid - h), 10 + x, int(mid + h))
    p.setPen(QColor(theme.colors()['muted']))
    p.drawText(12, height - 10, f'{len(data) / RATE:.1f} s')
    p.end()
    return pix
