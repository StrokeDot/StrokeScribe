"""Update window: check GitHub, update in place, restart (or go back)."""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
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
        self._cancel = threading.Event()
        self.phase = 'idle'

    def cancelled(self):
        return self._cancel.is_set()

    def request_cancel(self):
        """Only preparation/download may be cancelled; commits must finish."""
        if self.phase == 'installing':
            return False
        self._cancel.set()
        return True

    def _begin_install(self):
        self.phase = 'installing'
        self.progress.emit(-1, 'Installing files safely… Please wait.')

    def run(self):
        try:
            getattr(self, '_' + self.job)(**self.kw)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _check(self, token, branch):
        self.phase = 'checking'
        version = updater.latest_version(token, branch)
        if self.cancelled():
            raise updater.CancelledUpdate('Update check cancelled.')
        self.done.emit(('checked', version))

    def _update(self, token=None, branch=None, zip_path=None):
        self.phase = 'downloading'
        # Each worker has its own temporary directory. Two updater windows
        # cannot corrupt one another's partial ZIP or remove a supplied file.
        with tempfile.TemporaryDirectory(prefix='StrokeScribe-update-') as folder:
            if zip_path is None:
                self.progress.emit(-1, 'Downloading the new version…')
                zip_path = Path(folder) / 'download.zip'
                updater.download(token, zip_path, branch,
                    progress=lambda d, t: self.progress.emit(
                        round(100 * d / t) if t else -1,
                        f'Downloading… {d / 1e6:.1f} MB'),
                    cancelled=self.cancelled)
            if self.cancelled():
                raise updater.CancelledUpdate('Update cancelled before installation.')
            self.phase = 'preparing'
            self.progress.emit(-1, 'Verifying and preparing files…')
            result = updater.apply_zip(zip_path, log=self.log.emit,
                                       cancelled=self.cancelled,
                                       on_commit=self._begin_install)
            if result['requirements_changed']:
                raise updater.UpdateError(
                    'This update needs new Python packages. Use the verified full Windows installer; '
                    'the running runtime will not be modified.')
        self.phase = 'finished'
        self.done.emit(('updated', result))


class KeyDialog(QDialog):
    """Pop-up to add, change or remove the GitHub key (only needed for a private project)."""

    def __init__(self, parent=None, token=''):
        super().__init__(parent)
        self.setWindowTitle('GitHub key')
        self.resize(520, 300)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18); root.setSpacing(10)
        title = QLabel('GitHub key'); title.setObjectName('dialogTitle')
        root.addWidget(title)
        note = QLabel('StrokeScribe is public, so updates work <b>without a key</b>. A key is only '
                      'needed if you make the project private again.')
        note.setWordWrap(True); note.setObjectName('note')
        root.addWidget(note)
        steps = QLabel('1. Click <i>Make a key on GitHub</i> and sign in.<br>'
                       '2. Repository access: <i>Only select repositories</i> → <i>StrokeDot/StrokeScribe</i>.<br>'
                       '3. Permissions → <i>Contents: Read-only</i>, then <i>Generate token</i>.<br>'
                       '4. Copy the key and paste it below.')
        steps.setWordWrap(True); steps.setObjectName('note')
        root.addWidget(steps)
        row = QHBoxLayout(); row.setSpacing(6)
        self.token = QLineEdit(token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText('Paste the key here (github_pat_…)')
        row.addWidget(self.token, 1)
        self.show_key = QPushButton('Show'); self.show_key.setObjectName('subtle'); self.show_key.setCheckable(True)
        self.show_key.toggled.connect(lambda on: (self.token.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password),
            self.show_key.setText('Hide' if on else 'Show')))
        row.addWidget(self.show_key)
        root.addLayout(row)
        self.problem = QLabel(''); self.problem.setObjectName('bad'); self.problem.setWordWrap(True)
        root.addWidget(self.problem)
        root.addStretch(1)
        buttons = QHBoxLayout(); buttons.setSpacing(8)
        make = QPushButton('Make a key on GitHub'); make.setObjectName('subtle')
        make.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(updater.TOKEN_HELP)))
        buttons.addWidget(make)
        self.remove = QPushButton('Remove key'); self.remove.setObjectName('subtle')
        self.remove.clicked.connect(self.remove_key)
        self.remove.setVisible(bool(token))
        buttons.addWidget(self.remove)
        buttons.addStretch(1)
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.save_button = QPushButton('Save'); self.save_button.setObjectName('primary')
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)
        self.token.textChanged.connect(lambda text: self.problem.setText(''))

    def value(self):
        return self.token.text().strip()

    def save(self):
        problem = updater.key_problem(self.value()) if self.value() else None
        if problem:
            self.problem.setText('✗  ' + problem); return
        self.accept()

    def remove_key(self):
        self.token.clear(); self.accept()


