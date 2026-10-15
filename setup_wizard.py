"""First-launch setup window: pick Fast/Balanced/Quality/Max, check this PC,
see what is installed and where, and download what is missing (after a yes).
"""
from __future__ import annotations

import preflight
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QDialog,
                               QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

STATUS_TEXT = {'ok': '✓  Installed', 'missing': '✗  Missing', 'warning': '!  Needs attention'}
STATUS_COLOR = {'ok': '#5BC98A', 'missing': '#F07A7A', 'warning': '#F2C14E'}


class CheckWorker(QThread):
    """Runs the (slow-ish) checks off the UI thread."""
    done = Signal(object, object)

    def __init__(self, tier):
        super().__init__()
        self.tier = tier

    def run(self):
        self.done.emit(preflight.system_info(), preflight.run_checks(self.tier))


class InstallWorker(QThread):
    """Installs the agreed items one after another."""
    message = Signal(str)
    progress = Signal(int, int)
    finished_all = Signal(str)

    def __init__(self, actions):
        super().__init__()
        self.actions = actions

    def run(self):
        problems = []
        for action, label, model in self.actions:
            if self.isInterruptionRequested():
                problems.append('Cancelled.')
                break
            try:
                self.progress.emit(0, 0)
                if action == 'pull_model':
                    if not preflight.ollama_version():
                        if preflight.find_ollama():
                            preflight.start_ollama(); self.sleep(3)
                        if not preflight.ollama_version():
                            raise RuntimeError('Ollama is not running, so the model cannot download yet.')
                    self.message.emit(f'Downloading {model}…')

                    def report(status, completed, total):
                        if total:
                            self.progress.emit(int(completed / 2**20), int(total / 2**20))
                            self.message.emit(f'Downloading {model}: {completed/2**30:.2f} of {total/2**30:.2f} GB')
                        elif status:
                            self.message.emit(f'{model}: {status}')
                    preflight.pull_model(model, report, self.isInterruptionRequested)
                elif action in ('winget_ffmpeg', 'winget_ollama'):
                    tool = action.split('_', 1)[1]
                    self.message.emit(f'Installing {label} with Windows Package Manager…')
                    preflight.winget_install(tool, self.message.emit)
                    if tool == 'ollama':
                        self.sleep(3)
                        if not preflight.ollama_version() and preflight.find_ollama():
                            preflight.start_ollama(); self.sleep(3)
                elif action == 'start_ollama':
                    self.message.emit('Starting Ollama…')
                    preflight.start_ollama(); self.sleep(3)
                self.message.emit(f'{label}: done')
            except Exception as exc:
                problems.append(f'{label}: {exc}')
                self.message.emit(f'{label}: {exc}')
        self.finished_all.emit(' | '.join(problems))


