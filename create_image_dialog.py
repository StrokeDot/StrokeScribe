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

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QRectF, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QDesktopServices, QPainter, QColor, QLinearGradient, QPen, QFont, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox,
    QPlainTextEdit, QProgressBar, QSpinBox, QCheckBox, QFileDialog, QMessageBox, QFrame,
    QButtonGroup, QSizePolicy, QScrollArea, QBoxLayout, QWidget,
)

import ai_engine
import ai_models
import model_updates_live
from ai_workflows import LINE_ART_PROMPT, SIZES, SOUND_PROMPTS, build

TASKS = (('lineart', 'Line art for my image'), ('generate', 'Create from text'),
         ('edit', 'Edit an image'), ('sound', 'Create a sound'))
GENERATE_PROMPT = ('A friendly cartoon coffee cup with steam, bold clean shapes, '
                   'flat colours, white background')
EDIT_PROMPT = 'Make the background plain white.'


def suggested_prompt(task, sound_for='Pencil'):
    """The ready-made prompt of each tab (the Suggested prompt button brings it back)."""
    return {'lineart': LINE_ART_PROMPT, 'edit': EDIT_PROMPT, 'generate': GENERATE_PROMPT,
            'sound': SOUND_PROMPTS.get(sound_for, next(iter(SOUND_PROMPTS.values())))}.get(task, GENERATE_PROMPT)


SOUND_SETTINGS = {'Pencil': 'sound_pencil_file', 'Brush': 'sound_brush_file', 'Eraser': 'sound_eraser_file'}


class ModelUpdateWorker(QThread):
    """Check publisher revisions or replace a single verified model off the UI thread."""
    progress_message = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, mode, paths, hardware=None, state=None):
        super().__init__()
        self.mode, self.paths = mode, paths
        self.hardware, self.state = hardware, state
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def cancelled(self):
        return self._cancel

    def run(self):
        try:
            if self.mode == 'scan':
                result = model_updates_live.inspect_models(
                    self.paths, self.hardware,
                    progress=self.progress_message.emit,
                    cancelled=self.cancelled)
            elif self.mode == 'update':
                def progress(done, total, name):
                    self.progress_message.emit(
                        f'Updating {name}: {done / 1e9:.1f} / {total / 1e9:.1f} GB')
                result = model_updates_live.install_verified_revision(
                    self.paths, self.state, progress, self.cancelled)
            else:
                raise ValueError('Unknown model update operation.')
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


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
        recent = []                      # (time, bytes): speed over the last few seconds

        def report(done, total, file_name):
            now = time.time()
            recent.append((now, done))
            while len(recent) > 2 and now - recent[0][0] > 5:
                recent.pop(0)
            span = now - recent[0][0]
            rate = (done - recent[0][1]) / span / 1e6 if span > .5 else 0.
            if recent and now - getattr(report, 'shown', 0) < .4 and done < total:
                return                   # update the window a few times a second
            report.shown = now
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