class UpdateDialog(QDialog):
    """Version, a ✓ / ✗ line for the connection to GitHub, and the update buttons.

    The key is never shown here; it is added or changed in its own pop-up (Key…)."""

    def __init__(self, parent=None, latest=None, auto_check=True):
        super().__init__(parent)
        self.setWindowTitle('Update StrokeScribe')
        self.resize(560, 360)
        self.settings = updater.load_settings()
        self.current = updater.current_version() or '?'
        self.latest = latest
        self.worker = None
        self._close_when_idle = False
        self.updated = None
        self.connected = None              # None: not checked yet, True / False
        self.connection_text = ''
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18); root.setSpacing(12)
        title = QLabel('Update StrokeScribe'); title.setObjectName('dialogTitle')
        root.addWidget(title)
        self.version_label = QLabel(); self.version_label.setWordWrap(True)
        root.addWidget(self.version_label)
        # Connection to GitHub: ✓ or ✗, never the key itself.
        conn = QHBoxLayout(); conn.setSpacing(8)
        self.connection = QLabel(); self.connection.setWordWrap(True)
        conn.addWidget(self.connection, 1)
        self.key_button = QPushButton('Key…'); self.key_button.setObjectName('subtle')
        self.key_button.setToolTip('Add or change the GitHub key (only needed for a private project).')
        self.key_button.clicked.connect(self.edit_key)
        conn.addWidget(self.key_button)
        root.addLayout(conn)
        note = QLabel('Updating replaces only the app’s own files. Your Library, projects, settings and '
                      'AI models stay, and the previous version is kept so you can go back.')
        note.setWordWrap(True); note.setObjectName('note')
        root.addWidget(note)
        self.check_at_start = QCheckBox('Check for a new version when StrokeScribe starts')
        self.check_at_start.setChecked(bool(self.settings.get('check_at_start', True)))
        root.addWidget(self.check_at_start)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setFixedHeight(6)
        self.progress.hide()
        root.addWidget(self.progress)
        self.status = QLabel(''); self.status.setWordWrap(True); self.status.setObjectName('status')
        root.addWidget(self.status)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(110)
        self.log_view.hide()
        root.addWidget(self.log_view, 1)
        root.addStretch(1)
        buttons = QHBoxLayout(); buttons.setSpacing(8)
        self.more_button = QPushButton('More ▾'); self.more_button.setObjectName('subtle')
        from PySide6.QtWidgets import QMenu
        more = QMenu(self)
        self.zip_action = more.addAction('Update from a ZIP file…', self.update_from_zip)
        self.back_action = more.addAction('Go back to the previous version', self.roll_back)
        self.details_action = more.addAction('Show details', lambda: self.log_view.setVisible(not self.log_view.isVisible()))
        self.more_button.setMenu(more)
        buttons.addWidget(self.more_button)
        buttons.addStretch(1)
        self.check_button = QPushButton('Check now'); self.check_button.clicked.connect(self.check)
        buttons.addWidget(self.check_button)
        self.update_button = QPushButton('Update now'); self.update_button.setObjectName('primary')
        self.update_button.clicked.connect(self.update_online)
        buttons.addWidget(self.update_button)
        self.cancel_button = QPushButton('Cancel update')
        self.cancel_button.setObjectName('subtle')
        self.cancel_button.clicked.connect(self.cancel_running)
        self.cancel_button.hide()
        buttons.addWidget(self.cancel_button)
        self.restart_button = QPushButton('Restart StrokeScribe'); self.restart_button.setObjectName('primary')
        self.restart_button.clicked.connect(self.restart)
        self.restart_button.hide()
        buttons.addWidget(self.restart_button)
        root.addLayout(buttons)
        self.refresh()
        if auto_check:
            self.check()

    # ------------------------------------------------------------ state
    @property
    def token(self):
        return (self.settings.get('token') or '').strip()

    def save(self):
        self.settings['check_at_start'] = self.check_at_start.isChecked()
        updater.save_settings(self.settings)

    def show_connection(self):
        if self.connected is None:
            text, colour = '●  Not checked yet', 'muted'
        elif self.connected:
            text, colour = '✓  Connected to GitHub' + (' (with your key)' if self.token else ''), 'good'
        else:
            text, colour = '✗  Not connected' + (f' — {self.connection_text}' if self.connection_text else ''), 'bad'
        self.connection.setText(text)
        self.connection.setObjectName(colour)
        self.connection.style().unpolish(self.connection); self.connection.style().polish(self.connection)

    def refresh(self):
        busy = self.worker is not None and self.worker.isRunning()
        text = f'This version: <b>{self.current}</b>'
        if self.latest:
            newer = updater.is_newer(self.latest, self.current)
            text += (f'<br>New version ready: <b>{self.latest}</b>' if newer
                     else '<br>You have the newest version.')
        self.version_label.setText(text)
        self.show_connection()
        self.key_button.setText('Change key…' if self.token else 'Key…')
        self.check_button.setEnabled(not busy and not self.updated)
        self.update_button.setEnabled(not busy and not self.updated
                                      and bool(self.latest) and updater.is_newer(self.latest, self.current))
        self.update_button.setVisible(not self.updated)
        self.zip_action.setEnabled(not busy and not self.updated)
        self.back_action.setVisible(updater.can_roll_back())
        self.back_action.setEnabled(not busy)
        self.key_button.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy and
             getattr(self.worker, 'phase', None) != 'installing' and
             not (getattr(self.worker, 'cancelled', lambda: False)() if busy else False))
        self.restart_button.setEnabled(not busy)

    def _worker_finished(self):
        self.refresh()
        if self._close_when_idle:
            self._close_when_idle = False
            QTimer.singleShot(0, self.close)

    def cancel_running(self):
        if self.worker is None or not self.worker.isRunning():
            return False
        if not self.worker.request_cancel():
            self.status.setText('Installing the update safely. Wait for it to finish before closing.')
            self.refresh()
            return False
        self.status.setText('Cancellation requested. Waiting for the current operation to stop safely…')
        self.refresh()
        return True

    def _start(self, worker):
        if self.worker is not None and self.worker.isRunning():
            return
        self.save()
        self.worker = worker
        worker.progress.connect(self.on_progress)
        worker.log.connect(self.log_view.appendPlainText)
        worker.done.connect(self.on_done)
        worker.failed.connect(self.on_failed)
        worker.finished.connect(self._worker_finished)
        worker.start()
        self.refresh()

    # ------------------------------------------------------------ actions
    def edit_key(self):
        dialog = KeyDialog(self, self.token)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings['token'] = dialog.value()
        self.save()
        self.connected = None
        self.check()

    def check(self):
        self.status.setText('Asking GitHub for the newest version…')
        self._start(UpdateWorker('check', token=self.token, branch=self.settings['branch']))

    def update_online(self):
        self._start(UpdateWorker('update', token=self.token, branch=self.settings['branch']))

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
        if self.worker is not None and self.worker.isRunning():
            return
        target = updater.rollback_target_version()
        if QMessageBox.question(self, 'Restore previous version',
                f'Go back to StrokeScribe {target}? '
                'You will need to restart the application afterward.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            version = updater.roll_back()
        except Exception as exc:
            QMessageBox.warning(self, 'Go back', str(exc)); return
        self.status.setText(f'Previous version {version} restored. Restart StrokeScribe to use it.')
        self.updated = {'version': version}
        self.restart_button.show()
        self.refresh()

    def on_progress(self, percent, text):
        self.progress.show()
        if percent < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100); self.progress.setValue(percent)
        self.status.setText(text)

    def on_done(self, result):
        kind, value = result
        self.progress.setRange(0, 100); self.progress.setValue(100); self.progress.hide()
        if kind == 'checked':
            self.latest = value
            self.connected, self.connection_text = True, ''
            self.status.setText('Click Update now to install it.' if updater.is_newer(value, self.current) else '')
        else:
            self.updated = value
            self.status.setText(f'✓  Updated to {value["version"]}. Restart StrokeScribe to use it '
                                '(save your project first if you changed it).')
            self.restart_button.show()
        self.refresh()

    def on_failed(self, message):
        self.progress.setRange(0, 100); self.progress.setValue(0); self.progress.hide()
        first = message.splitlines()[0] if message else 'Something went wrong.'
        if self.worker is not None and self.worker.job == 'check':
            self.connected, self.connection_text = False, first
            self.status.setText('')
        else:
            self.status.setText(first if 'cancel' in first.lower() else '✗  ' + first)
        self.log_view.appendPlainText(message)
        self.refresh()

    def restart(self):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText('Wait for the update to finish before restarting.')
            return False
        parent = self.parent()
        if parent is not None and hasattr(parent, 'restart_after_update'):
            # Do not close this dialog before the parent has confirmed Save /
            # Discard / Cancel and successfully launched the new process.
            ok = bool(parent.restart_after_update())
            if not ok:
                self.status.setText('Restart cancelled. StrokeScribe is still open.')
            return ok
        try:
            updater.restart()
        except Exception as exc:
            QMessageBox.warning(self, 'Restart', 'Could not start StrokeScribe: ' + str(exc))
            return False
        self.accept()
        return True

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            if self.worker.request_cancel():
                self._close_when_idle = True
                self.status.setText('Cancelling safely… This window will close when finished.')
            else:
                self.status.setText('Installing application files. Please wait until it finishes.')
            event.ignore()
            self.refresh()
            return
        self.save()
        super().closeEvent(event)


class StartupCheck(QThread):
    """Quiet check for a newer version when the app starts."""
    found = Signal(str)

    def run(self):
        try:
            settings = updater.load_settings()
            if not settings.get('check_at_start', True):
                return
            latest = updater.latest_version(settings.get('token') or None, settings['branch'])
            if updater.is_newer(latest, updater.current_version() or ''):
                self.found.emit(latest)
        except Exception:
            pass
