"""Small advisory panel; no modal warning and no changes to other applications."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDialog,QFormLayout,QDoubleSpinBox,QCheckBox,QDialogButtonBox
from ai_resources import limits,describe

class ResourcePanel(QFrame):
    proceed_requested=Signal()
    cancel_requested=Signal()
    limits_changed=Signal(object)
    def __init__(self,settings,parent=None):
        super().__init__(parent);self.settings=limits(settings)
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        row=QHBoxLayout()
        self.readout=QLabel('Available memory is checked before generation.');self.readout.setWordWrap(True)
        row.addWidget(self.readout,1)
        self.settings_button=QPushButton('Memory limits…');self.settings_button.clicked.connect(self.edit_limits)
        row.addWidget(self.settings_button);root.addLayout(row)
        self.warning=QFrame();box=QVBoxLayout(self.warning)
        self.message=QLabel();self.message.setWordWrap(True);box.addWidget(self.message)
        actions=QHBoxLayout()
        self.proceed=QPushButton('Generate anyway');self.cancel=QPushButton('Cancel generation')
        self.proceed.clicked.connect(self.proceed_requested.emit);self.cancel.clicked.connect(self.cancel_requested.emit)
        actions.addWidget(self.proceed);actions.addWidget(self.cancel);actions.addStretch()
        box.addLayout(actions);root.addWidget(self.warning);self.warning.hide()
    def show_metrics(self,metrics):
        self.readout.setText(describe(metrics))
    def warn(self,message):
        self.message.setText(message);self.warning.show()
    def clear_warning(self):
        self.warning.hide()
    def edit_limits(self):
        dialog=QDialog(self);dialog.setWindowTitle('AI resource warning limits')
        form=QFormLayout(dialog)
        enabled=QCheckBox('Warn when available memory is low');enabled.setChecked(self.settings['enabled']);form.addRow(enabled)
        controls={}
        for key,title,ceiling in (('ram_gb','Available RAM warning below (GB)',1024),('vram_gb','Available GPU memory warning below (GB)',256),('stall_seconds','No-progress notice after (seconds)',3600)):
            control=QDoubleSpinBox();control.setDecimals(1);control.setRange(5 if key=='stall_seconds' else 0,ceiling)
            control.setValue(self.settings[key]);controls[key]=control;form.addRow(title,control)
        note=QLabel('Advisory thresholds only. They never lower image quality or close applications. Zero disables that memory threshold.')
        note.setWordWrap(True);form.addRow(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.settings=limits(dict(enabled=enabled.isChecked(),**{key:control.value() for key,control in controls.items()}))
            self.limits_changed.emit(self.settings)
