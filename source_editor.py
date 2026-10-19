"""Small staged source editors. Cancel never touches the project."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QFileDialog,QDialogButtonBox,QFormLayout,QDoubleSpinBox,QCheckBox,QMessageBox)

class SourceEditor(QDialog):
    def __init__(self,window,stage):
        super().__init__(window)
        self.window=window;self.stage=stage;self.path=None;self.controls={};self.initial_settings={}
        self.setWindowTitle('Edit Drawing Source' if stage=='draw' else 'Edit Painting Source')
        self.resize(620,600)
        layout=QVBoxLayout(self)
        self.name=QLabel();self.name.setWordWrap(True);layout.addWidget(self.name)
        self.preview=QLabel();self.preview.setMinimumSize(360,220)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('background:#26303b;border:1px solid #4b5868;border-radius:6px')
        layout.addWidget(self.preview,1)
        choose=QPushButton('Choose SVG or line-art image…' if stage=='draw' else
                           'Change original image…' if window.is_image_artwork() else 'Change matching colors…')
        choose.clicked.connect(self.choose);layout.addWidget(choose)
        self.reconstruct=QCheckBox('Reconstruct drawing paths from this source')
        self.reconstruct.setChecked(False)
        self.reconstruct.setVisible(stage=='draw')
        self.reconstruct.setToolTip('Keeps the original colors and your timing and hand settings.')
        layout.addWidget(self.reconstruct)
        form=QFormLayout();layout.addLayout(form)
        names=(('duration','Draw time (s)'),('thickness','Line width')) if stage=='draw' else (
            ('image_duration' if window.is_image_artwork() else 'color_fade','Paint time (s)'),
            ('brush_width','Brush width'),('stroke_spacing','Stroke spacing / overlap'))
        for key,label in names:
            source=getattr(window,key);control=QDoubleSpinBox()
            control.setDecimals(source.decimals());control.setRange(source.minimum(),source.maximum())
            control.setSingleStep(source.singleStep());control.setValue(source.value())
            form.addRow(label,control);self.controls[key]=control;self.initial_settings[key]=control.value()
        note=QLabel('Drawing paths and original colors are separate. A replacement is fitted proportionally to the existing artwork bounds. '
                    'If its composition differs, choose a matching drawing source too. Hand calibration and placement are kept.')
        note.setWordWrap(True);layout.addWidget(note)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Apply changes')
        self.buttons.accepted.connect(self.apply);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.show_source()

    def show_source(self):
        window=self.window
        try:
            if self.path:
                self.name.setText(Path(self.path).name)
                if Path(self.path).suffix.lower()=='.svg':
                    from engine import import_svg,render
                    image=render(import_svg(self.path),1.,560,300)
                else:
                    from image_reconstruct import load_raster
                    from adaptive_hand import qimage
                    image=qimage(load_raster(self.path))
            elif self.stage=='draw':
                from engine import render
                image=render(window.drawing,1.,560,300)
                self.name.setText(getattr(window.drawing,'drawing_source_name',None) or
                    (Path(window.image_guide).name if window.image_guide else window.project_title)+' • current drawing')
            else:
                image=window.image_result.image if window.is_image_artwork() and window.image_result else window.final_image
                self.name.setText(window.color_note.text())
            if image is None or image.isNull():
                self.preview.clear();self.preview.setText('No painting source. Choose a matching colored image.')
            else:
                self.preview.setPixmap(QPixmap.fromImage(image).scaled(560,300,
                        Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            return True
        except Exception as exc:
            QMessageBox.warning(self,'Cannot preview source',str(exc));return False

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,self.windowTitle(),'',
                'Artwork (*.svg *.png *.jpg *.jpeg *.webp *.bmp)' if self.stage=='draw' else 'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not path:return
        old=self.path;self.path=path
        if not self.show_source():
            self.path=old;self.show_source()
        elif self.stage=='draw':self.reconstruct.setChecked(True)

    def apply(self):
        settings={key:control.value() for key,control in self.controls.items() if control.value()!=self.initial_settings[key]}
        w=self.window
        if self.stage=='draw' and (self.path or self.reconstruct.isChecked()):
            ok=w.replace_drawing_source(self.path,reconstruct=not bool(self.path),settings=settings)
        elif self.stage=='paint' and self.path:
            ok=w.replace_paint_source(self.path,settings=settings)
        else:ok=w._commit_source({},settings)
        if ok:self.accept()
