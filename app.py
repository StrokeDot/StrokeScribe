import sys, time
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,QDoubleSpinBox,QSpinBox,QComboBox,QFileDialog,QListWidget,QSlider,QCheckBox,QPlainTextEdit,QMessageBox,QSplitter,QProgressBar,QScrollArea)
from engine import import_svg, render, export_frames, encode_mov, encode_webm
from lettering import make_text
from color_reveal import load_color_image, render_color_timeline, timeline_duration
from version import APP_VERSION, DISPLAY_NAME, RELEASE_DATE

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
    def __init__(self,drawing,folder,options,mov,webm=False,webm_quality=28,keep_png=True):
        super().__init__()
        self.drawing=drawing; self.folder=Path(folder); self.options=options
        self.mov=mov; self.webm=webm; self.webm_quality=webm_quality
        self.keep_png=keep_png
    def run(self):
        try:
            def tick(i,n):
                self.progress.emit(i,n)
                return not self.isInterruptionRequested()
            export_frames(self.drawing,self.folder,callback=tick,**self.options)
            videos=[]
            if self.webm:
                if self.isInterruptionRequested(): raise InterruptedError('Export cancelled; PNG frames were retained.')
                self.progress.emit(0,0)
                videos.append(encode_webm(self.folder,self.options['fps'],self.webm_quality))
            if self.mov:
                if self.isInterruptionRequested(): raise InterruptedError('Export cancelled; completed files were retained.')
                self.progress.emit(0,0)
                videos.append(encode_mov(self.folder,self.options['fps']))
            if videos and not self.keep_png:
                # Only remove intermediate frames once every selected format
                # encoded successfully. Never remove user-supplied artwork.
                for frame in self.folder.glob('frame_*.png'):
                    frame.unlink()
            if videos:
                details=', '.join(f'{v.name} ({v.stat().st_size/1048576:.1f} MB)' for v in videos)
                self.done.emit(f'Saved: {details} in {self.folder}')
            else:
                self.done.emit(f'Saved PNG sequence: {self.folder}')
        except Exception as e: self.failed.emit(str(e))