class PlaceholderIcon(QLabel):
    """Original vector placeholder icon; no external font or bitmap needed."""
    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#72798d'),3))
        p.drawRoundedRect(QRectF(5,5,48,48),5,5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#72798d'))
        p.drawEllipse(QPointF(20,20),5,5)
        mountain=QPainterPath(QPointF(9,45))
        for x,y in ((23,29),(31,36),(39,25),(50,41),(50,49),(9,49)):
            mountain.lineTo(x,y)
        mountain.closeSubpath();p.drawPath(mountain)


class ResultPreview(QLabel):
    """Result monitor with an illustrated empty state that survives resizing."""
    resized=Signal()

    def __init__(self, text='', parent=None):
        super().__init__('',parent)
        self.placeholder=QFrame(self)
        self.placeholder.setObjectName('resultPlaceholder')
        self.placeholder.setStyleSheet(
            'QFrame#resultPlaceholder { border:1px dashed #434b60; border-radius:10px; }'
            'QLabel { border:none; background:transparent; color:#bac2d4; }')
        layout=QVBoxLayout(self.placeholder)
        layout.setContentsMargins(18,22,18,22)
        layout.setSpacing(10);layout.addStretch(1)
        icon=PlaceholderIcon();icon.setObjectName('resultPlaceholderIcon')
        icon.setFixedSize(58,58)
        layout.addWidget(icon,0,Qt.AlignmentFlag.AlignHCenter)
        title=QLabel('The result appears here.')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter);title.setWordWrap(True)
        title.setStyleSheet('font-weight:600; font-size:13px; color:#e0e3ec;')
        layout.addWidget(title)
        self.placeholder_note=QLabel('Generate an image from your prompt to see the result.')
        self.placeholder_note.setWordWrap(True)
        self.placeholder_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder_note);layout.addStretch(1)

    def setPixmap(self, pixmap):
        self.placeholder.setVisible(pixmap.isNull())
        super().setPixmap(pixmap)

    def setText(self, text):
        # Existing callers clear the label before drawing. Empty state is a
        # child widget, so text clearing must not accidentally replace it.
        super().setText('')
        self.placeholder.setVisible(bool(text))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        w=max(1,min(300,self.width()-40));h=max(1,min(400,self.height()-40))
        self.placeholder.setGeometry((self.width()-w)//2,(self.height()-h)//2,w,h)
        self.resized.emit()


class CreateImageDialog(QDialog):
    """use_result(kind, path, original) is called with kind 'lineart' or 'image'."""

    def __init__(self, parent=None, current_image=None, use_result=None, engine=None,
                 hardware=None, task=None):
        super().__init__(parent)
        self.setWindowTitle('Create Image or Sound (AI)')
        self.resize(1100, 800)
        self.setMinimumSize(900, 620)
        self.use_result = use_result
        self.settings = ai_engine.load_settings()
        self.paths = ai_engine.Paths(self.settings['root'])
        self.engine = engine or ai_engine.Engine(self.paths)
        self.hw = hardware or ai_models.detect_hardware()
        self.image_path = current_image
        self.result_path = None; self.kept_path = None
        self.worker = None

        # The drawer is a sibling, never an overlay over generation controls.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(18,16,18,16);outer.setSpacing(14)
        self.main_panel=QWidget()
        self.main_panel.setMinimumWidth(440)
        outer.addWidget(self.main_panel,1)
        root = QVBoxLayout(self.main_panel)
        root.setContentsMargins(0,0,0,0); root.setSpacing(10)
        self.model_manager=None
        self.live_update_worker = None
        self._rescan_after_update = False
        title = QLabel('Create Image'); title.setObjectName('dialogTitle')
        title.setStyleSheet('font-size: 18px; font-weight: 700;')
        header=QHBoxLayout()
        header.addWidget(title,1)
        self.check_updates_button=QPushButton('↻  Check for updates')
        self.check_updates_button.setCheckable(True)
        self.check_updates_button.setAutoDefault(False)
        self.check_updates_button.setAccessibleName('Check for image generator updates')
        self.check_updates_button.setToolTip('Check official image model revisions installed on this PC')
        self.check_updates_button.clicked.connect(self.open_updates)
        header.addWidget(self.check_updates_button)
        root.addLayout(header)
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
        self.tasks_layout = QGridLayout();self.tasks_layout.setSpacing(6)
        tasks = self.tasks_layout
        self.task_group = QButtonGroup(self); self.task_buttons = {}
        for key, text in TASKS:
            button = QPushButton(text); button.setCheckable(True); button.setMinimumHeight(34)
            button.clicked.connect(lambda checked=False, k=key: self.set_task(k))
            self.task_group.addButton(button); self.task_buttons[key] = button
            tasks.addWidget(button,0,len(self.task_buttons)-1)
        root.addLayout(tasks)

        self.body_scroll=QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_widget=QWidget()
        body = QBoxLayout(QBoxLayout.Direction.LeftToRight,body_widget)
        body.setContentsMargins(0,0,4,0);body.setSpacing(16)
        self.body_layout=body
        self.body_scroll.setWidget(body_widget)
        root.addWidget(self.body_scroll,1)
        form = QGridLayout(); form.setHorizontalSpacing(10); form.setVerticalSpacing(8)
        left = QFrame(); left.setLayout(form); left.setMinimumWidth(380)
        body.addWidget(left, 1)
        row = 0
        form.addWidget(QLabel('Model'), row, 0)
        self.model_box = QComboBox(); self.model_box.currentIndexChanged.connect(self.refresh)
        self.model_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_box.setMinimumContentsLength(12)
        model_row=QHBoxLayout();model_row.setSpacing(8)
        model_row.addWidget(self.model_box,1)
        self.manage_models_button=QPushButton('⚙  Manage models…')
        self.manage_models_button.setAutoDefault(False)
        self.manage_models_button.clicked.connect(self.manage_models)
        model_row.addWidget(self.manage_models_button)
        form.addLayout(model_row,row,1);row+=1
        self.model_info = QLabel(); self.model_info.setWordWrap(True); self.model_info.setObjectName('note')
        self.model_info.setTextFormat(Qt.TextFormat.RichText)
        self.model_info.setOpenExternalLinks(True)
        form.addWidget(self.model_info, row, 0, 1, 2); row += 1
        form.addWidget(QLabel('Version'), row, 0)
        self.variant_box = QComboBox(); self.variant_box.currentIndexChanged.connect(self.variant_changed)
        self.variant_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.variant_box.setMinimumContentsLength(16)
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
        prompt_row = QHBoxLayout(); prompt_row.addStretch(1)
        self.suggested_button = QPushButton('↺ Suggested prompt'); self.suggested_button.setObjectName('subtle')
        self.suggested_button.setToolTip('Put back the ready-made prompt for this tab (try your own words, '
                                         'then come back to it with one click).')
        self.suggested_button.clicked.connect(
            lambda checked=False: self.prompt.setPlainText(suggested_prompt(self.task, self.sound_for.currentText())))
        prompt_row.addWidget(self.suggested_button)
        form.addLayout(prompt_row, row, 1); row += 1
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
        self.preview = ResultPreview('The result appears here.')
        self.preview.resized.connect(self.refit_preview)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(300, 240)
        # Pixmap dimensions must never force the reflowed monitor to stay large.
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setObjectName('monitorWell')
        self.preview.setStyleSheet('border-radius: 6px;')
        right.addWidget(self.preview, 1)
        actions = QHBoxLayout()
        self.use_button = QPushButton('Draw it in StrokeScribe'); self.use_button.setObjectName('primary')
        self.use_button.clicked.connect(self.use)
        self.save_button = QPushButton('Save image…'); self.save_button.clicked.connect(self.save)
        self.play_button = QPushButton('▶ Listen'); self.play_button.clicked.connect(self.listen)
        actions.addWidget(self.play_button)
        self.folder_button = QPushButton('Show in folder'); self.folder_button.setObjectName('subtle')
        self.folder_button.setToolTip('Every picture you create is kept in your Library → Images.')
        self.folder_button.clicked.connect(self.show_in_folder)
        actions.addWidget(self.use_button, 1); actions.addWidget(self.save_button); actions.addWidget(self.folder_button)
        right.addLayout(actions)
        self.player = None

        bottom = QHBoxLayout()
        self.status = QLabel('Ready.'); self.status.setObjectName('status'); self.status.setWordWrap(True)
        root.addWidget(self.status)
        bottom.addStretch(1)
        self.progress = QProgressBar(); self.progress.setMaximumWidth(280)
        self.progress.setMinimumWidth(80); self.progress.setTextVisible(True)
        self.progress.setFixedHeight(18); self.progress.setFormat('%p%')
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_motion=QVariantAnimation(self)
        self.progress_motion.setDuration(240)
        self.progress_motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.progress_motion.valueChanged.connect(lambda value:self.progress.setValue(round(value)))
        bottom.addWidget(self.progress,1)
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

        # Each tab keeps its own prompt and its last result (switching tabs loses nothing).
        self.memory = {}
        self.running_task = None
        self.work = dict(percent=-1, text='', started=0.)
        self.work_timer = QTimer(self); self.work_timer.setInterval(16); self.work_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.work_timer.timeout.connect(self.paint_working)
        self.reveal_timer = QTimer(self); self.reveal_timer.setInterval(16); self.reveal_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.reveal_timer.timeout.connect(self.reveal_step)
        from image_generator_updates import UpdatePanel
        self.updates_panel=UpdatePanel(self)
        self.updates_panel.hide()
        self.updates_panel.close_requested.connect(self.close_updates)
        self.updates_panel.action_requested.connect(self.model_update_action)
        self.updates_panel.cancel_requested.connect(self.cancel_live_model_update)
        outer.addWidget(self.updates_panel)
        self._drawer_open=False
        self.drawer_motion=QVariantAnimation(self)
        self.drawer_motion.setDuration(250)
        self.drawer_motion.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.drawer_motion.valueChanged.connect(lambda value:self.updates_panel.setFixedWidth(round(value)))
        self.drawer_motion.finished.connect(self._finish_drawer_motion)
        self.task = None
        self.set_task(task or ('lineart' if current_image else 'generate'))

    def open_updates(self):
        self._animate_drawer(True)
        self.check_live_model_updates()

    def _run_live_model_worker(self, worker, mode):
        if self.live_update_worker is not None and self.live_update_worker.isRunning():
            self.updates_panel.show_feedback('A model check or download is already in progress.')
            return
        self.live_update_worker = worker
        self.check_updates_button.setEnabled(False)
        self.updates_panel.set_busy(True)
        self.updates_panel.show_feedback(
            'Checking the actual AI folder and official model sources…' if mode == 'scan'
            else 'Downloading and verifying the replacement. The current model stays in place.')
        worker.progress_message.connect(self.updates_panel.show_feedback)
        worker.succeeded.connect(lambda result: self.on_live_model_done(mode, result))
        worker.failed.connect(self.on_live_model_failed)
        worker.finished.connect(self.on_live_model_finished)
        worker.start()

    def check_live_model_updates(self):
        if self.live_update_worker is not None and self.live_update_worker.isRunning():
            return
        self._run_live_model_worker(
            ModelUpdateWorker('scan', self.paths, hardware=self.hw), 'scan')

    def on_live_model_done(self, mode, result):
        if mode == 'scan':
            self.updates_panel.set_items(result)
            changed = sum(s.status == 'update_available' for s in result)
            unknown = sum(s.status == 'unverified' for s in result)
            if changed:
                summary=f'{changed} installed model(s) have a different official file available.'
            elif unknown:
                summary='No updates confirmed. Some installed models could not be checked; try again later.'
            else:
                summary='No updates found for the installed models that were checked.'
            self.updates_panel.show_feedback(summary)
        else:
            self.updates_panel.show_feedback(
                'Model updated and verified. The previous weights were kept as a backup.')
            self.refresh()
            self._rescan_after_update = True

    def on_live_model_failed(self, message):
        self.updates_panel.show_feedback('Model operation: ' + message)

    def on_live_model_finished(self):
        self.check_updates_button.setEnabled(True)
        self.updates_panel.set_busy(False)
        # Keep the QThread referenced until the finished signal, never while running.
        self.live_update_worker = None
        if self._rescan_after_update:
            self._rescan_after_update = False
            QTimer.singleShot(0, self.check_live_model_updates)

    def cancel_live_model_update(self):
        if self.live_update_worker is not None and self.live_update_worker.isRunning():
            self.live_update_worker.cancel()
            self.updates_panel.show_feedback('Stopping operation; current model files are retained.')

    def model_update_action(self, action, model_id):
        model = ai_models.BY_ID.get(model_id)
        if model is None:
            self.updates_panel.show_feedback('Model is not in the trusted registry.')
            return
        if action == 'rescan':
            self.check_live_model_updates()
            return
        if self.live_update_worker is not None and self.live_update_worker.isRunning():
            self.updates_panel.show_feedback('Please wait for the current model operation.')
            return
        states = [s for s in self.updates_panel.items if s.model_id == model_id]
        if len(states) != 1:
            self.updates_panel.show_feedback('Recheck model status before continuing.')
            return
        state = states[0]
        if action == 'update':
            if state.status != 'update_available' or state.remote is None:
                self.updates_panel.show_feedback('A verified model replacement is not available.')
                return
            if self.worker is not None and self.worker.isRunning():
                self.updates_panel.show_feedback('Finish or cancel the current generation first.')
                return
            if QMessageBox.question(
                    self, 'Update installed AI model',
                    f'Replace the weights for {state.name} ({state.variant_label})?\n\n'
                    f'Download: {state.remote.size / 1e9:.1f} GB.\n'
                    'The currently installed weights will be kept as a .previous backup.\n'
                    'This may be a changed official revision rather than a newer release.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            # Never replace model weights while the local inference server may use them.
            self.engine.stop()
            self._run_live_model_worker(
                ModelUpdateWorker('update', self.paths, state=state), 'update')
            return
        self.choose_managed_model(model)
        # Preserve the actual installed variant when repairing a model rather
        # than silently downloading the machine's default other quantization.
        idx = self.variant_box.findData(state.variant_id)
        if idx >= 0:
            self.variant_box.setCurrentIndex(idx)
        if action in ('install', 'repair'):
            if not self.paths.engine_installed():
                self.updates_panel.show_feedback('Install the AI engine in the main form first.')
            elif model.needs_acceptance and model.id not in self.settings.get('accepted_licenses', []):
                self.updates_panel.show_feedback('Accept this model’s license in the main form first.')
            else:
                self.download_model()
                self.updates_panel.show_feedback('Started the existing model download in the main form.')
        else:
            self.updates_panel.show_feedback('Selected the model in the main controls.')

    def _animate_drawer(self, opening):
        self.drawer_motion.stop()
        width=self.updates_panel.width() if self.updates_panel.isVisible() else 0
        self._drawer_open=opening
        self.check_updates_button.setChecked(opening)
        self.updates_panel.setFixedWidth(width)
        self.updates_panel.show()
        self.update_layout()
        self.drawer_motion.setStartValue(width)
        self.drawer_motion.setEndValue(400 if opening else 0)
        self.drawer_motion.start()

    def _finish_drawer_motion(self):
        if not self._drawer_open:
            self.updates_panel.hide()
            self.check_updates_button.setFocus()
        self.update_layout()

    def close_updates(self):
        self._animate_drawer(False)

    def reject(self):
        if hasattr(self,'updates_panel') and self.updates_panel.isVisible():
            self.close_updates()
            return
        super().reject()

    def update_layout(self):
        if not hasattr(self,'body_layout'):
            return
        # Use the available left column, including a pending drawer opening.
        drawer_open=hasattr(self,'updates_panel') and (self._drawer_open or not self.updates_panel.isHidden())
        available=self.width()-36-(414 if drawer_open else 0)
        compact=available<850
        self.body_layout.setDirection(QBoxLayout.Direction.TopToBottom if compact
                                      else QBoxLayout.Direction.LeftToRight)
        columns=2 if compact else 4
        for index,button in enumerate(self.task_buttons.values()):
            self.tasks_layout.addWidget(button,index//columns,index%columns)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.update_layout()


    def manage_models(self):
        if self.model_manager is not None:
            self.model_manager.close()
        manager=QDialog(self)
        manager.setWindowTitle('Manage AI models')
        manager.resize(620,500)
        layout=QVBoxLayout(manager)
        note=QLabel('Choose a model to view its variants, license and download options. '
                    'The updates drawer now checks installed weights against their official sources.')
        note.setWordWrap(True);layout.addWidget(note)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();items=QVBoxLayout(content)
        for model in ai_models.MODELS:
            variant,fit=ai_models.choose_variant(model,self.hw)
            card=QFrame();card_layout=QVBoxLayout(card)
            have=self.paths.has_files(model.files(variant,self.hw.ram_gb))
            title=QLabel(model.name+'  —  '+('Ready' if have else 'Download needed'))
            title.setWordWrap(True);card_layout.addWidget(title)
            info=QLabel(f'{model.maker}  •  {variant.label}  •  {ai_models.fit_text(fit)}')
            info.setWordWrap(True);card_layout.addWidget(info)
            choose=QPushButton('Choose model')
            choose.setProperty('modelId',model.id)
            choose.clicked.connect(lambda checked=False,m=model:self.choose_managed_model(m))
            card_layout.addWidget(choose);items.addWidget(card)
        items.addStretch(1);scroll.setWidget(content);layout.addWidget(scroll)
        close=QPushButton('Close');close.clicked.connect(manager.close);layout.addWidget(close)
        self.model_manager=manager
        manager.show()

    def choose_managed_model(self,model):
        task='sound' if 'sound' in model.tasks else 'generate' if 'generate' in model.tasks else 'edit'
        self.set_task(task)
        self.model_box.setCurrentIndex(self.model_box.findData(model.id))
        self.model_box.setFocus()
        if self.model_manager is not None:
            self.model_manager.close()

    # ------------------------------------------------------------ state
    def models_for_task(self):
        need = self.task if self.task in ('generate', 'sound') else 'edit'
        return [m for m in ai_models.MODELS if need in m.tasks]

    def set_task(self, key):
        if self.task is not None:
            self.memory[self.task] = dict(self.memory.get(self.task, {}), prompt=self.prompt.toPlainText(),
                                          result_path=self.result_path, kept_path=self.kept_path)
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
        saved = self.memory.get(key, {})
        self.prompt.setPlainText(saved.get('prompt') or suggested_prompt(key, self.sound_for.currentText()))
        for w in self.image_widgets:
            w.setVisible(key not in ('generate', 'sound'))
        self.size_box.setVisible(key == 'generate'); self.size_label.setVisible(key == 'generate')
        for w in self.sound_widgets:
            w.setVisible(key == 'sound')
        self.play_button.setVisible(key == 'sound')
        self.result_path = saved.get('result_path'); self.kept_path = saved.get('kept_path')
        self.reveal_timer.stop()
        if self.running_task == key and self.worker is not None and self.worker.isRunning():
            self.paint_working()
        else:
            self.show_result(animate=False)
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
        self.manage_models_button.setEnabled(not busy)
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
        self.folder_button.setVisible(bool(getattr(self, 'kept_path', None)))
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
        self.result_path = None; self.kept_path = None
        self.running_task = self.task
        self.memory[self.task] = dict(self.memory.get(self.task, {}), result_path=None, kept_path=None,
                                      prompt=self.prompt.toPlainText(), source=image)
        self.work.update(percent=-1, text='Starting…', started=time.monotonic())
        self.reveal_timer.stop(); self.work_timer.start(); self.paint_working()
        self._start(AIWorker('generate', engine=self.engine, workflow=workflow, image_path=image),
                    self.on_result)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText('Stopping…')

    def on_progress(self, percent, text):
        self.work.update(percent=percent, text=text)
        self.progress_motion.stop()
        if percent < 0:
            self.progress.setRange(0, 0)
        else:
            previous=max(0,self.progress.value()) if self.progress.maximum() else 0
            self.progress.setRange(0, 100)
            self.progress.setValue(min(previous,percent))
            self.progress_motion.setStartValue(float(min(previous,percent)))
            self.progress_motion.setEndValue(float(percent))
            self.progress_motion.start()
        self.status.setText(text)

    def on_failed(self, message):
        self.work_timer.stop()
        self.progress_motion.stop()
        if self.running_task == self.task:
            self.show_result(animate=False)
        self.running_task = None
        self.progress.setRange(0, 100); self.progress.setValue(0)
        self.status.setText(message.splitlines()[0][:200] if message else 'Stopped.')
        if message and 'cancel' not in message.lower() and 'paused' not in message.lower():
            self.log_view.appendPlainText(message)
            QMessageBox.warning(self, 'Create Image', message[:1500])

    def on_result(self, path):
        self.work_timer.stop()
        self.progress_motion.stop()
        task, self.running_task = self.running_task or self.task, None
        if task != self.task:
            # Made for another tab: it waits there (nothing is lost by switching tabs).
            kept = None
            if task != 'sound':
                kept = keep_in_library(path, task, self.memory.get(task, {}).get('prompt', ''))
            self.memory[task] = dict(self.memory.get(task, {}), result_path=path, kept_path=kept)
            name = dict(TASKS).get(task, task)
            self.progress.setRange(0, 100); self.progress.setValue(100)
            self.refresh()
            self.status.setText(f'Your “{name}” result is ready: click that tab to see it.'
                                + (' It is also kept in your Library → Images.' if kept else ''))
            return
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
        self.kept_path = keep_in_library(path, self.task, self.prompt.toPlainText())
        kept = ' Kept in your Library → Images.' if self.kept_path else ''
        self.status.setText('Done.' + kept + ' ' + ('Click “Draw it in StrokeScribe” to trace these lines and paint '
                                                   'your original colours.' if self.task == 'lineart' else
                                                   'Use it as an image source.'))
        self.memory[self.task] = dict(self.memory.get(self.task, {}), result_path=path, kept_path=self.kept_path)
        self.show_result(animate=True)
        self.refresh()

    # ------------------------------------------------------------ the result well
    def refit_preview(self):
        if not getattr(self,'result_path',None) or not hasattr(self,'reveal_timer'):
            return
        if self.reveal_timer.isActive() and self.task!='sound':
            pix=QPixmap(str(self.result_path))
            if not pix.isNull():
                self._shown=pix.scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                self.reveal_step()
        else:
            self.show_result(animate=False)

    def show_result(self, animate=False):
        """Show this tab's result (with a short fade-in when it has just been made)."""
        self.preview.setText('')
        if not self.result_path:
            self.preview.setPixmap(QPixmap()); self.preview.setText('The result appears here.')
            return
        if self.task == 'sound':
            self.preview.setPixmap(waveform(self.result_path, self.preview.width(), self.preview.height()))
            return
        pix = QPixmap(str(self.result_path))
        if pix.isNull():
            self.preview.setPixmap(QPixmap()); self.preview.setText('The result appears here.')
            return
        self._shown = pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        if animate:
            self._reveal = 0.
            self._reveal_started=time.monotonic()
            self.reveal_timer.start(); self.reveal_step()
        else:
            self.preview.setPixmap(self._shown)

    def reveal_step(self):
        """The new picture fades in and settles from slightly bigger (about half a second)."""
        self._reveal = min(1., max(0., (time.monotonic()-getattr(self,'_reveal_started',time.monotonic()-.5))/.5))
        f = 1 - (1 - self._reveal) ** 3
        size = self.preview.size()
        canvas = QPixmap(size); canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(f)
        scale = 1.06 - .06 * f
        w, h = self._shown.width() * scale, self._shown.height() * scale
        painter.drawPixmap(QRectF((size.width() - w) / 2, (size.height() - h) / 2, w, h), self._shown,
                           QRectF(self._shown.rect()))
        painter.end()
        self.preview.setPixmap(canvas)
        if self._reveal >= 1:
            self.reveal_timer.stop()
            self.preview.setPixmap(self._shown)

    def paint_working(self):
        """While the AI works: a light sweeps over the well (over the starting image, dimmed,
        when there is one), a spinner turns, and the percent and time are written."""
        if self.running_task != self.task:
            return
        size = self.preview.size()
        W, H = max(40, size.width()), max(40, size.height())
        canvas = QPixmap(W, H); canvas.fill(QColor('#15171d'))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        now = time.monotonic()
        source = self.memory.get(self.task, {}).get('source')
        if source:
            pix = getattr(self, '_work_source', None)
            if pix is None or getattr(self, '_work_source_path', None) != source:
                self._work_source = pix = QPixmap(str(source)); self._work_source_path = source
            if not pix.isNull():
                fit = pix.scaled(W, H, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter.setOpacity(.28 + .06 * __import__('math').sin(now * 2.2))
                painter.drawPixmap((W - fit.width()) // 2, (H - fit.height()) // 2, fit)
                painter.setOpacity(1.)
        # A soft light sweeping across, again and again.
        phase = (now * .45) % 1.
        x = -W * .6 + phase * W * 2.2
        light = QLinearGradient(QPointF(x, 0), QPointF(x + W * .5, H))
        light.setColorAt(0, QColor(110, 79, 242, 0)); light.setColorAt(.5, QColor(140, 110, 255, 70))
        light.setColorAt(1, QColor(110, 79, 242, 0))
        painter.fillRect(0, 0, W, H, light)
        # The spinner.
        r = min(W, H) * .09
        centre = QPointF(W / 2, H / 2 - r * .6)
        painter.setPen(QPen(QColor(255, 255, 255, 40), max(3., r * .18)))
        painter.drawEllipse(centre, r, r)
        pen = QPen(QColor('#8B6CFF'), max(3., r * .18)); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r),
                        int(-now * 360 * 16) % (360 * 16), 100 * 16)
        # The words.
        percent = self.work.get('percent', -1)
        elapsed = int(now - self.work.get('started', now))
        line = f'Creating… {percent}%' if percent >= 0 else (self.work.get('text') or 'Working…')
        font = QFont(self.font()); font.setPointSizeF(11.5); font.setBold(True)
        painter.setFont(font); painter.setPen(QColor('white'))
        painter.drawText(QRectF(10, centre.y() + r * 1.5, W - 20, 26), Qt.AlignmentFlag.AlignCenter, line[:80])
        small = QFont(self.font()); small.setPointSizeF(9.5); painter.setFont(small)
        painter.setPen(QColor(255, 255, 255, 170))
        painter.drawText(QRectF(10, centre.y() + r * 1.5 + 26, W - 20, 22), Qt.AlignmentFlag.AlignCenter,
                         f'{elapsed // 60}:{elapsed % 60:02d}  •  you can switch tabs; the result waits here')
        painter.end()
        self.preview.setText('')
        self.preview.setPixmap(canvas)

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
        stable = str(getattr(self, 'kept_path', None) or self.result_path)   # the Library copy stays
        if self.task == 'lineart':
            self.use_result('lineart', stable, self.image_path)
        else:
            self.use_result('image', stable, None)
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

    def show_in_folder(self):
        path = getattr(self, 'kept_path', None)
        if not path:
            return
        import subprocess, sys
        try:
            if sys.platform == 'win32':
                subprocess.Popen(['explorer', '/select,', str(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def closeEvent(self, event):
        # Do not close a dialog while a QThread is still reading model weights
        # or staging a download. Let the user cancel, then close when finished.
        if self.live_update_worker is not None and self.live_update_worker.isRunning():
            self.cancel_live_model_update()
            event.ignore()
            return
        # QDialog.closeEvent calls reject(). Title-bar Close must dismiss the
        # whole window; only Escape should first dismiss the updates drawer.
        self.drawer_motion.stop()
        self._drawer_open=False
        self.updates_panel.hide()
        self.check_updates_button.setChecked(False)
        if self.model_manager is not None:
            self.model_manager.close()
        self.work_timer.stop(); self.reveal_timer.stop(); self.progress_motion.stop()
        if self.player is not None:
            self.player.stop()
        if self.live_update_worker is not None and self.live_update_worker.isRunning():
            self.live_update_worker.cancel()
            self.updates_panel.show_feedback('Stopping model operation. Close again when finished.')
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


KIND_NAMES = {'generate': 'AI picture', 'edit': 'AI edit', 'lineart': 'AI line art'}


def picture_name(task, prompt, when=None):
    """A readable file name: 'AI line art - a cat reading - 2026-10-17 07.31.png'."""
    import re
    when = when or time.localtime()
    words = re.sub(r'[^\w\s-]', '', ' '.join((prompt or '').split()[:6]), flags=re.UNICODE).strip()
    words = words[:48].strip()
    stamp = time.strftime('%Y-%m-%d %H.%M.%S', when)
    return ' - '.join(x for x in (KIND_NAMES.get(task, 'AI picture'), words, stamp) if x) + '.png'


def keep_in_library(path, task, prompt=''):
    """Copy a created picture into Library → Images (the engine's folder is only a work folder)."""
    try:
        import shutil, tempfile
        import library
        named = Path(tempfile.mkdtemp()) / picture_name(task, prompt)
        shutil.copy2(path, named)
        item = library.Library().add('images', named, name=named.stem)
        shutil.rmtree(named.parent, ignore_errors=True)
        return item.path
    except Exception:
        return None


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
