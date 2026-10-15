import sys, time
from collections import OrderedDict
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase, QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,QDoubleSpinBox,QSpinBox,QComboBox,QFileDialog,QListWidget,QSlider,QCheckBox,QPlainTextEdit,QMessageBox,QSplitter,QProgressBar,QScrollArea,QColorDialog)
from engine import import_svg, render, export_frames, encode_mov, encode_webm, encode_mp4, scale_animation_frame, apply_lettering_background
from lettering import make_text
from font_library import (STARTER_FONTS, installed_font, make_font_text,
                          import_font, download_google_font)
from color_reveal import load_color_image, render_color_timeline, timeline_duration
from version import APP_VERSION, DISPLAY_NAME, RELEASE_DATE

# Shared application branding asset (path independent of the working directory).
BRAND_ICON = Path(__file__).resolve().parent / 'assets' / 'strokescribe_icon.png'


DONE_SOUND = Path(__file__).resolve().parent / 'assets' / 'export_done.wav'
DEFAULT_HAND = Path(__file__).resolve().parent / 'assets' / 'default_hand.png'


def play_done_sound():
    """Short chime when an export finishes successfully (never on failure)."""
    try:
        if sys.platform == 'win32' and DONE_SOUND.is_file():
            import winsound
            winsound.PlaySound(str(DONE_SOUND),
                               winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            QApplication.beep()
    except Exception:
        pass  # A missing sound must never disturb a finished export.


def format_seconds(seconds):
    """0:42 or 1:05:09 style duration for the export timer."""
    seconds=max(0,int(round(seconds)))
    hours,rest=divmod(seconds,3600); minutes,secs=divmod(rest,60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'
# Paint mode menu order (studio_workspace). Stroke-guided and Clean contour
# painting were retired from the menu; their code remains for old renders.
REVEAL_MODES = ('fade', 'brush', 'adaptive')

class Canvas(QWidget):
    def __init__(self):
        super().__init__(); self.frame=None; self.background=0; self.setMinimumSize(550,330)
    def set_background(self,index):
        self.background=index; self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.fillRect(self.rect(),QColor('#141d28'))
        if self.frame:
            size=self.frame.size(); size.scale(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            x=(self.width()-size.width())//2; y=(self.height()-size.height())//2
            p.save(); p.setClipRect(x,y,size.width(),size.height())
            if self.background:
                p.fillRect(x,y,size.width(),size.height(),QColor('#ffffff' if self.background==1 else '#242d3b'))
            else:
                for a in range(x,x+size.width(),20):
                    for b in range(y,y+size.height(),20):
                        p.fillRect(a,b,20,20,QColor('#e8edf0' if ((a-x)//20+(b-y)//20)%2==0 else '#d4dce2'))
            p.drawImage(x,y,self.frame.scaled(size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)); p.restore()
        p.end()

class Exporter(QThread):
    progress=Signal(int,int); done=Signal(str); failed=Signal(str)
    def __init__(self,drawing,folder,options,mov,webm=False,webm_quality=28,keep_png=True,
                 mp4=False,mp4_background='white'):
        super().__init__()
        self.drawing=drawing; self.folder=Path(folder); self.options=options
        self.mov=mov; self.webm=webm; self.webm_quality=webm_quality
        self.keep_png=keep_png; self.mp4=mp4; self.mp4_background=mp4_background
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
            if self.mp4:
                if self.isInterruptionRequested(): raise InterruptedError('Export cancelled; completed files were retained.')
                self.progress.emit(0,0)
                videos.append(encode_mp4(self.folder,self.options['fps'],self.mp4_background))
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

class FontInstaller(QThread):
    complete=Signal(object); update=Signal(str)
    def __init__(self,families):
        super().__init__(); self.families=tuple(families)
    def run(self):
        installed=[]; errors=[]
        for family in self.families:
            if self.isInterruptionRequested(): break
            self.update.emit('Downloading '+family+' from Google Fonts…')
            try:
                installed.append((family,str(download_google_font(family))))
            except (OSError,ValueError,RuntimeError) as exc:
                errors.append((family,str(exc)))
        self.complete.emit((installed,errors))


class ImageBuilder(QThread):
    ready=Signal(object)
    failed=Signal(str)
    stage=Signal(str,int,bool)
    analysis_ready=Signal(object)
    def __init__(self,path,mode,detail,brush_width,spacing,ai_model='qwen3-vl:4b-instruct',
                 cached_analysis=None,ai_profile='balanced'):
        super().__init__()
        self.path=path; self.mode=mode; self.detail=detail
        self.brush_width=brush_width; self.spacing=spacing; self.ai_model=ai_model
        self.cached_analysis=cached_analysis
        self.ai_profile=ai_profile
        self.analysis=None
        self.timings={}
        self.success=False
        self.failed_message=None
        self.cache_hit=False
    def run(self):
        try:
            from image_reconstruct import reconstruct, load_raster
            from adaptive_hand import plan_for
            if self.mode=='ai_redraw':
                if self.cached_analysis is not None:
                    self.analysis=self.cached_analysis
                    self.cache_hit=True
                    self.timings['vision']=0.
                    self.stage.emit('Reusing previous AI object analysis',45,False)
                else:
                    self.stage.emit('Asking Ollama to identify image objects',0,True)
                    started=time.perf_counter()
                    from semantic_redraw import local_vision_analysis
                    original=load_raster(self.path)
                    self.analysis=local_vision_analysis(original,self.ai_model,profile=self.ai_profile)
                    self.timings['vision']=time.perf_counter()-started
                    # Store a successful semantic plan even if later local
                    # contour generation fails. No disk or cloud cache used.
                    self.analysis_ready.emit(self.analysis)
                self.stage.emit('Building image contours and color regions',65,False)
            else:
                self.stage.emit('Tracing image details',20,False)
            started=time.perf_counter()
            result=reconstruct(self.path,self.mode,self.detail,
                               ai_model=self.ai_model,ai_analysis=self.analysis,
                               ai_profile=self.ai_profile)
            self.timings['contours']=time.perf_counter()-started
            self.stage.emit('Preparing animation and brush routes',85,False)
            started=time.perf_counter()
            plan_for(result.drawing,result.image,self.brush_width,self.spacing)
            self.timings['brush']=time.perf_counter()-started
            self.stage.emit('Drawing is ready',100,False)
            self.success=True
            self.ready.emit(result)
        except Exception as exc:
            self.failed_message=str(exc)
            self.failed.emit(self.failed_message)

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
        self.ai_analysis_cache=OrderedDict()
        self.analysis_started=0.
        self.analysis_stage=''
        self.svg_state=None
        self.drawing=None
        self.hand=None
        self.final_image=None
        self.worker=None
        self.font_worker=None
        self.playing=False
        self.position=0
        self.project_title='Sample drawing'
        self.letter_ink_color='#25364a'
        self.letter_bg_color=None
        self.last_letter_bg_index=0
        self.reorder_undo=[]
        self.reorder_redo=[]
        # Rapid brush-width changes should not synchronously rebuild the entire
        # paint plan for every spinbox/wheel event on the GUI thread.
        self.brush_preview_timer=QTimer(self)
        self.brush_preview_timer.setSingleShot(True)
        self.brush_preview_timer.setInterval(180)
        self.brush_preview_timer.timeout.connect(self.refresh)
        from studio_workspace import build_workspace
        build_workspace(self,Canvas,BRAND_ICON)
        self.use_builtin_hand(refresh=False)
        self.set_drawing(import_svg(Path(__file__).parent/'samples'/'drawing.svg'))
        self.timer=QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.analysis_timer=QTimer(self)
        self.analysis_timer.setInterval(1000)
        self.analysis_timer.timeout.connect(self.update_analysis_elapsed)

    def open_export(self):
        self.inspector_tabs.setCurrentIndex(2)
        self.export.setFocus()

    def open_svg_source(self):
        self.source_type.setCurrentIndex(0)
        self.load()

    def open_image_source(self):
        self.source_type.setCurrentIndex(1)
        self.load()

    def show_quick_help(self):
        QMessageBox.information(self,'StrokeScribe Studio — Quick help',
            '1. Use the project menu or Source panel to import SVG or image artwork.\\n'
            '2. For text, choose a font and Animate lettering.\\n'
            '3. Select Animation, Hand, or Export in the right inspector.\\n'
            '4. Use the timeline to preview and the Export Animation button to render.\\n'
            'Undo and Redo apply to stroke-order changes.')

    def update_project_title(self,name):
        self.project_title=str(name or 'Untitled artwork')
        short=self.project_title if len(self.project_title)<=27 else self.project_title[:24]+'…'
        self.project_menu.setText('▣  '+short+'  ▾')
        self.project_menu.setToolTip('Current artwork: '+self.project_title)

    def update_history_controls(self):
        self.undo_button.setEnabled(bool(self.reorder_undo))
        self.redo_button.setEnabled(bool(self.reorder_redo))

    def undo_stroke_order(self):
        if not self.reorder_undo or not self.drawing:return
        self.reorder_redo.append(list(self.drawing.strokes))
        self.drawing.strokes=self.reorder_undo.pop()
        self.order.clear()
        self.order.addItems([s.name for s in self.drawing.strokes])
        self.update_history_controls()
        self.refresh()

    def redo_stroke_order(self):
        if not self.reorder_redo or not self.drawing:return
        self.reorder_undo.append(list(self.drawing.strokes))
        self.drawing.strokes=self.reorder_redo.pop()
        self.order.clear()
        self.order.addItems([s.name for s in self.drawing.strokes])
        self.update_history_controls()
        self.refresh()

    def sync_workspace(self,*args):
        image_source=bool(self.source_type.currentIndex())
        self.load_color_button.setEnabled(not image_source)
        self.use_color.setEnabled(not image_source and self.final_image is not None)
        self.reveal_mode.setEnabled(not image_source)
        self.paint_form.setRowVisible(self.reveal_mode,not image_source)
        self.paint_form.setRowVisible(self.image_paint_hint,image_source)
        self.paint_form.setRowVisible(self.color_fade,not image_source)
        self.paint_form.setRowVisible(self.image_duration,image_source)
        self.paint_form.setRowVisible(self.image_animation,image_source)
        paint_only=image_source and self.image_animation.currentIndex()==1
        self.duration.setEnabled(not paint_only)
        self.speed.setEnabled(not paint_only)
        self.reveal_mode.setToolTip('Image sources use Adaptive Hand Painting.' if image_source else '')
        self.output_summary.setText(f'{self.res.currentText()}  •  {self.fps.value()} fps')
        busy=bool((self.worker and self.worker.isRunning()) or (self.builder and self.builder.isRunning()))
        self.export.setEnabled(self.drawing is not None and not busy)
        self.quick_export.setEnabled(self.drawing is not None and not busy)
        self.webm_quality.setEnabled(self.webm.isChecked())
        self.keep_png.setEnabled(self.webm.isChecked() or self.mov.isChecked() or self.mp4.isChecked())
        self.mp4_background.setEnabled(self.mp4.isChecked())
        self.play.setText('Pause' if self.playing else 'Play')

    def show_version_info(self):
        build_file = Path(__file__).resolve().parent / 'BUILD_INFO.txt'
        build = build_file.read_text(encoding='utf-8').strip() if build_file.exists() else 'Source ZIP / local checkout'
        QMessageBox.information(self, 'About StrokeScribe',
            f'{DISPLAY_NAME}\nRelease date: {RELEASE_DATE}\n\nBuild details:\n{build}\n\n'
            'If your title bar shows a different version, you are running an older folder.')

    def number(self,minimum,maximum,value,step):
        w=QDoubleSpinBox(); w.setRange(minimum,maximum); w.setValue(value); w.setSingleStep(step); return w
    def set_drawing(self,drawing):
        self.playing=False
        self.drawing=drawing
        self.reorder_undo.clear()
        self.reorder_redo.clear()
        self.update_history_controls()
        self.order.clear()
        self.order.addItems([s.name for s in drawing.strokes])
        self.note.setText('\n'.join(drawing.warnings) or 'Ready. Press Play to draw from the beginning.')
        self.position=0 if getattr(drawing,'source_kind',None)=='image' else 1
        self.slider.setValue(round(self.position*1000))
        self.update_project_title(self.project_title)
        self.refresh()
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
    def update_image_mode(self,*args):
        active=self.image_mode.currentIndex()==2
        self.image_source_form.setRowVisible(self.ai_model,active)
        self.image_source_form.setRowVisible(self.ai_profile,active)
        self.image_source_form.setRowVisible(self.ai_note,active)
        self.rebuild_button.setText('Analyze with local AI' if active else 'Apply image settings')
        if active: self.warm_up_ai()

    def warm_up_ai(self,*args):
        """Load the selected local model in the background (no generation).

        Gives Ollama a head start so Analyze does not also wait for the model
        to load. Repeats for the same model/profile are skipped for a minute.
        """
        if self.image_mode.currentIndex()!=2: return
        if self.builder and self.builder.isRunning(): return
        model=self.ai_model.currentText().strip()
        profile=self.ai_profile.currentText().strip().lower()
        if not model: return
        warmed=getattr(self,'ai_warmed',{})
        now=time.monotonic()
        if now-warmed.get((model,profile),-1e9)<60: return
        warmed[(model,profile)]=now; self.ai_warmed=warmed
        import threading
        from semantic_redraw import warm_up_model
        threading.Thread(target=warm_up_model,args=(model,profile),daemon=True).start()

    def rebuild_image(self):
        if self.image_path: self.build_image(self.image_path)

    def analysis_cache_key(self,path,model,profile='balanced'):
        # Cache is memory-only and scoped to the exact file revision/model.
        # Detail is purposefully excluded: Low/Medium/High reuses the SAME
        # recognized objects while rebuilding only local contours.
        source=Path(path).resolve(strict=True)
        stat=source.stat()
        return (str(source).casefold(),stat.st_size,stat.st_mtime_ns,model,profile)

    def cache_ai_analysis(self,key,analysis):
        self.ai_analysis_cache.pop(key,None)
        self.ai_analysis_cache[key]=analysis
        # Bound stored scene plans; never persist image/model results to disk.
        while len(self.ai_analysis_cache)>4:
            self.ai_analysis_cache.popitem(last=False)

    def image_stage(self,message,percent,indeterminate):
        self.analysis_stage=message
        if indeterminate:
            self.progress.setRange(0,0)
        else:
            self.progress.setRange(0,100)
            self.progress.setValue(percent)
        self.update_analysis_elapsed()

    def update_analysis_elapsed(self):
        elapsed=max(0,time.perf_counter()-self.analysis_started)
        if self.builder and self.builder.isRunning():
            self.status.setText(f'{self.analysis_stage}… {elapsed:.0f}s elapsed')
        elif self.analysis_stage:
            self.status.setText(self.analysis_stage)

    def build_image(self,path):
        if self.builder and self.builder.isRunning(): return
        mode=['auto_trace','stroke_reconstruction','ai_redraw'][self.image_mode.currentIndex()]
        model=self.ai_model.currentText().strip()
        profile=self.ai_profile.currentText().strip().lower()
        cache_key=None
        cached=None
        if mode=='ai_redraw':
            try:
                cache_key=self.analysis_cache_key(path,model,profile)
            except OSError as exc:
                QMessageBox.warning(self,'Image import',str(exc))
                return
            cached=self.ai_analysis_cache.get(cache_key)
            if cached is not None:
                self.ai_analysis_cache.move_to_end(cache_key)
        self.playing=False
        self.image_path=path
        self.builder=ImageBuilder(path,mode,self.image_detail.currentText().lower(),
                                  self.brush_width.value(),self.stroke_spacing.value(),
                                  model,cached_analysis=cached,
                                  ai_profile=profile)
        self.builder.ready.connect(self.image_ready)
        self.builder.failed.connect(self.image_failed)
        self.builder.stage.connect(self.image_stage)
        if cache_key is not None:
            self.builder.analysis_ready.connect(
                lambda result,key=cache_key:self.cache_ai_analysis(key,result))
        self.builder.finished.connect(self.image_finished)
        self.analysis_started=time.perf_counter()
        self.analysis_stage=('Reusing existing AI image analysis'
                             if cached is not None else 'Preparing AI image analysis'
                             if mode=='ai_redraw' else 'Preparing image reconstruction')
        self.progress.setRange(0,0 if mode=='ai_redraw' and cached is None else 100)
        if self.progress.maximum()!=0:self.progress.setValue(0)
        self.source_type.setEnabled(False)
        self.import_button.setEnabled(False)
        self.rebuild_button.setEnabled(False)
        self.export.setEnabled(False)
        self.quick_export.setEnabled(False)
        self.update_analysis_elapsed()
        self.analysis_timer.start()
        self.builder.start()

    def image_failed(self,error):
        self.status.setText('Image analysis failed: '+str(error)[:140])
        QMessageBox.warning(self,'Image reconstruction',error)

    def image_ready(self,result):
        self.image_result=result
        self.update_project_title(result.filename)
        self.set_drawing(result.drawing)
        self.color_note.setText(result.filename+' • original colors; adaptive brush reveal')

    def image_finished(self):
        self.analysis_timer.stop()
        self.source_type.setEnabled(True)
        self.import_button.setEnabled(True)
        self.rebuild_button.setEnabled(True)
        self.export.setEnabled(self.drawing is not None and not (self.worker and self.worker.isRunning()))
        self.quick_export.setEnabled(self.drawing is not None and not (self.worker and self.worker.isRunning()))
        self.progress.setRange(0,100)
        if self.builder and self.builder.success:
            self.progress.setValue(100)
            times=self.builder.timings
            if self.builder.mode=='ai_redraw':
                vision=('reused (0s)' if self.builder.cache_hit
                        else f'{times.get("vision",0):.1f}s')
                self.status.setText(
                    f'AI Redraw ({self.builder.ai_profile.title()}) ready: Ollama {vision}; '
                    f'contours {times.get("contours",0):.1f}s; '
                    f'brush plan {times.get("brush",0):.1f}s. '
                    'Medium detail recommended.')
            else:
                self.status.setText(
                    f'Image ready: tracing {times.get("contours",0):.1f}s; '
                    f'brush plan {times.get("brush",0):.1f}s.')
        else:
            self.progress.setValue(0)
            message=self.builder.failed_message if self.builder else 'Unknown problem'
            self.status.setText('Image analysis failed: '+str(message)[:140])
        self.analysis_stage=''
    def load(self):
        if self.source_type.currentIndex():
            name,_=QFileDialog.getOpenFileName(self,'Import image','','Images (*.png *.jpg *.jpeg *.webp *.bmp)')
            if name: self.build_image(name)
            return
        name,_=QFileDialog.getOpenFileName(self,'Import SVG','','SVG (*.svg)')
        if name:
            try:
                drawing=import_svg(name)
                self.update_project_title(Path(name).name)
                self.set_drawing(drawing)
            except Exception as e: QMessageBox.warning(self,'Cannot import',str(e))
    def letter(self):
        try:
            label=self.font_select.currentText().strip()
            if not label or label=='Built-in single-line pen':
                drawing=make_text(self.text.toPlainText())
            else:
                font_path=self.font_select.currentData()
                if not label.startswith('Local: ') or not font_path:
                    font_path=installed_font(label)
                if font_path is None:
                    QMessageBox.information(self,'Handwriting font',
                        'This font has not been downloaded yet. Click '
                        '"Download selected Google Font" first, or import a local TTF/OTF file.')
                    return
                drawing=make_font_text(self.text.toPlainText(),font_path,
                                       int(self.font_size.value()))
            drawing.source_kind=getattr(drawing,'source_kind','lettering')
            self.apply_letter_style(drawing)
            self.source_type.setCurrentIndex(0)
            self.update_project_title('Lettering — '+self.text.toPlainText()[:16].replace('\n',' '))
            self.set_drawing(drawing)
        except Exception as e: QMessageBox.warning(self,'Lettering',str(e))

    def apply_letter_style(self,drawing=None):
        drawing=drawing or self.drawing
        if not drawing or getattr(drawing,'source_kind',None) not in ('font','lettering'):
            return
        drawing.lettering_background=self.letter_bg_color
        if drawing.source_kind=='font':
            drawing.font_color=self.letter_ink_color
        else:
            for stroke in drawing.strokes:
                stroke.color=self.letter_ink_color

    def choose_letter_color(self):
        color=QColorDialog.getColor(QColor(self.letter_ink_color),self,'Letter ink color')
        if not color.isValid():return
        self.letter_ink_color=color.name()
        self.font_color_button.setText('Letter color: '+self.letter_ink_color.upper())
        self.apply_letter_style()
        self.refresh()

    def select_letter_background(self,index):
        if index==0:
            color=None
        elif index==1:
            color='#ffffff'
        elif index==2:
            color='#000000'
        else:
            selected=QColorDialog.getColor(
                QColor(self.letter_bg_color or '#f5f0e4'),self,'Lettering background')
            if not selected.isValid():
                self.font_bg_mode.blockSignals(True)
                self.font_bg_mode.setCurrentIndex(self.last_letter_bg_index)
                self.font_bg_mode.blockSignals(False)
                return
            color=selected.name()
        self.letter_bg_color=color
        self.last_letter_bg_index=index
        self.apply_letter_style()
        self.refresh()

    def install_selected_font(self):
        name=self.font_select.currentText().strip()
        if name.startswith('Local: ') or name=='Built-in single-line pen' or not name:
            QMessageBox.information(self,'Fonts','Select or type a Google Fonts family first.')
            return
        self.start_font_install((name,))

    def install_starter_fonts(self):
        self.start_font_install(STARTER_FONTS)

    def start_font_install(self,families):
        if self.font_worker and self.font_worker.isRunning(): return
        self.font_worker=FontInstaller(families)
        self.font_worker.update.connect(self.font_note.setText)
        self.font_worker.complete.connect(self.font_install_complete)
        self.font_worker.finished.connect(self.font_install_finished)
        self.download_font.setEnabled(False)
        self.download_starters.setEnabled(False)
        self.font_worker.start()

    def font_install_complete(self,result):
        installed,errors=result
        message=f'{len(installed)} handwriting font(s) ready to use.'
        if errors:
            message+=' Failed: '+', '.join(f'{name}: {why}' for name,why in errors[:2])
        self.font_note.setText(message)
        if errors: QMessageBox.warning(self,'Google Fonts download',message)

    def font_install_finished(self):
        self.download_font.setEnabled(True)
        self.download_starters.setEnabled(True)

    def browse_google_fonts(self):
        QDesktopServices.openUrl(QUrl('https://fonts.google.com/?category=Handwriting'))

    def import_local_font(self):
        filename,_=QFileDialog.getOpenFileName(
            self,'Import TTF/OTF font','','Font files (*.ttf *.otf)')
        if not filename: return
        try:
            path=import_font(filename)
            label='Local: '+path.stem
            self.font_select.addItem(label,str(path))
            self.font_select.setCurrentIndex(self.font_select.count()-1)
            self.font_note.setText(f'Imported {path.name}. You are responsible for its license.')
        except Exception as exc:
            QMessageBox.warning(self,'Font import',str(exc))
    def move(self,direction):
        if not self.drawing:return
        i=self.order.currentRow(); j=i+direction
        if i<0 or not 0<=j<len(self.drawing.strokes): return
        self.reorder_undo.append(list(self.drawing.strokes))
        self.reorder_undo=self.reorder_undo[-50:]
        self.reorder_redo.clear()
        self.drawing.strokes[i],self.drawing.strokes[j]=self.drawing.strokes[j],self.drawing.strokes[i]
        item=self.order.takeItem(i)
        self.order.insertItem(j,item)
        self.order.setCurrentRow(j)
        self.update_history_controls()
        self.refresh()
    def loadhand(self):
        name,_=QFileDialog.getOpenFileName(self,'Hand overlay','','PNG (*.png)')
        if name:
            image=QImage(name)
            if image.isNull(): QMessageBox.warning(self,'Hand','Could not read PNG.'); return
            self.hand=image; self.hand_name.setText('Hand: '+Path(name).name); self.refresh()
    def use_builtin_hand(self,refresh=True):
        """Load the bundled StrokeScribe hand (calibrated pencil tip X 0.08, Y 0.13)."""
        image=QImage(str(DEFAULT_HAND)) if DEFAULT_HAND.is_file() else QImage()
        if image.isNull():
            self.hand_name.setText('Hand: none (built-in hand file missing)'); return
        self.hand=image; self.hand_name.setText('Hand: StrokeScribe built-in hand')
        if refresh: self.refresh()
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
        if (self.source_type.currentIndex() and self.image_animation.currentIndex()==1
                and options['final_image'] is not None):
            return max(.001,options['fade_duration'])+max(0.,options['hold_duration'])
        return timeline_duration(options['duration'],options['final_image'],options['fade_duration'],options['hold_duration'])
    def change_image_animation(self,*args):
        # Direct painting has to retain its color source; never let the user
        # accidentally request an invisible, no-color animation.
        if self.image_animation.currentIndex()==1 and self.source_type.currentIndex():
            self.preserve_colors.setChecked(True)
        self.preserve_colors.setEnabled(self.image_animation.currentIndex()!=1)
        self.refresh()

    def schedule_brush_refresh(self,*args):
        # Debounce potentially expensive plan_for() rebuilds while controls
        # are changing. A single preview reflects the final requested value.
        self.brush_preview_timer.start()

    def options(self):
        if self.drawing is not None and getattr(self.drawing,'source_kind',None)=='image':
            self.drawing.image_animation=['draw_paint','paint_only'][self.image_animation.currentIndex()]
            self.drawing.drawing_visibility='progressive'
        width,height=[int(x.strip()) for x in self.res.currentText().split('×')]
        options=dict(duration=self.effective_duration(),fps=self.fps.value(),width=width,height=height,
                    thickness=self.thickness.value(),hand=self.hand if self.showhand.isChecked() else None,
                    hand_scale=self.handsize.value(),anchor=(self.ax.value(),self.ay.value()),
                    final_image=self.final_image if self.use_color.isChecked() else None,
                    fade_duration=self.color_fade.value(),hold_duration=self.color_hold.value(),
                    reveal_mode=REVEAL_MODES[self.reveal_mode.currentIndex()],
                    brush_width=self.brush_width.value(),stroke_spacing=self.stroke_spacing.value(),
                    artwork_scale=self.artwork_size.value()/100.0,
                    painting_hand=self.hand if self.show_paint_hand.isChecked() else None)
        if self.source_type.currentIndex():
            paint_only=self.image_animation.currentIndex()==1
            options.update(final_image=self.image_result.image if self.image_result
                           and (self.preserve_colors.isChecked() or paint_only) else None,
                           fade_duration=self.image_duration.value(),reveal_mode='adaptive',
                           duration=0. if paint_only else options['duration'])
        return options
    def refresh(self,*args):
        self.sync_workspace()
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
        size=options.pop('artwork_scale')
        # The artwork is scaled after rasterization. Compensating the hand
        # before that transform keeps its FINAL size independent of Artwork
        # Size, while its pen-tip coordinates move with the artwork.
        options['hand_scale']/=size
        ratio=options['height']/options['width']
        options['width']=960; options['height']=round(960*ratio)
        try:
            if options['final_image'] is not None:
                frame=render_color_timeline(self.drawing,self.position,duration=duration,**options)
            else:
                for key in ('final_image','fade_duration','hold_duration','reveal_mode','brush_width','painting_hand','stroke_spacing'):
                    options.pop(key)
                frame=render(self.drawing,self.position,**options)
            frame=scale_animation_frame(frame,size)
            self.canvas.frame=apply_lettering_background(frame,self.drawing)
            self.canvas.update()
        except Exception as exc:
            # An invalid/expensive brush configuration must not throw out of
            # the Qt signal handler and terminate the application.
            self.status.setText('Preview could not be updated: '+str(exc)[:220])
            return
        length=self.timeline_length()
        self.clock.setText(f'{self.position*length:.2f} / {length:.2f} s')
    def scrub(self,value): self.position=value/1000; self.refresh()
    def toggle(self):
        if not self.drawing: return
        if self.position>=1: self.slider.setValue(0)
        self.playing=not self.playing; self.last=time.perf_counter(); self.sync_workspace()
    def restart(self):
        if not self.drawing: return
        self.slider.setValue(0); self.playing=True; self.last=time.perf_counter(); self.sync_workspace()
    def tick(self):
        if not self.playing or not self.drawing: return
        now=time.perf_counter(); self.position=min(1,self.position+(now-self.last)/self.timeline_length()); self.last=now
        self.slider.blockSignals(True); self.slider.setValue(round(self.position*1000)); self.slider.blockSignals(False); self.refresh()
        if self.position>=1: self.playing=False; self.sync_workspace()
    def save(self):
        if not self.drawing or (self.builder and self.builder.isRunning()) or (self.worker and self.worker.isRunning()): return
        parent=QFileDialog.getExistingDirectory(self,'Choose destination; a new sequence folder will be created')
        if not parent: return
        import copy
        folder=Path(parent)/datetime.now().strftime('StrokeScribe_%Y%m%d_%H%M%S_%f')
        options=self.options()
        self.worker=Exporter(copy.deepcopy(self.drawing),folder,options,
                             self.mov.isChecked(),self.webm.isChecked(),
                             self.webm_quality.value(),self.keep_png.isChecked(),
                             mp4=self.mp4.isChecked(),
                             mp4_background=('white','dark','black')[self.mp4_background.currentIndex()])
        self.worker.progress.connect(self.export_progress); self.worker.done.connect(lambda p:self.export_done('Saved: '+p)); self.worker.done.connect(lambda _p:play_done_sound()); self.worker.failed.connect(lambda e:self.export_done('Export stopped: '+e)); self.worker.finished.connect(self.export_finished)
        self.export.setEnabled(False); self.quick_export.setEnabled(False); self.cancel.setEnabled(True); self.status.setText('Exporting locally…')
        # Export timer: elapsed time, frame count and an estimate of time left.
        self.export_started=time.perf_counter(); self.export_step=(0,0); self.export_encoding=False
        if not hasattr(self,'export_clock'):
            self.export_clock=QTimer(self); self.export_clock.setInterval(250)
            self.export_clock.timeout.connect(self.update_export_status)
        self.export_clock.start(); self.worker.start()
    def export_elapsed(self):
        return format_seconds(time.perf_counter()-getattr(self,'export_started',time.perf_counter()))
    def update_export_status(self):
        i,n=self.export_step
        spent=time.perf_counter()-self.export_started
        if n:
            left=f'  •  about {format_seconds(spent/i*(n-i))} left' if i>=5 else ''
            self.status.setText(f'Exporting frame {i} / {n}  •  {format_seconds(spent)} elapsed{left}')
        elif self.export_encoding:
            self.status.setText(f'Encoding video…  •  {format_seconds(spent)} elapsed')
    def export_progress(self,i,n):
        # (0, 0) is the worker's signal that frame rendering is done and a
        # video encoder (FFmpeg) is running.
        self.progress.setRange(0,n); self.progress.setValue(i); self.export_step=(i,n)
        self.export_encoding=(n==0)
        self.update_export_status()
    def export_done(self,message):
        if hasattr(self,'export_clock'): self.export_clock.stop()
        self.status.setText(f'{message}  •  took {self.export_elapsed()}'); self.status.setWordWrap(True)
    def export_finished(self):
        if hasattr(self,'export_clock'): self.export_clock.stop()
        self.cancel.setEnabled(False); self.progress.setRange(0,100); self.progress.setValue(100); self.sync_workspace()
    def cancel_export(self):
        if self.worker:
            self.worker.requestInterruption()
            self.status.setText('Cancelling after current frame. FFmpeg encoding, if started, must finish.')
    def closeEvent(self,event):
        if self.font_worker and self.font_worker.isRunning():
            QMessageBox.information(self,'Font downloads',
                'Please wait for the current font download to finish.')
            event.ignore()
            return
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
