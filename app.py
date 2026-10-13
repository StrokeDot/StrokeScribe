import sys, time
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,QDoubleSpinBox,QSpinBox,QComboBox,QFileDialog,QListWidget,QSlider,QCheckBox,QPlainTextEdit,QMessageBox,QSplitter,QProgressBar)
from engine import import_svg, render, export_frames, encode_mov
from lettering import make_text
from color_reveal import load_color_image, render_color_timeline, timeline_duration

# Shared application branding asset (path independent of the working directory).
BRAND_ICON = Path(__file__).resolve().parent / 'assets' / 'strokescribe_icon.png'

class Canvas(QWidget):
    def __init__(self):
        super().__init__(); self.frame=None; self.setMinimumSize(550,330)
    def paintEvent(self,event):
        p=QPainter(self); p.fillRect(self.rect(),QColor('#141d28'))
        if self.frame:
            size=self.frame.size(); size.scale(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            x=(self.width()-size.width())//2; y=(self.height()-size.height())//2
            p.save(); p.setClipRect(x,y,size.width(),size.height())
            for a in range(x,x+size.width(),20):
                for b in range(y,y+size.height(),20):
                    p.fillRect(a,b,20,20,QColor('#e8edf0' if ((a-x)//20+(b-y)//20)%2==0 else '#d4dce2'))
            p.drawImage(x,y,self.frame.scaled(size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)); p.restore()
        p.end()

class Exporter(QThread):
    progress=Signal(int,int); done=Signal(str); failed=Signal(str)
    def __init__(self,drawing,folder,options,mov):
        super().__init__(); self.drawing=drawing; self.folder=folder; self.options=options; self.mov=mov
    def run(self):
        try:
            def tick(i,n):
                self.progress.emit(i,n)
                return not self.isInterruptionRequested()
            export_frames(self.drawing,self.folder,callback=tick,**self.options)
            if self.mov:
                self.progress.emit(0,0)
                encode_mov(self.folder,self.options['fps'])
            self.done.emit(str(self.folder))
        except Exception as e: self.failed.emit(str(e))

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        # Explicit font registration also supports Qt's offscreen Windows backend.
        import os
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
        if font.exists(): QFontDatabase.addApplicationFont(str(font))
        QApplication.instance().setFont(QFont('Segoe UI',10))
        self.setWindowTitle('StrokeScribe • local animation prototype'); self.resize(1220,800)
        if BRAND_ICON.is_file():
            icon = QIcon(str(BRAND_ICON))
            self.setWindowIcon(icon)
            QApplication.instance().setWindowIcon(icon)
        self.drawing=None; self.hand=None; self.final_image=None; self.worker=None; self.playing=False; self.position=0
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(33)
        root=QWidget(); self.setCentralWidget(root); outer=QVBoxLayout(root)
        header = QHBoxLayout(); outer.addLayout(header)
        if BRAND_ICON.is_file():
            brand = QLabel()
            brand.setFixedSize(64,64)
            brand.setPixmap(QPixmap(str(BRAND_ICON)).scaled(60,60,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            header.addWidget(brand)
        titles = QVBoxLayout(); header.addLayout(titles, 1)
        title = QLabel('StrokeScribe'); title.setStyleSheet('font-size:24px;font-weight:700;color:#2767ed;')
        subtitle = QLabel('SVG → transparent animation'); subtitle.setStyleSheet('font-size:12px;color:#72839a;')
        titles.addWidget(title); titles.addWidget(subtitle)
        header.setContentsMargins(8,4,8,8)
        split=QSplitter(); outer.addWidget(split,1); left=QWidget(); panel=QVBoxLayout(left); split.addWidget(left)
        b=QPushButton('Import SVG…'); b.clicked.connect(self.load); panel.addWidget(b)
        panel.addWidget(QLabel('Single-line lettering (A–Z, digits, punctuation)'))
        self.text=QPlainTextEdit('Hello world!'); self.text.setMaximumHeight(70); panel.addWidget(self.text)
        b=QPushButton('Create lettering'); b.clicked.connect(self.letter); panel.addWidget(b)
        panel.addWidget(QLabel('Stroke order • select and move'))
        self.order=QListWidget(); panel.addWidget(self.order,1)
        row=QHBoxLayout(); panel.addLayout(row)
        for label,direction in [('Move up',-1),('Move down',1)]:
            b=QPushButton(label); b.clicked.connect(lambda checked=False,d=direction:self.move(d)); row.addWidget(b)
        panel.addWidget(QLabel('Final artwork reveal (optional)'))
        b=QPushButton('Load original colored PNG…'); b.clicked.connect(self.load_color); panel.addWidget(b)
        self.use_color=QCheckBox('Reveal PNG after drawing')
        self.use_color.setEnabled(False)
        panel.addWidget(self.use_color)
        color_form=QFormLayout(); panel.addLayout(color_form)
        self.reveal_mode=QComboBox()
        self.reveal_mode.addItems(['Fade','Brush painting','Stroke-guided painting'])
        color_form.addRow('Reveal mode',self.reveal_mode)
        self.color_fade=self.number(0,20,.4,.1)
        color_form.addRow('Reveal duration (seconds)',self.color_fade)
        self.brush_width=self.number(.02,.5,.14,.02)
        color_form.addRow('Brush width / artwork',self.brush_width)
        self.show_paint_hand=QCheckBox('Show hand during painting')
        self.show_paint_hand.setChecked(True)
        color_form.addRow(self.show_paint_hand)
        self.color_hold=self.number(0,30,.6,.1); color_form.addRow('Final image hold (seconds)',self.color_hold)
        self.color_note=QLabel('No final PNG loaded'); self.color_note.setWordWrap(True); panel.addWidget(self.color_note)
        self.note=QLabel(); self.note.setWordWrap(True); self.note.setMaximumWidth(340); panel.addWidget(self.note)
        right=QWidget(); layout=QVBoxLayout(right); split.addWidget(right); self.canvas=Canvas(); layout.addWidget(self.canvas,1)
        self.slider=QSlider(Qt.Orientation.Horizontal); self.slider.setRange(0,1000); self.slider.valueChanged.connect(self.scrub); layout.addWidget(self.slider)
        playback=QHBoxLayout(); layout.addLayout(playback)
        self.play=QPushButton('Play / pause'); self.play.clicked.connect(self.toggle); playback.addWidget(self.play)
        b=QPushButton('Restart'); b.clicked.connect(self.restart); playback.addWidget(b)
        self.clock=QLabel(); playback.addWidget(self.clock)
        controls=QHBoxLayout(); layout.addLayout(controls); form=QFormLayout(); controls.addLayout(form)
        self.duration=self.number(.2,120,4,.1); form.addRow('Base duration (seconds)',self.duration)
        self.speed=self.number(.1,5,1,.1); form.addRow('Speed multiplier',self.speed)
        self.thickness=self.number(.1,10,1,.1); form.addRow('Line thickness ×',self.thickness)
        self.res=QComboBox(); self.res.addItems(['1920 × 1080','2048 × 1080','2560 × 1440']); form.addRow('Export resolution',self.res)
        self.fps=QSpinBox(); self.fps.setRange(1,60); self.fps.setValue(30); form.addRow('Frames per second',self.fps)
        handform=QFormLayout(); controls.addLayout(handform)
        b=QPushButton('Load transparent hand PNG…'); b.clicked.connect(self.loadhand); handform.addRow(b)
        self.showhand=QCheckBox('Show hand'); self.showhand.setChecked(True); handform.addRow(self.showhand)
        self.handsize=self.number(.02,.8,.18,.01); handform.addRow('Hand width / canvas',self.handsize)
        self.ax=self.number(0,1,.1,.01); handform.addRow('Pen tip X / PNG width',self.ax)
        self.ay=self.number(0,1,.1,.01); handform.addRow('Pen tip Y / PNG height',self.ay)
        self.mov=QCheckBox('Also make ProRes 4444 MOV (FFmpeg)'); layout.addWidget(self.mov)
        row=QHBoxLayout(); layout.addLayout(row); self.export=QPushButton('Export transparent PNG sequence…'); self.export.clicked.connect(self.save); row.addWidget(self.export)
        self.cancel=QPushButton('Cancel export'); self.cancel.setEnabled(False); self.cancel.clicked.connect(self.cancel_export); row.addWidget(self.cancel)
        self.progress=QProgressBar(); layout.addWidget(self.progress)
        self.status=QLabel('Local CPU rendering • checkerboard is preview only'); layout.addWidget(self.status)
        split.setSizes([300,900])
        for w in [self.duration,self.speed,self.thickness,self.handsize,self.ax,self.ay]: w.valueChanged.connect(self.refresh)
        self.showhand.toggled.connect(self.refresh); self.res.currentIndexChanged.connect(self.refresh)
        self.use_color.toggled.connect(self.refresh)
        self.color_fade.valueChanged.connect(self.refresh)
        self.color_hold.valueChanged.connect(self.refresh)
        self.reveal_mode.currentIndexChanged.connect(self.refresh)
        self.brush_width.valueChanged.connect(self.refresh)
        self.show_paint_hand.toggled.connect(self.refresh)
        self.set_drawing(import_svg(Path(__file__).parent/'samples'/'drawing.svg'))
    def number(self,minimum,maximum,value,step):
        w=QDoubleSpinBox(); w.setRange(minimum,maximum); w.setValue(value); w.setSingleStep(step); return w
    def set_drawing(self,drawing):
        self.playing=False; self.drawing=drawing; self.order.clear(); self.order.addItems([s.name for s in drawing.strokes]); self.note.setText('\n'.join(drawing.warnings) or 'Ready. Press Play to draw from the beginning.'); self.position=1; self.slider.setValue(1000); self.refresh()
    def load(self):
        name,_=QFileDialog.getOpenFileName(self,'Import SVG','','SVG (*.svg)')
        if name:
            try: self.set_drawing(import_svg(name))
            except Exception as e: QMessageBox.warning(self,'Cannot import',str(e))
    def letter(self):
        try: self.set_drawing(make_text(self.text.toPlainText()))
        except Exception as e: QMessageBox.warning(self,'Lettering',str(e))
    def move(self,direction):
        i=self.order.currentRow(); j=i+direction
        if i<0 or not 0<=j<len(self.drawing.strokes): return
        self.drawing.strokes[i],self.drawing.strokes[j]=self.drawing.strokes[j],self.drawing.strokes[i]
        item=self.order.takeItem(i); self.order.insertItem(j,item); self.order.setCurrentRow(j); self.refresh()
    def loadhand(self):
        name,_=QFileDialog.getOpenFileName(self,'Hand overlay','','PNG (*.png)')
        if name:
            image=QImage(name)
            if image.isNull(): QMessageBox.warning(self,'Hand','Could not read PNG.'); return
            self.hand=image; self.refresh()
    def load_color(self):
        name,_=QFileDialog.getOpenFileName(self,'Load final colored artwork','','PNG (*.png)')
        if not name: return
        try:
            self.final_image=load_color_image(name)
        except Exception as e:
            QMessageBox.warning(self,'Final artwork',str(e)); return
        self.color_note.setText(Path(name).name+' • use a transparent PNG that matches the SVG drawing')
        self.use_color.setEnabled(True)
        self.use_color.setChecked(True)
        self.refresh()
    def effective_duration(self): return self.duration.value()/self.speed.value()
    def timeline_length(self):
        color = self.final_image if self.use_color.isChecked() else None
        return timeline_duration(self.effective_duration(),color,self.color_fade.value(),self.color_hold.value())
    def options(self):
        width,height=[int(x.strip()) for x in self.res.currentText().split('×')]
        return dict(duration=self.effective_duration(),fps=self.fps.value(),width=width,height=height,
                    thickness=self.thickness.value(),hand=self.hand if self.showhand.isChecked() else None,
                    hand_scale=self.handsize.value(),anchor=(self.ax.value(),self.ay.value()),
                    final_image=self.final_image if self.use_color.isChecked() else None,
                    fade_duration=self.color_fade.value(),hold_duration=self.color_hold.value(),
                    reveal_mode=['fade','brush','guided'][self.reveal_mode.currentIndex()],
                    brush_width=self.brush_width.value(),
                    painting_hand=self.hand if self.show_paint_hand.isChecked() else None)
    def refresh(self,*args):
        if not self.drawing: return
        options=self.options()
        duration=options.pop('duration'); options.pop('fps')
        ratio=options['height']/options['width']
        options['width']=960; options['height']=round(960*ratio)
        if options['final_image'] is not None:
            self.canvas.frame=render_color_timeline(self.drawing,self.position,duration=duration,**options)
        else:
            for key in ('final_image','fade_duration','hold_duration','reveal_mode','brush_width','painting_hand'):
                options.pop(key)
            self.canvas.frame=render(self.drawing,self.position,**options)
        self.canvas.update()
        length=self.timeline_length()
        self.clock.setText(f'{self.position*length:.2f} / {length:.2f} s')
    def scrub(self,value): self.position=value/1000; self.refresh()
    def toggle(self):
        if self.position>=1: self.slider.setValue(0)
        self.playing=not self.playing; self.last=time.perf_counter()
    def restart(self): self.slider.setValue(0); self.playing=True; self.last=time.perf_counter()
    def tick(self):
        if not self.playing: return
        now=time.perf_counter(); self.position=min(1,self.position+(now-self.last)/self.timeline_length()); self.last=now
        self.slider.blockSignals(True); self.slider.setValue(round(self.position*1000)); self.slider.blockSignals(False); self.refresh()
        if self.position>=1: self.playing=False
    def save(self):
        parent=QFileDialog.getExistingDirectory(self,'Choose destination; a new sequence folder will be created')
        if not parent: return
        import copy
        folder=Path(parent)/datetime.now().strftime('StrokeScribe_%Y%m%d_%H%M%S_%f')
        self.worker=Exporter(copy.deepcopy(self.drawing),folder,self.options(),self.mov.isChecked())
        self.worker.progress.connect(self.export_progress); self.worker.done.connect(lambda p:self.export_done('Saved: '+p)); self.worker.failed.connect(lambda e:self.export_done('Export stopped: '+e)); self.worker.finished.connect(self.export_finished)
        self.export.setEnabled(False); self.cancel.setEnabled(True); self.status.setText('Exporting locally…'); self.worker.start()
    def export_progress(self,i,n): self.progress.setRange(0,n); self.progress.setValue(i)
    def export_done(self,message): self.status.setText(message); self.status.setWordWrap(True)
    def export_finished(self): self.export.setEnabled(True); self.cancel.setEnabled(False); self.progress.setRange(0,100); self.progress.setValue(100)
    def cancel_export(self):
        if self.worker: self.worker.requestInterruption(); self.status.setText('Cancelling after current frame. MOV encoding, if started, must finish.')
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.cancel_export(); QMessageBox.information(self,'Export running','Please wait for the current export to stop before closing.'); event.ignore()
        else: event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setStyle('Fusion'); window=Window()
    if len(sys.argv)>1:
        try: window.set_drawing(import_svg(sys.argv[1]))
        except Exception as e: QMessageBox.warning(window,'Cannot import',str(e))
    window.show(); sys.exit(app.exec())