class SetupDialog(QDialog):
    """Small centered window shown at first launch and from the ⚙ button."""
    tier_applied = Signal(str)

    def __init__(self, parent=None, tier=None, show_at_startup=True, auto_check=True):
        super().__init__(parent)
        self.setWindowTitle('StrokeScribe setup')
        self.setModal(True)
        self.resize(760, 640)
        self.items = []
        self.info = None
        self.checker = None
        self.installer = None
        saved = preflight.load_setup()
        self.tier = tier or saved['tier'] or 'balanced'

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18); root.setSpacing(12)
        title = QLabel('Set up StrokeScribe')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        root.addWidget(title)
        intro = QLabel('Choose how much quality and speed you want. StrokeScribe checks '
                       'this computer and lists what each level needs, what is already '
                       'installed and where. Nothing downloads until you agree.')
        intro.setWordWrap(True); intro.setObjectName('note')
        root.addWidget(intro)

        levels = QHBoxLayout(); levels.setSpacing(8)
        self.tier_group = QButtonGroup(self); self.tier_group.setExclusive(True)
        self.tier_buttons = {}
        for key in preflight.TIER_ORDER:
            button = QPushButton(preflight.TIERS[key]['label'])
            button.setCheckable(True); button.setMinimumHeight(38)
            button.clicked.connect(lambda checked=False, k=key: self.choose(k))
            self.tier_group.addButton(button)
            self.tier_buttons[key] = button
            levels.addWidget(button)
        root.addLayout(levels)
        self.tier_summary = QLabel(); self.tier_summary.setWordWrap(True)
        root.addWidget(self.tier_summary)

        card = QFrame(); card.setObjectName('panel')
        card_l = QVBoxLayout(card); card_l.setContentsMargins(14, 10, 14, 10)
        self.system_label = QLabel('Checking this computer…'); self.system_label.setWordWrap(True)
        self.advice_label = QLabel(); self.advice_label.setWordWrap(True)
        self.advice_label.setStyleSheet('color: #F2C14E;')
        card_l.addWidget(self.system_label); card_l.addWidget(self.advice_label)
        root.addWidget(card)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Item', 'Status', 'Details and location'])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.progress_label = QLabel(''); self.progress_label.setWordWrap(True)
        self.progress_label.setObjectName('note')
        root.addWidget(self.progress); root.addWidget(self.progress_label)

        bottom = QHBoxLayout()
        self.show_at_startup = QCheckBox('Show this window when StrokeScribe starts')
        self.show_at_startup.setChecked(show_at_startup and saved['show_at_startup'])
        bottom.addWidget(self.show_at_startup); bottom.addStretch(1)
        self.recheck_button = QPushButton('Check again')
        self.recheck_button.clicked.connect(self.check)
        self.download_button = QPushButton('Download missing…')
        self.download_button.setObjectName('primary')
        self.download_button.clicked.connect(self.download_missing)
        self.done_button = QPushButton('Use this level')
        self.done_button.clicked.connect(self.finish)
        for button in (self.recheck_button, self.download_button, self.done_button):
            bottom.addWidget(button)
        root.addLayout(bottom)

        self.choose(self.tier, run_check=auto_check)

    # ----- Level choice and checks -----
    def choose(self, tier, run_check=True):
        self.tier = tier
        self.tier_buttons[tier].setChecked(True)
        settings = preflight.TIERS[tier]
        self.tier_summary.setText(
            f'<b>{settings["label"]}</b>: {settings["summary"]}<br>'
            f'AI model: {settings["model"]} ({settings["model_gb"]} GB)  •  '
            f'AI processing: {settings["profile"].title()}  •  '
            f'RAM: about {settings["ram_gb"]} GB recommended')
        if run_check:
            self.check()

    def check(self):
        if self.checker and self.checker.isRunning():
            return
        self.progress_label.setText('Checking this computer…')
        self.progress.setRange(0, 0)
        self.download_button.setEnabled(False)
        self.checker = CheckWorker(self.tier)
        self.checker.done.connect(self.show_results)
        self.checker.start()

    def show_results(self, info, items):
        self.info, self.items = info, items
        ram = (f'{info.ram_total_gb:.0f} GB RAM ({info.ram_free_gb:.0f} GB free)'
               if info.ram_total_gb else 'RAM unknown')
        disk = (f'{info.disk_free_gb:.0f} GB free on {info.disk_path}'
                if info.disk_free_gb is not None else 'free disk space unknown')
        gpu = (', '.join(f'{name} ({memory} GB)' for name, memory in info.gpus)
               if info.gpus else 'no NVIDIA GPU detected')
        self.system_label.setText(f'<b>This computer:</b> {info.os_name}  •  {ram}  •  {disk}  •  GPU: {gpu}')
        self.advice_label.setText('\n'.join(preflight.advice(info, self.tier)))
        self.advice_label.setVisible(bool(self.advice_label.text()))
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            name = QTableWidgetItem(item.name + ('' if item.required else '  (optional)'))
            name.setToolTip(item.purpose)
            status = QTableWidgetItem(STATUS_TEXT[item.status])
            status.setForeground(QColor(STATUS_COLOR[item.status]))
            details = ' — '.join(part for part in (item.purpose, item.detail) if part)
            if item.location:
                details += f'\nLocation: {item.location}'
            info_item = QTableWidgetItem(details)
            info_item.setToolTip(details)
            for column, cell in enumerate((name, status, info_item)):
                self.table.setItem(row, column, cell)
        self.table.resizeRowsToContents()
        todo = self.pending()
        self.progress.setRange(0, 100); self.progress.setValue(100 if not todo else 0)
        size = sum(item.size_gb for item in todo)
        self.download_button.setEnabled(bool(todo))
        self.download_button.setText(f'Download missing ({size:.1f} GB)…' if todo else 'Everything installed')
        self.progress_label.setText('Ready: everything for this level is installed.' if not todo
                                    else f'{len(todo)} item(s) can be installed for this level.')

    def pending(self):
        return [item for item in self.items if item.action]

    # ----- Installing -----
    def download_missing(self):
        todo = self.pending()
        if not todo:
            return
        lines = '\n'.join(f'•  {item.name}' + (f'  ({item.size_gb:.1f} GB)' if item.size_gb else '')
                          for item in todo)
        answer = QMessageBox.question(
            self, 'Download and install',
            'StrokeScribe will download and install:\n\n' + lines +
            '\n\nFFmpeg and Ollama install through Windows Package Manager (winget); '
            'AI models download through Ollama and are stored in:\n' +
            str(preflight.models_dir()) + '\n\nContinue?')
        if answer != QMessageBox.StandardButton.Yes:
            return
        # Ollama must exist before its model can download.
        order = {'winget_ffmpeg': 0, 'winget_ollama': 1, 'start_ollama': 2, 'pull_model': 3}
        actions = [(item.action, item.name, preflight.TIERS[self.tier]['model'])
                   for item in sorted(todo, key=lambda i: order.get(i.action, 9))]
        self.installer = InstallWorker(actions)
        self.installer.message.connect(self.progress_label.setText)
        self.installer.progress.connect(self.set_progress)
        self.installer.finished_all.connect(self.install_finished)
        for button in (self.download_button, self.recheck_button, self.done_button):
            button.setEnabled(False)
        for button in self.tier_buttons.values():
            button.setEnabled(False)
        self.installer.start()

    def set_progress(self, value, maximum):
        self.progress.setRange(0, maximum); self.progress.setValue(value)

    def install_finished(self, problems):
        for button in (self.recheck_button, self.done_button):
            button.setEnabled(True)
        for button in self.tier_buttons.values():
            button.setEnabled(True)
        if problems:
            QMessageBox.warning(self, 'Setup', 'Some items could not be installed:\n\n' + problems)
        self.check()

    # ----- Finish -----
    def finish(self):
        preflight.save_setup(self.tier, self.show_at_startup.isChecked())
        self.tier_applied.emit(self.tier)
        self.accept()

    def closeEvent(self, event):
        if self.installer and self.installer.isRunning():
            if QMessageBox.question(self, 'Setup', 'A download is running. Stop it and close?') \
                    != QMessageBox.StandardButton.Yes:
                event.ignore(); return
            self.installer.requestInterruption(); self.installer.wait(5000)
        if self.checker and self.checker.isRunning():
            self.checker.wait(20000)
        super().closeEvent(event)
