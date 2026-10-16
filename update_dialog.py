"""Update window: check GitHub, update in place, restart (or go back)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QPlainTextEdit, QProgressBar, QFileDialog, QMessageBox, QCheckBox)

import updater


class UpdateWorker(QThread):
    progress = Signal(int, str)
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, job, **kw):
        super().__init__()
        self.job, self.kw = job, kw

    def run(self):
        try:
            getattr(self, '_' + self.job)(**self.kw)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _check(self, token, branch):
        self.done.emit(('checked', updater.latest_version(token, branch)))

    def _update(self, token=None, branch=None, zip_path=None):
        if zip_path is None:
            self.progress.emit(-1, 'Downloading the new version…')
            zip_path = Path(tempfile.gettempdir()) / 'StrokeScribe-update.zip'
            updater.download(token, zip_path, branch,
                             progress=lambda d, t: self.progress.emit(round(100 * d / t) if t else -1,
                                                                      f'Downloading… {d / 1e6:.1f} MB'))
        self.progress.emit(-1, 'Installing the new version…')
        result = updater.apply_zip(zip_path, log=self.log.emit)
        if result['requirements_changed']:
            self.progress.emit(-1, 'Installing new Python packages for this version…')
            updater.install_requirements(log=self.log.emit)
        self.done.emit(('updated', result))


class UpdateDialog(QDialog):
    def __init__(self, parent=None, latest=None):
        super().__init__(parent)
        self.setWindowTitle('Update StrokeScribe')
        self.resize(640, 470)
        self.settings = updater.load_settings()
        self.current = updater.current_version() or '?'
        self.latest = latest
        self.worker = None
        self.updated = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16); root.setSpacing(10)
        title = QLabel('Update StrokeScribe'); title.setStyleSheet('font-size: 18px; font-weight: 700;')
        root.addWidget(title)
        self.version_label = QLabel(); self.version_label.setWordWrap(True)
        root.addWidget(self.version_label)
        note = QLabel('Updating replaces only the app’s own files. Your Library, projects, settings, '
                      'AI models and installed packages stay. The previous version is kept, so you can go back.')
        note.setWordWrap(True); note.setObjectName('note')
        root.addWidget(note)

        key = QLabel('<b>GitHub key</b> (needed once, because the StrokeScribe project is private):')
        key.setWordWrap(True)
        root.addWidget(key)
        steps = QLabel('1. Click <i>Make a key on GitHub</i> and sign in.<br>'
                       '2. Name: <i>StrokeScribe updates</i>. Repository access: <i>Only select repositories</i> '
                       '→ <i>StrokeDot/StrokeScribe</i>.<br>'
                       '3. Permissions → Repository → <i>Contents: Read-only</i>. Click <i>Generate token</i>.<br>'
                       '4. Copy the key and paste it here.')
        steps.setWordWrap(True); steps.setObjectName('note')
        root.addWidget(steps)
        row = QHBoxLayout()
        self.token = QLineEdit(self.settings.get('token', ''))
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText('github_pat_…')
        row.addWidget(self.token, 1)
        make = QPushButton('Make a key on GitHub'); make.setObjectName('subtle')
        make.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(updater.TOKEN_HELP)))
        row.addWidget(make)
        root.addLayout(row)
        self.check_at_start = QCheckBox('Check for a new version when StrokeScribe starts')
        self.check_at_start.setChecked(bool(self.settings.get('check_at_start', True)))
        root.addWidget(self.check_at_start)

        buttons = QHBoxLayout()
        self.check_button = QPushButton('Check now'); self.check_button.clicked.connect(self.check)
        buttons.addWidget(self.check_button)
        self.update_button = QPushButton('Update now'); self.update_button.setObjectName('primary')
        self.update_button.clicked.connect(self.update_online)
        buttons.addWidget(self.update_button)
        self.zip_button = QPushButton('Update from a ZIP file…')
        self.zip_button.setToolTip('Use a StrokeScribe ZIP you downloaded (for example from the chat).')
        self.zip_button.clicked.connect(self.update_from_zip)
        buttons.addWidget(self.zip_button)
        self.back_button = QPushButton('Go back to the previous version'); self.back_button.setObjectName('subtle')
        self.back_button.clicked.connect(self.roll_back)
        buttons.addWidget(self.back_button)
        root.addLayout(buttons)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setFixedHeight(8)
        root.addWidget(self.progress)
        self.status = QLabel(''); self.status.setWordWrap(True); self.status.setObjectName('status')
        root.addWidget(self.status)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(110)
        root.addWidget(self.log_view, 1)
        self.restart_button = QPushButton('Restart StrokeScribe now'); self.restart_button.setObjectName('primary')
        self.restart_button.clicked.connect(self.restart)
        self.restart_button.hide()
        root.addWidget(self.restart_button)
        self.refresh()

    # ------------------------------------------------------------ state
    def save(self):
        self.settings['token'] = self.token.text().strip()
        self.settings['check_at_start'] = self.check_at_start.isChecked()
        updater.save_settings(self.settings)

    def refresh(self):
        busy = self.worker is not None and self.worker.isRunning()
        text = f'This version: <b>{self.current}</b>'
        if self.latest:
            newer = updater.is_newer(self.latest, self.current)
            text += (f'  •  New version on GitHub: <b>{self.latest}</b>' if newer
                     else f'  •  GitHub: {self.latest} — you have the newest version.')
        self.version_label.setText(text)
        has_key = bool(self.token.text().strip())
        self.check_button.setEnabled(has_key and not busy and not self.updated)
        self.update_button.setEnabled(has_key and not busy and not self.updated
                                      and bool(self.latest) and updater.is_newer(self.latest, self.current))
        self.zip_button.setEnabled(not busy and not self.updated)
        self.back_button.setVisible(updater.can_roll_back())
        self.back_button.setEnabled(not busy)

    def _start(self, worker):
        self.save()
        self.worker = worker
        worker.progress.connect(self.on_progress)
        worker.log.connect(self.log_view.appendPlainText)
        worker.done.connect(self.on_done)
        worker.failed.connect(self.on_failed)
        worker.finished.connect(self.refresh)
        worker.start()
        self.refresh()

    # ------------------------------------------------------------ actions
    def check(self):
        self.status.setText('Asking GitHub for the newest version…')
        self._start(UpdateWorker('check', token=self.token.text().strip(), branch=self.settings['branch']))

    def update_online(self):
        self._start(UpdateWorker('update', token=self.token.text().strip(), branch=self.settings['branch']))

    def update_from_zip(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Choose the StrokeScribe ZIP', '', 'ZIP (*.zip)')
            if not path:
                return
        try:
            version = updater.zip_version(path)
        except Exception as exc:
            QMessageBox.warning(self, 'Update', str(exc)); return
        if not updater.is_newer(version, self.current) and QMessageBox.question(
                self, 'Update', f'This ZIP has version {version}, not newer than {self.current}. Use it anyway?') \
                != QMessageBox.StandardButton.Yes:
            return
        self._start(UpdateWorker('update', zip_path=path))

    def roll_back(self):
        try:
            version = updater.roll_back()
        except Exception as exc:
            QMessageBox.warning(self, 'Go back', str(exc)); return
        self.status.setText(f'Back to version {version}. Restart to use it.')
        self.updated = {'version': version}
        self.restart_button.show()
        self.refresh()

    def on_progress(self, percent, text):
        if percent < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100); self.progress.setValue(percent)
        self.status.setText(text)

    def on_done(self, result):
        kind, value = result
        self.progress.setRange(0, 100); self.progress.setValue(100)
        if kind == 'checked':
            self.latest = value
            self.status.setText('A new version is ready: click Update now.' if updater.is_newer(value, self.current)
                                else 'You already have the newest version.')
        else:
            self.updated = value
            self.status.setText(f'Updated to {value["version"]}. Restart StrokeScribe to use it '
                                '(save your project first if you changed it).')
            self.restart_button.show()
        self.refresh()

    def on_failed(self, message):
        self.progress.setRange(0, 100); self.progress.setValue(0)
        self.status.setText(message)
        self.log_view.appendPlainText(message)

    def restart(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, 'restart_after_update'):
            self.accept()
            parent.restart_after_update()
            return
        updater.restart()
        self.accept()

    def closeEvent(self, event):
        self.save()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(5000)
        super().closeEvent(event)


class StartupCheck(QThread):
    """Quiet check for a newer version when the app starts."""
    found = Signal(str)

    def run(self):
        try:
            settings = updater.load_settings()
            if not settings.get('check_at_start', True) or not settings.get('token'):
                return
            latest = updater.latest_version(settings['token'], settings['branch'])
            if updater.is_newer(latest, updater.current_version() or ''):
                self.found.emit(latest)
        except Exception:
            pass