class ImageBuilder(QThread):
    ready=Signal(object); failed=Signal(str)
    def __init__(self,path,mode,detail,brush_width,spacing):
        super().__init__(); self.path=path; self.mode=mode; self.detail=detail; self.brush_width=brush_width; self.spacing=spacing
    def run(self):
        try:
            from image_reconstruct import reconstruct
            result=reconstruct(self.path,self.mode,self.detail)
            from adaptive_hand import plan_for
            plan_for(result.drawing,result.image,self.brush_width,self.spacing)
            self.ready.emit(result)
        except Exception as exc: self.failed.emit(str(exc))

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        import os
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
        QApplication.instance().setFont(QFont('Segoe UI',10))
        self.image_result=None
        self.image_path=None
        self.builder=None
        self.svg_state=None
        self.drawing=None
        self.hand=None
        self.final_image=None
        self.worker=None
        self.playing=False
        self.position=0
        from studio_workspace import build_workspace
        build_workspace(self,Canvas,BRAND_ICON)
        self.set_drawing(import_svg(Path(__file__).parent/'samples'/'drawing.svg'))
        self.timer=QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)

    def show_version_info(self):
        build_file = Path(__file__).resolve().parent / 'BUILD_INFO.txt'
        build = build_file.read_text(encoding='utf-8').strip() if build_file.exists() else 'Source ZIP / local checkout'
        QMessageBox.information(self, 'About StrokeScribe',
            f'{DISPLAY_NAME}\nRelease date: {RELEASE_DATE}\n\nBuild details:\n{build}\n\n'
            'If your title bar shows a different version, you are running an older folder.')

    def number(self,minimum,maximum,value,step):
        w=QDoubleSpinBox(); w.setRange(minimum,maximum); w.setValue(value); w.setSingleStep(step); return w
    def set_drawing(self,drawing):
        self.playing=False; self.drawing=drawing; self.order.clear(); self.order.addItems([s.name for s in drawing.strokes]); self.note.setText('\n'.join(drawing.warnings) or 'Ready. Press Play to draw from the beginning.'); self.position=1; self.slider.setValue(1000); self.refresh()
    def change_source(self,index):
        self.playing=False
        if index:
            self.svg_state=(self.drawing,self.final_image,self.use_color.isChecked())
            self.image_controls.show(); self.import_button.setText('Import image…')
            if self.image_result: self.set_drawing(self.image_result.drawing)
            else:
                self.drawing=None; self.order.clear(); self.canvas.frame=None; self.canvas.update()
                self.note.setText('Import a PNG, JPEG, WebP or BMP to begin.')
        else:
            self.image_controls.hide(); self.import_button.setText('Import SVG…')
            if self.svg_state:
                drawing,self.final_image,checked=self.svg_state
                self.use_color.setChecked(checked); self.set_drawing(drawing)
        self.export.setEnabled(self.drawing is not None)
        self.quick_export.setEnabled(self.drawing is not None)
        self.refresh()
    def rebuild_image(self):
        if self.image_path: self.build_image(self.image_path)
    def build_image(self,path):
        if self.builder and self.builder.isRunning(): return
        self.playing=False; self.image_path=path
        self.builder=ImageBuilder(path,['auto_trace','stroke_reconstruction'][self.image_mode.currentIndex()],self.image_detail.currentText().lower(),self.brush_width.value(),self.stroke_spacing.value())
        self.builder.ready.connect(self.image_ready)
        self.builder.failed.connect(lambda error: QMessageBox.warning(self,'Image import',error))
        self.builder.finished.connect(self.image_finished)
        self.source_type.setEnabled(False); self.import_button.setEnabled(False); self.rebuild_button.setEnabled(False); self.export.setEnabled(False); self.quick_export.setEnabled(False)
        self.status.setText('Analyzing image locally…'); self.builder.start()
    def image_ready(self,result):
        self.image_result=result; self.set_drawing(result.drawing)
        self.color_note.setText(result.filename+' • original colors; adaptive brush reveal')
    def image_finished(self):
        self.source_type.setEnabled(True); self.import_button.setEnabled(True); self.rebuild_button.setEnabled(True)
        self.export.setEnabled(self.drawing is not None and not (self.worker and self.worker.isRunning()))
        self.quick_export.setEnabled(self.drawing is not None and not (self.worker and self.worker.isRunning()))
        self.status.setText('Image analysis finished. Apply image settings after changing mode or detail.')
    def load(self):
        if self.source_type.currentIndex():
            name,_=QFileDialog.getOpenFileName(self,'Import image','','Images (*.png *.jpg *.jpeg *.webp *.bmp)')
            if name: self.build_image(name)
            return
        name,_=QFileDialog.getOpenFileName(self,'Import SVG','','SVG (*.svg)')
        if name:
            try: self.set_drawing(import_svg(name))
            except Exception as e: QMessageBox.warning(self,'Cannot import',str(e))
    def letter(self):
        try:
            self.source_type.setCurrentIndex(0)
            self.set_drawing(make_text(self.text.toPlainText()))
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
        if self.source_type.currentIndex():
            QMessageBox.information(self,'Image colors','Image mode uses the imported image. Switch to SVG to load a matching colored PNG.'); return
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
        options=self.options()
        return timeline_duration(options['duration'],options['final_image'],options['fade_duration'],options['hold_duration'])
    def options(self):
        width,height=[int(x.strip()) for x in self.res.currentText().split('×')]
        options=dict(duration=self.effective_duration(),fps=self.fps.value(),width=width,height=height,
                    thickness=self.thickness.value(),hand=self.hand if self.showhand.isChecked() else None,
                    hand_scale=self.handsize.value(),anchor=(self.ax.value(),self.ay.value()),
                    final_image=self.final_image if self.use_color.isChecked() else None,
                    fade_duration=self.color_fade.value(),hold_duration=self.color_hold.value(),
                    reveal_mode=['fade','brush','guided','clean','adaptive'][self.reveal_mode.currentIndex()],
                    brush_width=self.brush_width.value(),stroke_spacing=self.stroke_spacing.value(),
                    painting_hand=self.hand if self.show_paint_hand.isChecked() else None)
        if self.source_type.currentIndex():
            options.update(final_image=self.image_result.image if self.image_result and self.preserve_colors.isChecked() else None,
                           fade_duration=self.image_duration.value(),reveal_mode='adaptive')
        return options
    def refresh(self,*args):
        if not self.drawing:
            self.stage_timeline.update_state(0,0,0,0)
            self.clock.setText('0.00 / 0.00 s')
            return
        options=self.options()
        self.stage_timeline.update_state(options['duration'],
            options['fade_duration'] if options['final_image'] is not None else 0,
            options['hold_duration'] if options['final_image'] is not None else 0,
            self.position)
        duration=options.pop('duration'); options.pop('fps')
        ratio=options['height']/options['width']
        options['width']=960; options['height']=round(960*ratio)
        if options['final_image'] is not None:
            self.canvas.frame=render_color_timeline(self.drawing,self.position,duration=duration,**options)
        else:
            for key in ('final_image','fade_duration','hold_duration','reveal_mode','brush_width','painting_hand','stroke_spacing'):
                options.pop(key)
            self.canvas.frame=render(self.drawing,self.position,**options)
        self.canvas.update()
        length=self.timeline_length()
        self.clock.setText(f'{self.position*length:.2f} / {length:.2f} s')
    def scrub(self,value): self.position=value/1000; self.refresh()
    def toggle(self):
        if not self.drawing: return
        if self.position>=1: self.slider.setValue(0)
        self.playing=not self.playing; self.last=time.perf_counter()
    def restart(self):
        if not self.drawing: return
        self.slider.setValue(0); self.playing=True; self.last=time.perf_counter()
    def tick(self):
        if not self.playing or not self.drawing: return
        now=time.perf_counter(); self.position=min(1,self.position+(now-self.last)/self.timeline_length()); self.last=now
        self.slider.blockSignals(True); self.slider.setValue(round(self.position*1000)); self.slider.blockSignals(False); self.refresh()
        if self.position>=1: self.playing=False
    def save(self):
        if not self.drawing or (self.builder and self.builder.isRunning()): return
        parent=QFileDialog.getExistingDirectory(self,'Choose destination; a new sequence folder will be created')
        if not parent: return
        import copy
        folder=Path(parent)/datetime.now().strftime('StrokeScribe_%Y%m%d_%H%M%S_%f')
        self.worker=Exporter(copy.deepcopy(self.drawing),folder,self.options(),
                             self.mov.isChecked(),self.webm.isChecked(),
                             self.webm_quality.value(),self.keep_png.isChecked())
        self.worker.progress.connect(self.export_progress); self.worker.done.connect(lambda p:self.export_done('Saved: '+p)); self.worker.failed.connect(lambda e:self.export_done('Export stopped: '+e)); self.worker.finished.connect(self.export_finished)
        self.export.setEnabled(False); self.cancel.setEnabled(True); self.status.setText('Exporting locally…'); self.worker.start()
    def export_progress(self,i,n): self.progress.setRange(0,n); self.progress.setValue(i)
    def export_done(self,message): self.status.setText(message); self.status.setWordWrap(True)
    def export_finished(self): self.export.setEnabled(True); self.cancel.setEnabled(False); self.progress.setRange(0,100); self.progress.setValue(100)
    def cancel_export(self):
        if self.worker:
            self.worker.requestInterruption()
            self.status.setText('Cancelling after current frame. FFmpeg encoding, if started, must finish.')
    def closeEvent(self,event):
        if self.builder and self.builder.isRunning():
            QMessageBox.information(self,'Image analysis','Please wait for image analysis to finish.'); event.ignore(); return
        if self.worker and self.worker.isRunning():
            self.cancel_export(); QMessageBox.information(self,'Export running','Please wait for the current export to stop before closing.'); event.ignore()
        else: event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setStyle('Fusion'); window=Window()
    if len(sys.argv)>1:
        try: window.set_drawing(import_svg(sys.argv[1]))
        except Exception as e: QMessageBox.warning(window,'Cannot import',str(e))
    window.show(); sys.exit(app.exec())
