import os, sys, time
from collections import OrderedDict
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl, QItemSelectionModel
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase, QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QListWidgetItem,QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,QDoubleSpinBox,QSpinBox,QComboBox,QFileDialog,QListWidget,QSlider,QCheckBox,QPlainTextEdit,QMessageBox,QSplitter,QProgressBar,QScrollArea,QColorDialog)
from engine import import_svg, render, export_frames, encode_mov, encode_webm, encode_mp4, scale_animation_frame, apply_lettering_background
from lettering import make_text
from font_library import (STARTER_FONTS, installed_font, make_font_text,
                          import_font, download_google_font)
from color_reveal import load_color_image, render_color_timeline, timeline_duration
from version import APP_VERSION, DISPLAY_NAME, RELEASE_DATE

# Shared application branding asset (path independent of the working directory).
BRAND_ICON = Path(__file__).resolve().parent / 'assets' / 'strokescribe_logo.png'   # 1024 px master


DEFAULT_HAND = Path(__file__).resolve().parent / 'assets' / 'default_hand.png'


def play_finished_sound():
    """Windows' own notification sound when an export is finished."""
    try:
        if sys.platform == 'win32':
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        else:
            QApplication.beep()
    except Exception:
        pass


def format_seconds(seconds):
    """0:42 or 1:05:09 style duration for the export timer."""
    seconds=max(0,int(round(seconds)))
    hours,rest=divmod(seconds,3600); minutes,secs=divmod(rest,60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'
# Paint mode menu order (studio_workspace). Stroke-guided and Clean contour
# painting were retired from the menu; their code remains for old renders.
REVEAL_MODES = ('brush', 'adaptive', 'zigzag', 'rows', 'columns', 'short_zigzag')

def timecode(seconds):
    """00:04.25 style time for the monitor."""
    seconds=max(0.,float(seconds))
    minutes,rest=divmod(seconds,60)
    return f'{int(minutes):02d}:{rest:05.2f}'


class Canvas(QWidget):
    """Program monitor: the frame on its preview background, plus a loading card."""
    def __init__(self):
        super().__init__(); self.frame=None; self.background=0; self.custom_colour=None; self.blend_mode='Normal'; self.art_frame=None; self.hand_frame=None; self.overlay_frame=None; self.art_opacity=100.; self.setMinimumSize(550,330)
        self.busy_text=None; self.busy_percent=None; self.busy_detail=''
        self._spin=0
        self._spinner=QTimer(self); self._spinner.setInterval(40)
        self._spinner.timeout.connect(self._advance)
        self.on_click=None          # on_click(x, y, add) in frame pixels
        self.on_drag=None           # on_drag('start', x, y) then ('move', dx, dy) / ('done'): dx, dy in fractions of the frame
        self.on_wheel=None          # on_wheel(steps, x, y) → False when not used
        self.on_double=None         # on_double(x, y)
        self.box_provider=None      # () → (x, y, w, h) in frame pixels of a box to outline, or None
        self._press=None
        self.highlight=[]           # selected lines: polylines in frame pixels
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    DRAG_START=6                    # pixels the mouse moves before a click becomes a drag
    def _frame_point(self,pos):
        x,y,size=self.frame_rect()
        return ((pos.x()-x)*self.frame.width()/max(1,size.width()),
                (pos.y()-y)*self.frame.height()/max(1,size.height()))
    def mousePressEvent(self,event):
        self._press=None
        if self.frame is None or self.busy_text is not None or event.button()!=Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._press=(event.position(),False)
        self.setFocus()
    def mouseMoveEvent(self,event):
        press=getattr(self,'_press',None)
        if press is None or self.on_drag is None or not event.buttons()&Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        start,dragging=press
        d=event.position()-start
        if not dragging and abs(d.x())+abs(d.y())<self.DRAG_START: return
        if not dragging:
            sx,sy=self._frame_point(start)
            if self.on_drag('start',sx,sy) is False:
                self._press=None; return
            self._press=(start,True)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        _,_,size=self.frame_rect()
        self.on_drag('move',d.x()/max(1,size.width()),d.y()/max(1,size.height()))
    def mouseReleaseEvent(self,event):
        press=getattr(self,'_press',None); self._press=None
        if press is None: return super().mouseReleaseEvent(event)
        start,dragging=press
        if dragging:
            self.unsetCursor()
            if self.on_drag is not None: self.on_drag('done',0.,0.)
            return
        if self.on_click is None or self.frame is None: return
        fx,fy=self._frame_point(start)
        if 0<=fx<=self.frame.width() and 0<=fy<=self.frame.height():
            mods=event.modifiers()
            self.on_click(fx,fy,bool(mods&(Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)))
    def _checker(self,w,h,a,b):
        """Transparency grid, made once per size and theme."""
        key=(w,h,a,b)
        if getattr(self,'_checker_key',None)!=key:
            from PySide6.QtGui import QPixmap
            pix=QPixmap(max(1,w),max(1,h)); pix.fill(QColor(b))
            p=QPainter(pix)
            for i,xx in enumerate(range(0,w,20)):
                for j,yy in enumerate(range(0,h,20)):
                    if (i+j)%2==0: p.fillRect(xx,yy,20,20,QColor(a))
            p.end()
            self._checker_pix=pix; self._checker_key=key
        return self._checker_pix
    def wheelEvent(self,event):
        if self.on_wheel is not None and self.frame is not None and self.busy_text is None:
            steps=event.angleDelta().y()/120
            x,y=self._frame_point(event.position())
            if steps and self.on_wheel(steps,x,y) is not False:
                event.accept(); return
        super().wheelEvent(event)
    def mouseDoubleClickEvent(self,event):
        if self.on_double is not None and self.frame is not None and self.busy_text is None:
            x,y=self._frame_point(event.position())
            self.on_double(x,y); event.accept(); return
        super().mouseDoubleClickEvent(event)
    def set_background(self,index):
        self.background=index; self.update()
    def set_busy(self,text,percent=None,detail=''):
        """Show a loading card over the picture (text None hides it)."""
        self.busy_text=text; self.busy_percent=percent; self.busy_detail=detail or ''
        if text is None: self._spinner.stop()
        elif not self._spinner.isActive(): self._spinner.start()
        self.update()
    def _advance(self):
        self._spin=(self._spin+1)%1000; self.update()
    def frame_rect(self):
        from PySide6.QtCore import QSize
        size=(self.frame.size() if self.frame else QSize(16,9))
        size.scale(self.size()*.98 if self.frame is None else self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        x=(self.width()-size.width())//2; y=(self.height()-size.height())//2
        return x,y,size
    def paintEvent(self,event):
        import theme
        from PySide6.QtCore import QRectF
        c=theme.colors()
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor(c['monitor']))
        if self.frame:
            x,y,size=self.frame_rect()
            from PySide6.QtGui import QPainterPath as _Path
            rounded=_Path(); rounded.addRoundedRect(QRectF(x,y,size.width(),size.height()),10,10)
            p.save(); p.setClipPath(rounded)
            if self.background==7 or self.background==8:
                p.fillRect(x,y,size.width(),size.height(),QColor('#000000' if self.background==7
                                                                 else (self.custom_colour or '#f5f0e4')))
            elif self.background>=3:
                from backgrounds import TEXTURES, texture_qimage
                key=(TEXTURES[self.background-3],size.width(),size.height())
                if getattr(self,'_texture_key',None)!=key:
                    self._texture=texture_qimage(*key); self._texture_key=key
                p.drawImage(x,y,self._texture)
            elif self.background:
                p.fillRect(x,y,size.width(),size.height(),QColor('#ffffff' if self.background==1 else c['preview_dark']))
            else:
                p.drawPixmap(x,y,self._checker(size.width(),size.height(),c['checker_a'],c['checker_b']))
            # Scaled while painting (no copy of the frame every time).
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            from blend_modes import composition_mode
            p.setCompositionMode(composition_mode(self.blend_mode))
            if self.art_frame is not None:
                p.setOpacity(max(0.,min(1.,self.art_opacity/100.)))
                p.drawImage(QRectF(x,y,size.width(),size.height()),self.art_frame)
                p.setOpacity(1.)
            else:
                p.drawImage(QRectF(x,y,size.width(),size.height()),self.frame)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if self.overlay_frame is not None:
                p.drawImage(QRectF(x,y,size.width(),size.height()),self.overlay_frame)
            if self.hand_frame is not None:
                p.drawImage(QRectF(x,y,size.width(),size.height()),self.hand_frame)
            box=self.box_provider() if self.box_provider is not None else None
            if box:
                from PySide6.QtGui import QPen
                k=size.width()/max(1,self.frame.width())
                bx,by,bw,bh=box
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255,255,255,200),3)); p.drawRoundedRect(QRectF(x+bx*k-3,y+by*k-3,bw*k+6,bh*k+6),6,6)
                p.setPen(QPen(QColor(c['accent']),2,Qt.PenStyle.DashLine)); p.drawRoundedRect(QRectF(x+bx*k-3,y+by*k-3,bw*k+6,bh*k+6),6,6)
            if self.highlight:
                from PySide6.QtGui import QPainterPath, QPen
                from PySide6.QtCore import QPointF
                k=size.width()/max(1,self.frame.width())
                path=QPainterPath()
                for line in self.highlight:
                    if not line: continue
                    path.moveTo(QPointF(x+line[0][0]*k,y+line[0][1]*k))
                    for px,py in line[1:]: path.lineTo(QPointF(x+px*k,y+py*k))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255,255,255,190),6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
                p.setPen(QPen(QColor(c['accent']),3,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
                # Where the pen starts each selected line.
                p.setBrush(QColor(c['accent'])); p.setPen(QPen(QColor('white'),1.5))
                for line in self.highlight:
                    if line: p.drawEllipse(QPointF(x+line[0][0]*k,y+line[0][1]*k),4.5,4.5)
            p.restore()
        if self.busy_text is not None:
            overlay=QColor(c['monitor']); overlay.setAlpha(205)
            p.fillRect(self.rect(),overlay)
            w=min(360.,self.width()-40.); h=112.
            card=QRectF((self.width()-w)/2,(self.height()-h)/2,w,h)
            p.setPen(QColor(c['border_strong'])); p.setBrush(QColor(c['panel']))
            p.drawRoundedRect(card,14,14)
            title=QFont(self.font()); title.setPointSizeF(10.5); title.setBold(True)
            p.setFont(title); p.setPen(QColor(c['text']))
            p.drawText(card.adjusted(20,16,-20,-h+40),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,self.busy_text)
            small=QFont(self.font()); small.setPointSizeF(8.5)
            p.setFont(small); p.setPen(QColor(c['muted']))
            right=f'{self.busy_percent}%' if self.busy_percent is not None else ''
            p.drawText(card.adjusted(20,16,-20,-h+40),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,right)
            bar=QRectF(card.x()+20,card.y()+54,w-40,8)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['track']))
            p.drawRoundedRect(bar,4,4)
            p.setBrush(QColor(c['accent']))
            if self.busy_percent is None:
                # Indeterminate: a segment sliding along the bar.
                seg=bar.width()*.28; t=(self._spin%60)/60.
                left=bar.x()-seg+(bar.width()+seg)*t
                p.save(); p.setClipRect(bar)
                p.drawRoundedRect(QRectF(left,bar.y(),seg,bar.height()),4,4); p.restore()
            else:
                p.drawRoundedRect(QRectF(bar.x(),bar.y(),max(8.,bar.width()*max(0,min(100,self.busy_percent))/100),bar.height()),4,4)
            p.setPen(QColor(c['muted']))
            p.drawText(card.adjusted(20,72,-20,-12),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,
                       self.busy_detail or 'The timeline unlocks when the drawing is ready.')
        p.end()

class PreviewSound:
    """Plays the pencil/brush soundtrack in sync with the preview."""
    def __init__(self):
        self.player=None; self.key=None; self.path=None
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            self.player=QMediaPlayer(); self.output=QAudioOutput()
            self.player.setAudioOutput(self.output)
        except Exception:
            self.player=None            # no audio support: preview stays silent
    def play(self,drawing,options,volume,seconds):
        """volume: pencil/brush sounds (None = off); options['audio']: voiceover/music."""
        if self.player is None or drawing is None: return
        import tempfile,hashlib
        voice=options.pop('audio',None)
        signature=repr((tuple(id(s) for s in drawing.strokes),id(drawing),
                        {k:v for k,v in options.items() if isinstance(v,(int,float,str,tuple))},
                        repr(options.get('erase') and {k:v for k,v in options['erase'].items() if k!='image'}),
                        volume if volume is None else round(volume,2),repr(voice)))
        key=hashlib.sha1(signature.encode()).hexdigest()
        if key!=self.key:
            from frame_render import timeline_seconds
            folder=Path(tempfile.gettempdir())/'strokescribe-sound'
            folder.mkdir(exist_ok=True)
            effects=None
            if volume is not None:
                from sound import soundtrack
                effects=soundtrack(drawing,options,folder/f'effects_{key[:12]}.wav',volume)
            if voice:
                from audio_track import mix
                self.path=mix(effects,voice['path'],voice['volume'],voice['offset'],
                              timeline_seconds(drawing,options),folder/f'preview_{key[:12]}.wav')
            else:
                self.path=effects
            self.key=key
            if self.path is None: return
            self.player.setSource(QUrl.fromLocalFile(str(self.path)))
        if self.path is None: return
        self.player.setPosition(int(seconds*1000))
        self.player.play()
    def stop(self):
        if self.player is not None:
            self.player.stop()


class Exporter(QThread):
    progress=Signal(int,int); done=Signal(str); failed=Signal(str)
    def __init__(self,drawing,folder,options,mov,webm=False,webm_quality=28,keep_png=True,
                 mp4=False,mp4_background='white',sound_volume=None,background=None):
        super().__init__()
        self.sound_volume=sound_volume; self.background=background
        self.drawing=drawing; self.folder=Path(folder); self.options=options
        self.mov=mov; self.webm=webm; self.webm_quality=webm_quality
        self.keep_png=keep_png; self.mp4=mp4; self.mp4_background=mp4_background
    def run(self):
        try:
            from export_job import run_export
            self.done.emit(run_export(
                self.drawing,self.folder,self.options,self.mov,self.webm,self.webm_quality,
                self.keep_png,self.mp4,self.mp4_background,self.sound_volume,
                progress=self.progress.emit,interrupted=self.isInterruptionRequested,background=self.background))
        except Exception as e: self.failed.emit(str(e))

class PlanWorker(QThread):
    """Plans a brush route in the background (brush width / spacing changes)."""
    def __init__(self,drawing,image,brush_width,spacing):
        super().__init__()
        self.args=(drawing,image,brush_width,spacing)
    def run(self):
        try:
            from adaptive_hand import plan_for
            plan_for(*self.args)
        except Exception:
            pass

class SceneExporter(QThread):
    """All scenes as one video (scenes.export_scenes), off the UI thread."""
    progress=Signal(int,int); done=Signal(str); failed=Signal(str)
    def __init__(self,scene_list,folder,settings,hand):
        super().__init__()
        self.scene_list=scene_list; self.folder=Path(folder); self.settings=settings; self.hand=hand
    def run(self):
        try:
            from scenes import export_scenes
            self.done.emit(export_scenes(self.scene_list,self.folder,self.settings,self.hand,
                                         progress=self.progress.emit,interrupted=self.isInterruptionRequested))
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
    """Line art reconstruction of an imported image, off the UI thread."""
    ready=Signal(object)
    failed=Signal(str)
    stage=Signal(str,int,bool)
    def __init__(self,path,detail,brush_width,spacing,clean_faint=False,style='clean',
                 animation='standard',paint_method='adaptive',line_guide=None):
        super().__init__()
        self.paint_method=paint_method
        self.line_guide=line_guide
        self.path=path; self.detail=detail; self.mode='line_art'; self.style=style
        self.animation=animation
        self.brush_width=brush_width; self.spacing=spacing
        self.clean_faint=clean_faint
        self.timings={}
        self.success=False
        self.failed_message=None
    def run(self):
        try:
            from image_reconstruct import reconstruct
            from adaptive_hand import plan_for
            self.stage.emit('Drawing line art from the image',20,False)
            started=time.perf_counter()
            if self.line_guide:
                self.stage.emit('Lining up the line drawing with the image',20,False)
            result=reconstruct(self.path,'line_art',self.detail,clean_faint=self.clean_faint,
                               style=self.style,animation=self.animation,
                               line_guide=self.line_guide)
            self.timings['lines']=time.perf_counter()-started
            self.stage.emit('Preparing animation and brush routes',85,False)
            started=time.perf_counter()
            result.drawing.paint_method=self.paint_method
            plan_for(result.drawing,result.image,self.brush_width,self.spacing)
            self.timings['brush']=time.perf_counter()-started
            self.stage.emit('Drawing is ready',100,False)
            self.success=True
            self.ready.emit(result)
        except Exception as exc:
            self.failed_message=str(exc)
            self.failed.emit(self.failed_message)

from artwork_workflow import ArtworkWorkflow

from source_editing import SourceEditing

class Window(SourceEditing,ArtworkWorkflow,QMainWindow):
    def __init__(self):
        super().__init__()
        import os
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
        QApplication.instance().setFont(QFont('Segoe UI',10))
        self.image_result=None
        self.image_path=None
        self.image_guide=None          # optional line drawing traced instead of the image
        self.ai_engine=None
        self.builder=None
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
        from history import History
        from project_lifecycle import ProjectChangeTracker
        self.history=History()
        self.project_changes=ProjectChangeTracker()
        self._autosaved_signature=None
        self._closed=False
        self._restoring=False
        self._lines_cache=None
        self.busy=False
        self._preparing=False
        self.preview_sound=None
        self.audio_path=None; self.audio_seconds=None
        self.paint_hand_path=None; self.paint_hand_tip=None
        self.sound_files={'sound_pencil_file':None,'sound_brush_file':None,'sound_eraser_file':None}
        from scenes import DEFAULT_TRANSITION, DEFAULT_TRANSITION_SECONDS
        self.scenes=[dict(state=None,transition=DEFAULT_TRANSITION,
                          transition_seconds=DEFAULT_TRANSITION_SECONDS,name=None,thumb=None)]
        self.scene_index=0
        self._scene_cache={}           # preview of other scenes: id(state) -> prepared scene
        self._camera_key=None; self._camera_path=None
        self._frames=OrderedDict(); self._frame_bytes=0; self._view=None
        self.overlays=[]               # pictures and titles on top of this scene (overlays.py)
        self.selected_overlay=None
        # Rapid brush-width changes should not synchronously rebuild the entire
        # paint plan for every spinbox/wheel event on the GUI thread.
        self.brush_preview_timer=QTimer(self)
        self.brush_preview_timer.setSingleShot(True)
        self.brush_preview_timer.setInterval(180)
        self.brush_preview_timer.timeout.connect(self.quiet_refresh)
        import applog
        applog.setup()
        applog._on_error.append(self.show_error)
        from studio_workspace import build_workspace
        build_workspace(self,Canvas,BRAND_ICON)
        self.canvas.on_click=self.click_preview
        self.canvas.on_drag=self.drag_picture
        self.canvas.box_provider=self.overlay_box
        self.canvas.on_wheel=self.preview_wheel
        self.canvas.on_double=self.preview_double
        from menus import build_menus
        build_menus(self)
        self.watch_settings()
        self.update_sound_buttons()
        self.latest_version=None
        self.autosave_timer=QTimer(self)
        self.autosave_timer.setInterval(60000)
        self.autosave_timer.timeout.connect(self.autosave_tick)
        self.autosave_timer.start()
        if not os.environ.get('QT_QPA_PLATFORM')=='offscreen':
            QTimer.singleShot(1200,self.offer_recovery)
            from update_dialog import StartupCheck
            self.update_check=StartupCheck(self)
            self.update_check.found.connect(self.update_found)
            QTimer.singleShot(4000,self.update_check.start)
        self.use_builtin_hand(refresh=False)
        # Setup level chosen in the setup window (Fast/Balanced/Quality/Max).
        import preflight
        preflight.ensure_ffmpeg_on_path()
        saved=preflight.load_setup()
        if saved['tier']: self.apply_tier(saved['tier'])
        # First launch (or when enabled): show the setup window once the main
        # window is up. Never in headless/offscreen runs such as tests.
        if saved['show_at_startup'] and QApplication.platformName()!='offscreen':
            QTimer.singleShot(400,self.open_setup)
        self.set_drawing(import_svg(Path(__file__).parent/'samples'/'drawing.svg'))
        self.timer=QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.analysis_timer=QTimer(self)
        self.analysis_timer.setInterval(1000)
        self.analysis_timer.timeout.connect(self.update_analysis_elapsed)
        self.reset_history()
        self.project_changes.mark_saved(self.project_state())

    # ---------------------------------------------------------------- theme
    def apply_theme(self,name):
        import theme
        from studio_workspace import wordmark_html
        theme.set_current(name)
        theme.save(theme.current())
        self.setStyleSheet(theme.stylesheet(theme.current(),self.theme_assets))
        self.brand_wordmark.setText(wordmark_html())
        self.update_theme_button()
        self.update_transport_icons()
        self.canvas.update(); self.stage_timeline.update()

    def toggle_theme(self):
        import theme
        self.apply_theme('light' if theme.current()=='dark' else 'dark')

    def update_transport_icons(self):
        import theme
        from studio_workspace import transport_icon
        from PySide6.QtCore import QSize
        c=theme.colors()
        self.play.setIcon(transport_icon('pause' if self.playing else 'play',c['accent_text']))
        self.play.setIconSize(QSize(18,18))
        for button,kind in ((self.to_start,'start'),(self.restart_button,'restart'),(self.to_end,'end')):
            button.setIcon(transport_icon(kind,c['text'] if button.isEnabled() else c['dim']))
            button.setIconSize(QSize(18,18))
        if not hasattr(self,'sound_on'): return
        on=self.sound_on.isChecked()
        self.mute_button.setIcon(transport_icon('sound' if on else 'mute',c['text'] if on else c['dim']))
        self.mute_button.setIconSize(QSize(18,18))
        self.mute_button.setToolTip(('Sound is ON. Click to mute' if on else 'Sound is OFF (muted). Click for sound')
                                    +' — pencil, brush and eraser sounds in the preview and the exported video.')

    def update_theme_button(self):
        import theme
        dark=theme.current()=='dark'
        self.theme_button.setText('☀' if dark else '☾')
        self.theme_button.setToolTip('Switch to light mode' if dark else 'Switch to dark mode')

    # ---------------------------------------------------------- busy state
    def set_busy(self,text,percent=None,detail=''):
        """Loading card on the monitor; the timeline stays locked until ready."""
        self.busy=True
        self.playing=False
        if self.preview_sound is not None: self.preview_sound.stop()
        self.canvas.set_busy(text,percent,detail)
        self.stage_timeline.set_locked(True)
        for button in (self.play,self.restart_button,self.to_start,self.to_end):
            button.setEnabled(False)
        self.update_transport_icons()
        self.timeline_status.setText('Preparing…  the timeline unlocks when ready')
        self.sync_workspace()

    def clear_busy(self):
        self.busy=False
        self.canvas.set_busy(None)
        self.stage_timeline.set_locked(False)
        for button in (self.play,self.restart_button,self.to_start,self.to_end):
            button.setEnabled(True)
        self.update_transport_icons()
        self.timeline_status.setText('')
        self.sync_workspace()

    def show_busy_now(self,text,detail=''):
        """Busy card for work done right here (not in a thread): paint it first."""
        self.set_busy(text,None,detail)
        from PySide6.QtCore import QEventLoop
        self.canvas.repaint()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def ensure_brush_plan(self,options):
        """Build a missing brush plan behind a loading card before showing it."""
        image=options.get('final_image')
        if image is None or self.drawing is None:
            return
        mode=options.get('reveal_mode')
        image_source=getattr(self.drawing,'source_kind',None)=='image'
        if mode in ('adaptive','zigzag','rows','columns','short_zigzag'):
            self.drawing.paint_method=mode
        elif not image_source:
            return
        from adaptive_hand import plan_ready, plan_for
        bw,sp=options.get('brush_width',.14),options.get('stroke_spacing',.55)
        if plan_ready(self.drawing,image,bw,sp):
            return True
        quiet=getattr(self,'_quiet_plan',False)
        self._quiet_plan=False
        if quiet and self.canvas.frame is not None:
            # Small change (brush width / spacing): plan in the background and
            # keep showing the last picture; no loading card.
            self.plan_in_background(image,bw,sp)
            return False
        self._preparing=True
        try:
            self.show_busy_now('Preparing brush route',
                               'Planning how the hand paints the colours…')
            plan_for(self.drawing,image,bw,sp)
        finally:
            self._preparing=False
            self.clear_busy()
        return True

    def plan_in_background(self,image,bw,sp):
        key=(id(self.drawing),image.cacheKey(),round(bw,4),round(sp,4))
        worker=getattr(self,'plan_worker',None)
        if worker is not None and worker.isRunning():
            self._plan_pending=True
            return
        if getattr(self,'_plan_key',None)==key and worker is not None:
            return
        self._plan_key=key; self._plan_pending=False
        self.plan_worker=PlanWorker(self.drawing,image,bw,sp)
        self.plan_worker.finished.connect(self.plan_finished)
        self.timeline_status.setText('Updating the brush route…')
        self.plan_worker.start()

    def plan_finished(self):
        self.timeline_status.setText('')
        if getattr(self,'_plan_pending',False):
            self._quiet_plan=True
        self.refresh()

    def prepare_eraser(self,*args):
        """Choosing an eraser style: plan it now behind the loading card."""
        if self._preparing or not self.drawing or not self.erase_mode.currentIndex():
            self.refresh(); return
        options=self.preview_options()
        if options is None or not options.get('erase'):
            self.refresh(); return
        from frame_render import split_erase, erase_setup
        opts,erase,_,_=split_erase(self.drawing,1.,options)
        self._preparing=True
        try:
            self.show_busy_now('Preparing the eraser','Finding where the picture is…')
            erase_setup(self.drawing,opts,erase)
        except Exception as exc:
            import applog; applog.error('Eraser could not be prepared',exc)
            self.status.setText('Eraser could not be prepared: '+str(exc)[:160])
        finally:
            self._preparing=False
            self.clear_busy()
        self.refresh()

    def preview_options(self):
        """The options the preview renders with (preview size, hand scale compensated)."""
        if not self.drawing: return None
        options=self.options()
        options.pop('fps',None)
        options['hand_scale']/=options['artwork_scale']
        ratio=options['height']/options['width']
        options['width']=960; options['height']=round(960*ratio)
        options['ghost']=.22
        return options

    def open_setup(self):
        """Setup & system check window (also opened from the ⚙ button)."""
        from setup_wizard import SetupDialog
        dialog=SetupDialog(self)
        dialog.tier_applied.connect(self.apply_tier)
        dialog.exec()
    def apply_tier(self,tier):
        """Use the chosen level's Line art detail for imported images."""
        import preflight
        settings=preflight.TIERS.get(tier)
        if not settings: return
        self.image_detail.setCurrentIndex(('low','medium','high','max').index(settings['detail']))
        self.setup_tier=tier
        if hasattr(self,'status'):
            self.status.setText(f'Setup level: {settings["label"]}  •  '
                                f'Line art detail {settings["detail"].title()}')
    def open_export(self):
        from studio_workspace import TABS
        self.inspector_tabs.setCurrentIndex(TABS['export'])
        self.export.setFocus()



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

    # ------------------------------------------------ undo / redo (everything)
    def snapshot(self):
        import json
        return {'settings':self.settings_state(),
                'strokes':tuple(self.drawing.strokes) if self.drawing else (),
                'overlays':json.dumps(getattr(self,'overlays',[])),
                'source':self.source_snapshot()}

    def reset_history(self):
        if hasattr(self,'history_timer'): self.history_timer.stop()
        self.history.reset(self.snapshot())
        self.update_history_controls()

    def note_change(self,*args):
        """A setting changed: remember it once the user pauses (one undo step per edit)."""
        if self._restoring or not hasattr(self,'history_timer'): return
        self.project_changes.mark_changed()
        self.history_timer.start()

    def commit_history(self):
        if self._restoring: return
        self.history_timer.stop()
        if self.history.record(self.snapshot()):
            self.project_changes.mark_changed()
        self.update_history_controls()

    def watch_settings(self):
        """Every setting control feeds the undo history."""
        from PySide6.QtWidgets import QAbstractButton
        self.history_timer=QTimer(self)
        self.history_timer.setSingleShot(True); self.history_timer.setInterval(450)
        self.history_timer.timeout.connect(self.commit_history)
        for name in self.PROJECT_SETTINGS:
            widget=getattr(self,name,None)
            if isinstance(widget,QComboBox): widget.currentIndexChanged.connect(self.note_change)
            elif isinstance(widget,(QSpinBox,QDoubleSpinBox)): widget.valueChanged.connect(self.note_change)
            elif isinstance(widget,QAbstractButton): widget.toggled.connect(self.note_change)

    def update_history_controls(self):
        self.undo_button.setEnabled(self.history.can_undo())
        self.redo_button.setEnabled(self.history.can_redo())

    def undo(self):
        if self.history_timer.isActive(): self.commit_history()
        self.restore(self.history.undo())

    def redo(self):
        if self.history_timer.isActive(): self.commit_history()
        self.restore(self.history.redo())

    # Older names (stroke order only) kept for compatibility.
    def undo_stroke_order(self): self.undo()
    def redo_stroke_order(self): self.redo()

    def restore(self,snapshot):
        if snapshot is None: return
        from projects import set_widget_value
        self._restoring=True
        source_changed=snapshot.get('source') is not self.source_snapshot()
        try:
            self.restore_source_snapshot(snapshot.get('source'))
            settings=snapshot['settings']
            # Older undo snapshots have none of the optional appearance
            # controls. Reset to legacy defaults instead of leaking values
            # from a different image element.
            settings=dict({'artwork_opacity':100,'paper_cleanup':False,
                           'paper_tolerance':24,'paper_softness':12},**settings)
            for name in self.PROJECT_SETTINGS:
                widget=getattr(self,name,None)
                if widget is None or name not in settings: continue
                widget.blockSignals(True); set_widget_value(widget,settings[name]); widget.blockSignals(False)
            if settings.get('audio_path')!=self.audio_path:
                self.set_audio(settings.get('audio_path'),refresh=False)
            self.paint_hand_path=settings.get('paint_hand_path')
            self.paint_hand_tip=settings.get('paint_hand_tip')
            self.update_paint_hand_label()
            for key in self.sound_files: self.sound_files[key]=settings.get(key)
            self.update_sound_buttons()
            self.canvas.set_background(self.preview_background.currentIndex())
            self.preserve_colors.setEnabled(self.image_animation.currentIndex()==0)
            if 'overlays' in snapshot:
                import json
                self.overlays=json.loads(snapshot['overlays'])
                if not any(o.get('id')==self.selected_overlay for o in self.overlays): self.selected_overlay=None
            if self.drawing is not None and snapshot['strokes']:
                selected=set(id(s) for s in self.selected_strokes())
                self.drawing.strokes=list(snapshot['strokes'])
                self.fill_order(keep=selected)
        finally:
            self._restoring=False
        self.update_history_controls()
        if source_changed:
            self.scenes[self.scene_index]['thumb']=None
            self.fill_scenes()
        self.sync_workspace();self.refresh()

    # ------------------------------------------------ lines: select and edit
    def fill_order(self,keep=(),current=None):
        """Rebuild the line list (each item holds its stroke)."""
        from history import describe
        self.order.blockSignals(True)
        self.order.clear()
        if self.drawing:
            for stroke in self.drawing.strokes:
                item=QListWidgetItem(describe(stroke))
                item.setData(Qt.ItemDataRole.UserRole,stroke)
                self.order.addItem(item)
                if id(stroke) in keep: item.setSelected(True)
            if current is not None and 0<=current<self.order.count():
                self.order.setCurrentRow(current,QItemSelectionModel.SelectionFlag.NoUpdate)
        self.order.blockSignals(False)
        self.lines_selected()

    def selected_rows(self):
        return sorted(self.order.row(item) for item in self.order.selectedItems())

    def selected_strokes(self):
        if not self.drawing: return []
        return [self.drawing.strokes[i] for i in self.selected_rows() if i<len(self.drawing.strokes)]

    def lines_selected(self):
        """Selection changed: show its pace/pause and outline it on the preview."""
        strokes=self.selected_strokes()
        for widget in (self.reverse_button,self.delete_button,self.line_pace,self.line_pause):
            widget.setEnabled(bool(strokes))
        if strokes:
            from stroke_timing import pace_name
            self.line_pace.blockSignals(True); self.line_pause.blockSignals(True)
            self.line_pace.setCurrentText(pace_name(getattr(strokes[0],'pace',1.)))
            self.line_pause.setValue(float(getattr(strokes[0],'pause',0.) or 0.))
            self.line_pace.blockSignals(False); self.line_pause.blockSignals(False)
        self.update_highlight()

    def preview_lines(self,options=None):
        """Every line as a polyline in preview-frame pixels (Artwork size and camera applied)."""
        if not self.drawing or self.canvas.frame is None: return []
        from motion import strokes_on_canvas
        w,h=self.canvas.frame.width(),self.canvas.frame.height()
        scale=self.artwork_size.value()/100.
        key=(tuple(id(s) for s in self.drawing.strokes),w,h,scale)
        if self._lines_cache is None or self._lines_cache[0]!=key:
            self._lines_cache=(key,strokes_on_canvas(self.drawing,w,h,scale))
        lines=self._lines_cache[1]
        ox,oy=self.picture_x.value()/100.*w,self.picture_y.value()/100.*h
        if ox or oy:
            lines=[[(x+ox,y+oy) for x,y in line] for line in lines]
        camera=self._camera_path if self.camera.currentIndex() else None
        if camera is not None:
            z,cx,cy=camera.at(self.position)
            if z>1.0001:
                vw,vh=w/z,h/z
                left=min(max(0.,cx*w-vw/2),w-vw); top=min(max(0.,cy*h-vh/2),h-vh)
                lines=[[((x-left)*z,(y-top)*z) for x,y in line] for line in lines]
        return lines

    def update_highlight(self):
        rows=self.selected_rows()
        lines=self.preview_lines() if rows else []
        self.canvas.highlight=[lines[i] for i in rows if i<len(lines)]
        self.canvas.update()

    def line_at(self,x,y,tolerance=14.):
        """Index of the line nearest to (x, y) in preview pixels, or None."""
        import numpy as np
        best,best_d=None,tolerance*self.canvas.frame.width()/max(1,self.canvas.frame_rect()[2].width())
        for i,line in enumerate(self.preview_lines()):
            if not line: continue
            pts=np.asarray(line,float)
            if len(pts)==1:
                d=float(np.hypot(*(pts[0]-(x,y))))
            else:
                a,b=pts[:-1],pts[1:]; ab=b-a
                t=np.clip(((x-a[:,0])*ab[:,0]+(y-a[:,1])*ab[:,1])/np.maximum((ab**2).sum(1),1e-9),0,1)
                d=float(np.hypot(a[:,0]+ab[:,0]*t-x,a[:,1]+ab[:,1]*t-y).min())
            if d<best_d: best,best_d=i,d
        return best

    # ------------------------------------------------------------ overlays
    def scene_seconds(self):
        from frame_render import timeline_seconds
        return timeline_seconds(self.drawing,self.options()) if self.drawing else 4.

    def playhead_seconds(self):
        if self.all_scenes() or self.board_mode():
            lengths,joins=self.scene_timeline()
            at=self.position*(sum(lengths)+sum(joins))-self.element_start()
            return max(0.,min(self.scene_seconds(),at))
        return self.position*self.scene_seconds()

    def add_overlay(self,item):
        """Put a new overlay at the playhead (on a free track) and open its settings."""
        import overlays
        total=self.scene_seconds()
        start=min(max(0.,self.playhead_seconds()),max(0.,total-.5))
        if self.position>=.999: start=0.
        item['start']=round(start,2); item['duration']=round(max(.5,min(3.,total-start)),2)
        busy=[o for o in self.overlays if overlays.end_of(o)>item['start'] and o['start']<overlays.end_of(item)]
        used={int(o.get('track',0)) for o in busy}
        item['track']=next(t for t in range(10) if t not in used)
        self.overlays.append(item)
        self.project_changes.mark_changed()
        self.selected_overlay=item['id']
        if self.board_mode(): self.preview_scope.setCurrentIndex(1)
        self.commit_history(); self.refresh()
        return item

    def add_overlay_picture(self,path=None,at=None):
        import overlays
        if not self.drawing: return None
        if not path:
            path,_=QFileDialog.getOpenFileName(self,'Add a picture on top','',
                                               'Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.svg)')
            if not path: return None
        try:
            item=overlays.image_item_from_file(path)
        except Exception as exc:
            QMessageBox.warning(self,'Picture',f'This picture could not be opened: {exc}'); return None
        if at is not None:
            self.position=max(0.,min(1.,at/max(.01,self.scene_seconds())))
        item=self.add_overlay(item)
        self.status.setText(f'Picture "{item["name"]}" added at {item["start"]:.1f} s with a {item["effect_in"]} '
                            'effect. Drag it on the preview to place it, double-click its clip for more.')
        return item

    def add_overlay_text(self):
        import overlays
        if not self.drawing: return None
        item=self.add_overlay(overlays.new_text())
        self.edit_overlay(item['id'])
        return item

    def find_overlay(self,oid):
        return next((o for o in self.overlays if o.get('id')==oid),None)

    def select_overlay(self,oid):
        self.selected_overlay=oid or None
        self.refresh()

    def move_overlay_clip(self,oid,start,duration,track):
        item=self.find_overlay(oid)
        if item is None: return
        item.update(start=start,duration=duration,track=track)
        self.project_changes.mark_changed()
        self.refresh()

    def edit_overlay(self,oid):
        from overlay_dialog import OverlayDialog
        item=self.find_overlay(oid)
        if item is None: return
        self.selected_overlay=oid
        dialog=OverlayDialog(self,item,self.scene_seconds(),changed=lambda it: self.refresh())
        dialog.exec()
        if dialog.deleted:
            self.overlay_action(oid,'delete'); return
        self.commit_history(); self.refresh()

    def overlay_action(self,oid,action):
        import copy, uuid
        item=self.find_overlay(oid)
        if item is None: return
        if action=='edit':
            self.edit_overlay(oid); return
        if action=='duplicate':
            twin=copy.deepcopy(item); twin['id']=uuid.uuid4().hex[:10]
            twin['track']=max(int(o.get('track',0)) for o in self.overlays)+1
            self.overlays.append(twin); self.selected_overlay=twin['id']
        elif action=='delete':
            self.overlays=[o for o in self.overlays if o.get('id')!=oid]
            if self.selected_overlay==oid: self.selected_overlay=None
            self.status.setText(f'Overlay "{item.get("name","")}" deleted (Ctrl+Z brings it back).')
        self.commit_history(); self.refresh()

    def overlay_at(self,x,y):
        """The overlay shown at (x, y) of the preview now (the selected one first), or None."""
        import overlays
        if self.canvas.frame is None or not self.overlays: return None
        W,H=self.canvas.frame.width(),self.canvas.frame.height()
        t=self.playhead_seconds()
        order=sorted(self.overlays,key=lambda o: (o.get('id')!=self.selected_overlay,-int(o.get('track',0))))
        for item in order:
            if overlays.state_at(item,t) is None: continue
            bx,by,bw,bh=overlays.box(item,W,H)
            if bx-6<=x<=bx+bw+6 and by-6<=y<=by+bh+6:
                return item
        return None

    def overlay_box(self):
        """Dashed box around the selected overlay on the preview (frame pixels), or None."""
        import overlays
        item=self.find_overlay(self.selected_overlay) if self.selected_overlay else None
        if item is None or self.canvas.frame is None or self.all_scenes() or self.board_mode(): return None
        if overlays.state_at(item,self.playhead_seconds()) is None: return None
        return overlays.box(item,self.canvas.frame.width(),self.canvas.frame.height())

    def show_error(self,text):
        """Something went wrong: say so (the details are in the log)."""
        if hasattr(self,'status'):
            self.status.setText('⚠ Something went wrong: '+text[:160]+'  •  Details: Help → Open log folder')

    def open_log_folder(self):
        import applog
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(applog.folder())))

    def copy_log(self):
        import applog
        QApplication.clipboard().setText(applog.tail(300))
        self.status.setText('The last part of the log is copied: paste it in the chat with Henry.')

    # ------------------------------------------------------------ background
    def export_backgrounds(self):
        from export_job import backgrounds_from_settings
        return backgrounds_from_settings(self.settings_state())

    def background_spec(self):
        from backgrounds import spec
        return spec(self.preview_background.currentText(),getattr(self,'background_color',None))

    def show_background(self):
        self.canvas.custom_colour=getattr(self,'background_color',None)
        self.canvas.set_background(self.preview_background.currentIndex())

    def background_chosen(self,index):
        """Custom colour…: pick the colour."""
        if self.preview_background.itemText(index).startswith('Custom'):
            colour=QColorDialog.getColor(QColor(getattr(self,'background_color',None) or '#f5f0e4'),self,'Background colour')
            if colour.isValid():
                self.background_color=colour.name()
                self.preview_background.setItemText(index,'Custom colour…')
            self.show_background(); self.note_change()

    def drag_picture(self,kind,dx,dy):
        """Drag on the preview: move the picture on the page (Position X / Y), or a frame on the Board."""
        if self.board_mode() or (kind!='start' and getattr(self,'_board_drag',None)):
            return self.board_drag(kind,dx,dy)
        if kind=='start' and not self.all_scenes():
            item=self.overlay_at(dx,dy)
            if item is not None:
                self.playing=False
                self.selected_overlay=item['id']
                self._overlay_drag=(item,float(item.get('x',.5)),float(item.get('y',.5)))
                return True
        drag=getattr(self,'_overlay_drag',None)
        if drag is not None and kind!='start':
            item,x0,y0=drag
            if kind=='move':
                item['x'],item['y']=round(x0+dx,4),round(y0+dy,4)
                self.refresh()
            else:
                self._overlay_drag=None; self.commit_history(); self.refresh()
                self.status.setText(f'"{item.get("name","")}" moved. Mouse wheel on it: bigger or smaller.')
            return
        if kind=='start':
            if not self.drawing or self.all_scenes() or self.busy: return False
            self._drag_from=(self.picture_x.value(),self.picture_y.value())
            self.playing=False
            return True
        if kind=='move':
            x0,y0=getattr(self,'_drag_from',(0.,0.))
            self.picture_x.setValue(round(x0+dx*100,1))
            self.picture_y.setValue(round(y0+dy*100,1))
        else:
            self.commit_history()
            self.status.setText(f'Picture moved to X {self.picture_x.value():.0f}%, Y {self.picture_y.value():.0f}%. '
                                'Click "Center" (Animation tab) to put it back in the middle.')

    def click_preview(self,x,y,add=False):
        if not self.board_mode() and not self.all_scenes():
            item=self.overlay_at(x,y)
            if item is not None or self.selected_overlay:
                self.selected_overlay=item['id'] if item is not None else None
                self.refresh()
                if item is not None: return
        if self.board_mode():
            self.board_select(self.board_pick(x,y)); self.refresh(); return
        if self.all_scenes(): return          # lines are edited in "This scene" preview
        index=self.line_at(x,y)
        if index is None:
            if not add: self.order.clearSelection()
            return
        item=self.order.item(index)
        if add:
            item.setSelected(not item.isSelected())
        elif item.isSelected() and len(self.selected_rows())==1:
            # Clicking the same highlighted line toggles it off.
            self.order.clearSelection()
            self.status.setText('Line selection cleared.')
            return
        else:
            self.order.clearSelection(); item.setSelected(True)
        if not item.isSelected():
            return  # Ctrl+click deselected it; do not reselect.
        self.order.setCurrentRow(index,QItemSelectionModel.SelectionFlag.NoUpdate)
        if self.lines_toggle.isChecked():
            self.order.scrollToItem(item)
            self.show_line_tools()
        self.status.setText(f'Selected: {self.drawing.strokes[index].name}  •  Delete, Reverse, pace and pause '
                            'are under LINES & ORDER on the left; drag in the list to reorder.')

    def show_line_tools(self):
        """Scroll the Source panel so the line list and its buttons are visible."""
        from PySide6.QtWidgets import QScrollArea
        # Selecting on the canvas must not open a hidden advanced panel.
        if not self.lines_toggle.isChecked():
            return
        parent=self.order.parentWidget()
        while parent is not None and not isinstance(parent,QScrollArea):
            parent=parent.parentWidget()
        if parent is not None:
            parent.ensureWidgetVisible(self.line_pause,0,40)
            parent.ensureWidgetVisible(self.order,0,10)

    def change_lines(self,strokes,keep=(),current=None,status=''):
        """Apply an edited stroke list as one undo step."""
        self.drawing.strokes=list(strokes)
        self.fill_order(keep=keep,current=current)
        self.commit_history()
        if status: self.status.setText(status)
        self.refresh()

    def edit_selected(self,**change):
        from history import edited_stroke
        rows=set(self.selected_rows())
        if not rows or not self.drawing: return
        strokes=[edited_stroke(s,**change) if i in rows else s for i,s in enumerate(self.drawing.strokes)]
        keep={id(strokes[i]) for i in rows}
        self.drawing.strokes=strokes
        self.fill_order(keep=keep,current=min(rows))

    def reverse_lines(self):
        if not self.selected_rows(): return
        self.edit_selected(reverse=True); self.commit_history(); self.refresh()

    def set_line_pace(self):
        if not self.selected_rows(): return
        from stroke_timing import pace_value
        self.edit_selected(pace=pace_value(self.line_pace.currentText())); self.commit_history(); self.refresh()

    def set_line_pause(self):
        if not self.selected_rows() or self._restoring: return
        self.edit_selected(pause=self.line_pause.value())
        self.note_change(); self.refresh()

    def delete_lines(self):
        rows=set(self.selected_rows())
        if not rows or not self.drawing: return
        if len(rows)>=len(self.drawing.strokes):
            self.status.setText('At least one line has to stay.'); return
        strokes=[s for i,s in enumerate(self.drawing.strokes) if i not in rows]
        self.change_lines(strokes,current=min(min(rows),len(strokes)-1),
                          status=f'Deleted {len(rows)} line(s). Undo (Ctrl+Z) brings them back.')

    def order_dragged(self):
        """The user dragged lines to a new place in the list."""
        if not self.drawing: return
        strokes=[self.order.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.order.count())]
        if len(strokes)!=len(self.drawing.strokes) or any(s is None for s in strokes): return
        keep={id(s) for s in self.selected_strokes()}
        self.change_lines(strokes,keep=keep,status='New drawing order.')

    def sync_workspace(self,*args):
        image_source=self.is_image_artwork()
        self.load_color_button.setEnabled(bool(self.drawing) and not self._artwork_busy())
        self.load_color_button.setText('Change original image…' if image_source else 'Change matching colors…')
        self.use_color.setEnabled(not image_source and self.final_image is not None)
        # Image sources paint by brush plan only (Adaptive or Zigzag).
        brush_item=self.reveal_mode.model().item(0)
        if brush_item is not None:
            brush_item.setEnabled(not image_source)
        self.reveal_mode.view().setRowHidden(0,image_source)
        if image_source and self.reveal_mode.currentIndex()==0:
            self.reveal_mode.setCurrentIndex(1)
        self.paint_form.setRowVisible(self.image_paint_hint,image_source)
        self.paint_form.setRowVisible(self.color_fade,not image_source)
        self.paint_form.setRowVisible(self.image_duration,image_source)
        self.paint_form.setRowVisible(self.image_animation,image_source)
        paint_only=image_source and self.image_animation.currentIndex()==1
        self.duration.setEnabled(not paint_only)
        self.speed.setEnabled(not paint_only)
        self.reveal_mode.setToolTip('Image sources use Adaptive Hand Painting or Zigzag sweep.'
                                    if image_source else '')
        self.output_summary.setText(f'{self.res.currentText()}  •  {self.fps.value()} fps')
        busy=bool((self.worker and self.worker.isRunning()) or (self.builder and self.builder.isRunning())
                  or getattr(self,'busy',False))
        self.export.setEnabled(bool(self.drawing) and not busy)
        self.quick_export.setEnabled(bool(self.drawing) and not busy)
        self.webm_quality.setEnabled(self.webm.isChecked())
        self.keep_png.setEnabled(self.webm.isChecked() or self.mov.isChecked() or self.mp4.isChecked())
        self.mp4_background.setEnabled(self.mp4.isChecked())
        self.update_transport_icons()

    def show_version_info(self):
        build_file = Path(__file__).resolve().parent / 'BUILD_INFO.txt'
        build = build_file.read_text(encoding='utf-8').strip() if build_file.exists() else 'Source ZIP / local checkout'
        QMessageBox.information(self, 'About StrokeScribe',
            f'{DISPLAY_NAME}\nRelease date: {RELEASE_DATE}\n\nBuild details:\n{build}\n\n'
            'If your title bar shows a different version, you are running an older folder.')

    def number(self,minimum,maximum,value,step):
        w=QDoubleSpinBox(); w.setRange(minimum,maximum); w.setValue(value); w.setSingleStep(step); return w
    def set_drawing(self,drawing):
        if not getattr(self,'_entering_scene',False) and hasattr(self,'project_changes'):
            self.project_changes.mark_changed()
        self.playing=False
        self.drawing=drawing
        self.fill_order()
        self.note.setText('\n'.join(drawing.warnings) or 'Ready. Press Play to draw from the beginning.')
        self.position=0 if getattr(drawing,'source_kind',None)=='image' else 1
        if getattr(self,'scenes',None) and len(self.scenes)>1 and self.all_scenes():
            # Whole video: show this element (finished SVG, or its start for an image).
            try:
                lengths,joins=self.scene_timeline()
                total=max(1e-6,sum(lengths)+sum(joins))
                start=self.element_start()
                at=start if self.position==0 else start+lengths[self.scene_index]*.999
                self.position=max(0.,min(1.,at/total))
            except Exception as exc:
                import applog; applog.error('Whole-video position',exc)
        self.slider.setValue(round(self.position*1000))
        self.update_project_title(self.project_title)
        self.refresh()
        self.reset_history()
        if getattr(self,'scenes',None) and not getattr(self,'_entering_scene',False):
            self.scenes[self.scene_index]['thumb']=None      # new artwork: new thumbnail
            if hasattr(self,'scene_list'): QTimer.singleShot(0,self.fill_scenes)
    def change_source(self,index):
        # This chooses an intake type, never replaces the current element.
        self.image_controls.setVisible(bool(index))
        self.import_button.setText('Import image…' if index else 'Import SVG…')
        self.refresh()

    # ------------------------------------------------------------ projects
    PROJECT_SETTINGS=('duration','speed','thickness','artwork_size','picture_x','picture_y','reveal_mode','blend_mode','artwork_opacity','paper_cleanup','paper_tolerance','paper_softness','color_fade',
                      'image_duration','image_animation','brush_width','stroke_spacing','color_hold',
                      'use_color','preserve_colors','showhand','left_handed','entrance','pause_after','show_paint_hand','handsize','ax','ay',
                      'res','fps','webm','webm_quality','mov','mp4','mp4_background','keep_png',
                      'sound_on','sound_volume','sound_preview','preview_background','image_detail',
                      'image_style','image_animation_style','clean_faint',
                      'erase_mode','erase_time','erase_size','eraser',
                      'camera','audio_volume','audio_offset','pen_ease','paint_hand','paint_hand_size','fast_export','export_layers','clean_color','export_done_sound')

    def project_state(self):
        """Everything needed to reopen this project: the edited scene plus all scenes."""
        from scenes import scenes_to_project
        self.store_scene(thumbnail=False)
        return scenes_to_project(self.scene_state(),self.scenes,self.scene_index)

    def scene_state(self):
        """Everything needed to reopen the scene being edited."""
        from projects import drawing_to_dict, qimage_to_b64, widget_value
        from tools_kit import hand_to_project
        image_source=self.is_image_artwork()
        state={'title':self.project_title,'source':'image' if image_source else 'svg',
               'drawing':drawing_to_dict(self.drawing),
               'settings':self.settings_state(),
               'hand':hand_to_project(getattr(self,'hand_builtin',False),self.hand),
               'letter':{'ink':self.letter_ink_color,'background':self.letter_bg_color},
               'audio':str(self.audio_path or '')}
        if image_source and self.image_result:
            r=self.image_result
            state['image']={'png':qimage_to_b64(r.image),'filename':r.filename,'detail':r.detail,
                            'path':str(self.image_path or ''),'guide':str(self.image_guide or '')}
        else:
            original=getattr(self,'color_original',None)
            keep=original if original is not None else self.final_image
            state['color_png']=None if getattr(self.drawing,'svg_has_fill',False) and not self.color_path else qimage_to_b64(keep)
            state['svg_color_override']=bool(getattr(self,'color_path',None))
        if self.paint_hand_path and Path(self.paint_hand_path).is_file():
            import base64
            state['paint_hand_png']=base64.b64encode(Path(self.paint_hand_path).read_bytes()).decode('ascii')
        metadata=getattr(self.drawing,'artwork_assets',None)
        if metadata:
            state['artwork']=metadata
        if self.overlays:
            import copy
            state['overlays']=copy.deepcopy(self.overlays)
        return state

    def has_unsaved_changes(self):
        """Compare the complete persisted project, not just committed undo edits."""
        if not self.drawing:
            return self.project_changes.is_dirty
        if hasattr(self, 'history_timer') and self.history_timer.isActive():
            self.commit_history()
        return self.project_changes.changed(self.project_state())

    def confirm_leave_project(self, reason='leave this project'):
        """Use one tested decision policy for Save / Discard / Cancel."""
        from project_lifecycle import resolve_project_leave
        import os
        return resolve_project_leave(
            self.has_unsaved_changes(),
            ask=lambda: QMessageBox.question(
                self, 'Unsaved changes',
                'Your StrokeScribe project has unsaved changes.\\n\\nSave before you '+reason+'?',
                QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel),
            save=self.save_project,
            save_choice=QMessageBox.StandardButton.Save,
            discard_choice=QMessageBox.StandardButton.Discard,
            auto_discard=(os.environ.get('STROKESCRIBE_TEST_AUTODISCARD') == '1'
                          and QApplication.platformName() == 'offscreen'))

    def confirm_before_app_update(self):
        """Save before installing source files; cancellation must stop the update."""
        if not self.has_unsaved_changes():
            return True
        box=QMessageBox(self)
        box.setWindowTitle('Save before updating StrokeScribe')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText('Your project has unsaved changes. Save it before installing the update?')
        box.setStandardButtons(QMessageBox.StandardButton.Save |
                               QMessageBox.StandardButton.Discard |
                               QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Save).setText('Save and update')
        box.button(QMessageBox.StandardButton.Discard).setText('Update without saving')
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        choice=box.exec()
        if choice==QMessageBox.StandardButton.Save:
            return bool(self.save_project())
        return choice==QMessageBox.StandardButton.Discard

    def save_project(self,save_as=False):
        if not self.drawing or (self.builder and self.builder.isRunning()):
            QMessageBox.information(self,'Save project','There is no finished drawing to save yet.'); return None
        import projects
        path=getattr(self,'project_path',None)
        if save_as or not path:
            suggested=str(Path(path).parent if path else Path.home())+'/'+ \
                ''.join(c if c.isalnum() or c in ' -_' else '_' for c in self.project_title).strip()+projects.SUFFIX
            path,_=QFileDialog.getSaveFileName(self,'Save project',suggested,'StrokeScribe project (*.strokescribe)')
            if not path: return None
        try:
            state=self.project_state()
            path=projects.save(path,state)
        except Exception as exc:
            QMessageBox.warning(self,'Save project',str(exc)); return None
        self.project_path=str(path)
        self.status.setText('Project saved: '+str(path))
        self.setWindowTitle(f'{Path(path).stem}  •  {DISPLAY_NAME}')
        self.remember_recent(path)
        self.project_changes.mark_saved(state)
        self._autosaved_signature=None
        self._autosaved=self.history.current
        import autosave; autosave.clear()
        return path

    def remember_recent(self,path):
        try:
            import autosave; autosave.add_recent(path)
        except Exception:
            pass

    # ------------------------------------------------------------ autosave
    def autosave_tick(self):
        """Every minute: back up the project if something changed since the last backup."""
        # Qt can deliver an already queued timer event after a close. Never
        # recreate a crash-recovery backup for a window that closed normally.
        if self._closed or not self.drawing or (self.builder and self.builder.isRunning()) or self.busy:
            return False
        try:
            state=self.project_state()
            signature=self.project_changes.signature(state)
            if signature==self.project_changes.saved_signature or signature==self._autosaved_signature:
                return False
            import autosave
            autosave.save(state,getattr(self,'project_path',None),self.project_title)
            self._autosaved_signature=signature
            self._autosaved=self.history.current
            return True
        except Exception as exc:
            import applog; applog.error('Autosave failed',exc)
            self.status.setText('Autosave failed: '+str(exc)[:120])
            return False

    def offer_recovery(self):
        """After a crash: offer the work that was autosaved."""
        import autosave
        info=autosave.pending()
        if not info: return False
        when=datetime.fromtimestamp(float(info.get('time') or 0)).strftime('%H:%M, %d %b')
        name=info.get('title') or 'your project'
        answer=QMessageBox.question(self,'Restore your work?',
            f'StrokeScribe did not close normally last time.\n\nRestore "{name}" as it was at {when}?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:
            # Declining recovery never silently deletes the user's data.
            # Archive it as a normal .strokescribe project, freeing the live
            # autosave slot for new edits in this application session.
            try:
                kept=autosave.archive_pending()
            except Exception as exc:
                QMessageBox.warning(self,'Recovery copy',
                    'The recovery file is still in its original location; it could not be archived: '+str(exc))
                return False
            if kept:
                autosave.clear()
                self.status.setText('Recovery kept for later: '+str(kept))
            return False
        import projects
        try:
            self.apply_project(projects.load(info['path']))
        except Exception as exc:
            QMessageBox.warning(self,'Restore',f'The backup could not be opened: {exc}'); return False
        self.project_path=info.get('project_path') or None
        self.project_changes.mark_changed()
        self.status.setText('Restored your work from the autosave. Save it (Ctrl+S) to keep it.')
        return True

    def open_project(self,path=None):
        if (self.builder and self.builder.isRunning()) or (self.worker and self.worker.isRunning()):
            QMessageBox.information(self,'Open project','Please wait for the current job to finish.'); return False
        import projects
        if path is None:
            path,_=QFileDialog.getOpenFileName(self,'Open project','','StrokeScribe project (*.strokescribe)')
            if not path: return False
        try:
            data=projects.load(path)
        except Exception as exc:
            QMessageBox.warning(self,'Open project',str(exc)); return False
        if not self.confirm_leave_project('open another project'):
            return False
        # Loading can fail after partially changing scene/widget state. Keep a
        # full in-memory snapshot and restore it on failure, rather than leave
        # the user's unsaved work half-replaced.
        previous=self.project_state() if self.drawing is not None else None
        try:
            self.apply_project(data)
        except Exception as exc:
            if previous is not None:
                try:
                    self.apply_project(previous)
                except Exception as recovery_exc:
                    import applog; applog.error('Could not restore failed project load',recovery_exc)
                    import autosave
                    autosave.save(previous,getattr(self,'project_path',None),self.project_title)
            QMessageBox.warning(self,'Open project',str(exc)); return False
        self.project_path=str(path)
        self.setWindowTitle(f'{Path(path).stem}  •  {DISPLAY_NAME}')
        self.status.setText('Opened project: '+str(path))
        self.remember_recent(path)
        self.project_changes.mark_saved(self.project_state())
        self._autosaved_signature=None
        import autosave; autosave.clear()
        self._autosaved=self.history.current
        return True

    def apply_project(self,data):
        """Open project data: its scenes, then the scene that was being edited."""
        from scenes import scenes_from_project
        scene_list=scenes_from_project(data)
        index=max(0,min(len(scene_list)-1,int(data.get('scene_index',0) or 0)))
        main={k:v for k,v in data.items() if k not in ('scenes','scene_index')}
        for k,scene in enumerate(scene_list):
            scene['thumb']=None
            if k==index: scene['state']=None          # lives in the editor
        self.scenes=scene_list; self.scene_index=index
        self._scene_cache={}
        self.apply_scene_state(main)
        self.fill_scenes()

    def apply_scene_state(self,data):
        from projects import drawing_from_dict, qimage_from_b64, set_widget_value
        self.playing=False
        import copy
        self.overlays=copy.deepcopy(data.get('overlays') or [])
        self.selected_overlay=None
        drawing=drawing_from_dict(data['drawing'])
        metadata=data.get('artwork') or getattr(drawing,'artwork_assets',None)
        managed=None
        if metadata:
            from artwork_assets import validate_assets,materialize_assets
            drawing.artwork_assets=validate_assets(metadata)
            managed=materialize_assets(drawing.artwork_assets)
        settings=dict({'artwork_opacity':100,'paper_cleanup':False,
                       'paper_tolerance':24,'paper_softness':12},**(data.get('settings',{}) or {}))
        # Settings first (without a refresh storm), then the drawing.
        for name in self.PROJECT_SETTINGS:
            widget=getattr(self,name,None)
            if widget is None or name not in settings: continue
            widget.blockSignals(True)
            set_widget_value(widget,settings[name])
            widget.blockSignals(False)
        self.canvas.set_background(self.preview_background.currentIndex())
        import tools_kit
        image,builtin=tools_kit.hand_from_project(data.get('hand'))
        if builtin=='hand': self.use_builtin_hand(refresh=False)
        elif image is not None:
            self.hand=image; self.hand_builtin=builtin or False; self.hand_path=None
            self.hand_name.setText('Hand: '+(tools_kit.LABELS[builtin] if builtin else 'from project'))
        self.paint_hand_path=tools_kit.restore_paint_hand(settings.get('paint_hand_path'),data.get('paint_hand_png'))
        self.paint_hand_tip=settings.get('paint_hand_tip')
        self.update_paint_hand_label()
        for key in self.sound_files:
            path=settings.get(key)
            self.sound_files[key]=path if path and Path(path).is_file() else None
        self.update_sound_buttons()
        letter=data.get('letter',{})
        self.letter_ink_color=letter.get('ink',self.letter_ink_color)
        self.background_color=settings.get('background_color') or getattr(self,'background_color',None)
        old_bg=letter.get('background')
        self.letter_bg_color=None                 # one Background for all now (top of the preview)
        if old_bg and self.preview_background.currentIndex()==0:
            self.background_color=old_bg          # an older lettering project: keep its background
            self.preview_background.blockSignals(True)
            self.preview_background.setCurrentIndex(self.preview_background.count()-1)
            self.preview_background.blockSignals(False)
        self.show_background()
        if data.get('source')=='image' and data.get('image'):
            from image_reconstruct import Reconstruction
            from image_regions import segment_regions
            from adaptive_hand import pil_image
            info=data['image']
            image=qimage_from_b64(info['png'])
            if image is None: raise ValueError('The project image is damaged.')
            detail=info.get('detail','medium')
            regions=segment_regions(pil_image(image),'high' if detail=='max' else detail)
            drawing.image_regions=regions
            self.color_path=None;self.color_original=None;self.final_image=None
            self.image_result=Reconstruction(drawing,image,regions,'line_art',detail,info.get('filename','image'))
            self.image_path=managed[0] if managed else info.get('path') or None
            self.image_guide=managed[1] if managed else info.get('guide') or None
            self.source_type.blockSignals(True); self.source_type.setCurrentIndex(1); self.source_type.blockSignals(False)
            self.image_controls.show(); self.import_button.setText('Import image…')
            self.color_note.setText(self.image_result.filename+' • original colors')
        else:
            self.image_result=None;self.image_path=None;self.image_guide=None
            self.source_type.blockSignals(True); self.source_type.setCurrentIndex(0); self.source_type.blockSignals(False)
            self.image_controls.hide(); self.import_button.setText('Import SVG…')
            # The colour picture as saved; cleaned like a newly loaded PNG (an older
            # project may have kept a painted checkerboard or faint leftovers).
            self.color_path='from-project' if data.get('svg_color_override') else None
            self.color_original=qimage_from_b64(data.get('color_png'))
            self.final_image=self.color_original
            if self.final_image is not None and (data.get('settings') or {}).get('clean_color',True):
                try:
                    from color_reveal import clean_qimage
                    self.final_image=clean_qimage(self.final_image)
                except Exception:
                    self.final_image=self.color_original
            if getattr(drawing,'svg_source',None) and getattr(drawing,'svg_has_fill',False) and not data.get('color_png'):
                from svg_appearance import render_appearance
                self.final_image=render_appearance(drawing)
                self.color_original=self.final_image
            self.use_color.setEnabled(self.final_image is not None)
            if self.final_image is None:
                self.use_color.blockSignals(True); self.use_color.setChecked(False); self.use_color.blockSignals(False)
            self.color_note.setText('Colour image from project' if self.final_image is not None else 'No original PNG loaded')
        self.project_title=data.get('title') or 'Project'
        audio=data.get('audio') or None
        if audio and not Path(audio).is_file():
            self.status.setText('The project audio track was not found: '+audio); audio=None
        self.set_audio(audio,refresh=False)
        self.set_drawing(drawing)
        self.update_source_labels()

    # ------------------------------------------------------------ scenes
    def edit_element(self,k):
        """The element's own settings window (Set / Cancel)."""
        if not self.drawing or not 0<=k<len(self.scenes): return
        if self.builder and self.builder.isRunning(): return
        if k!=self.scene_index:
            self.select_scene(k)
            if k!=self.scene_index: return
        self.playing=False
        from element_dialog import ElementDialog
        ElementDialog(self,k).exec()

    def element_times(self,k):
        """(seconds on screen, seconds of the camera move after it) of element k, from its settings."""
        try:
            s=self.settings_state() if k==self.scene_index else dict((self.scenes[k]['state'] or {}).get('settings',{}))
            image=self.is_image_artwork() if k==self.scene_index else \
                  ((self.scenes[k]['state'] or {}).get('source')=='image')
            paint_only=image and s.get('image_animation')=='Paint Only'
            colour=(bool(s.get('preserve_colors',True)) and s.get('image_animation')!='Drawing only') if image else bool(s.get('use_color'))
            length=0. if paint_only else float(s.get('duration',4))/max(.01,float(s.get('speed',1)))
            if colour or paint_only:
                length+=float(s.get('image_duration',8) if image else s.get('color_fade',.4))
                length+=float(s.get('color_hold',.6))
            length+=float(s.get('pause_after',0) or 0)
            if (s.get('erase_mode') or 'Off')!='Off':
                length+=float(s.get('erase_time',3))
            from scenes import transition_seconds
            scene=self.scenes[k]
            move=transition_seconds(scene['transition'],scene['transition_seconds'],k==len(self.scenes)-1)
            return length,move
        except Exception:
            return 0.,0.

    def scene_label(self,k):
        scene=self.scenes[k]
        if scene.get('name'): return scene['name']
        state=scene.get('state')
        title=self.project_title if state is None else state.get('title')
        return title or f'Element {k+1}'

    def store_scene(self,thumbnail=True):
        """Keep the edited scene's state (and a fresh thumbnail) in the scene list."""
        if not self.drawing or not 0<=self.scene_index<len(self.scenes): return
        scene=self.scenes[self.scene_index]
        scene['name']=scene.get('name') or None
        if thumbnail:
            try:
                from scenes import thumbnail as make_thumb
                scene['thumb']=make_thumb(self.drawing,self.options())
            except Exception:
                scene['thumb']=None

    def fill_scenes(self):
        """Rebuild the scene strip; ignore deferred calls after window close."""
        if getattr(self,'_closed',False):
            return
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtGui import QIcon, QPixmap
        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        if not self.drawing:
            self.scene_list.blockSignals(False)
            return
        for k,scene in enumerate(self.scenes):
            if k==self.scene_index and self.drawing is not None and scene.get('thumb') is None:
                self.store_scene()
            # "+": drawn over pictures of earlier scenes (same page, or a frame on top of them).
            length,move=self.element_times(k)
            times=f'⏱ {length:.1f}s'+(f'  ➜ {move:.1f}s' if move else '')
            item=QListWidgetItem(f'{k+1} {"+" if self.drawn_over(k) else "·"} {self.scene_label(k)}'[:20]+'\n'+times)
            thumb=scene.get('thumb')
            if thumb is not None and not thumb.isNull():
                from PySide6.QtGui import QImage, QPainter
                card=QImage(thumb.size(),QImage.Format.Format_ARGB32_Premultiplied)
                card.fill(QColor('white'))
                painter=QPainter(card); painter.drawImage(0,0,thumb); painter.end()
                item.setIcon(QIcon(QPixmap.fromImage(card)))
            item.setToolTip(f'Scene {k+1}: {self.scene_label(k)}')
            self.scene_list.addItem(item)
        self.scene_list.setCurrentRow(self.scene_index)
        self.scene_list.blockSignals(False)
        many=len(self.scenes)>1
        last=self.scene_index==len(self.scenes)-1
        self.scene_delete.setEnabled(many)
        self.scene_left.setEnabled(self.scene_index>0)
        self.scene_right.setEnabled(not last)
        scene=self.scenes[self.scene_index]
        for widget,value in ((self.scene_transition,scene['transition']),
                             (self.scene_transition_time,scene['transition_seconds'])):
            widget.blockSignals(True)
            if widget is self.scene_transition: widget.setCurrentText(value)
            else: widget.setValue(value)
            widget.blockSignals(False)
        # After the last scene only "Show everything" does something (zoom out to the whole board).
        self.scene_transition.setEnabled(True)
        self.scene_transition.setToolTip('After the last scene: "Show everything" zooms out to the whole board.'
                                         if last else 'How the camera goes from this scene to the next one.')
        self.scene_transition_time.setEnabled(scene['transition']=='Show everything' if last
                                              else scene['transition'] not in ('Cut','Same page'))
        self.preview_scope.setEnabled(many)
        if not many and self.preview_scope.currentIndex():
            self.preview_scope.blockSignals(True); self.preview_scope.setCurrentIndex(0); self.preview_scope.blockSignals(False)
        self.export_all_scenes.setEnabled(many)
        self.export_all_scenes.setText(f'Export all {len(self.scenes)} elements as one video' if many
                                       else 'Export all scenes as one video')

    def _leave_scene(self):
        """Save the edited scene into the list before editing another one."""
        self.store_scene()
        self.scenes[self.scene_index]['state']=self.scene_state()
        self._scene_cache.pop(id(self.scenes[self.scene_index]['state']),None)

    def _enter_scene(self,k):
        import applog
        k=max(0,min(int(k),len(self.scenes)-1))
        state=self.scenes[k]['state']
        previous=self.scene_index
        # The scene number changes BEFORE loading: while it loads, the timeline and the
        # board already ask for "the current scene" (after a delete, the old number may
        # not exist any more).
        self.scene_index=k
        self._entering_scene=True                  # loading a scene is not new artwork
        try:
            if state is not None:
                self.apply_scene_state(state)
        except Exception as exc:
            applog.error(f'Scene {k+1} could not be opened',exc)
            if 0<=previous<len(self.scenes) and self.scenes[previous]['state'] is None and previous!=k:
                self.scene_index=previous            # stay on the scene being edited
                self.fill_scenes(); return
            QMessageBox.warning(self,'Scene',f'Scene {k+1} could not be opened: {exc}')
        finally:
            self._entering_scene=False
        applog.info('Editing element %d of %d',k+1,len(self.scenes))
        self.scenes[k]['state']=None              # lives in the editor now
        self._scene_cache={key:v for key,v in self._scene_cache.items()
                           if any(id(s['state'])==key for s in self.scenes)}
        self.fill_scenes()
        self.refresh()

    def select_scene(self,row):
        if row<0 or row==self.scene_index or row>=len(self.scenes): return
        if (self.builder and self.builder.isRunning()) or not self.drawing:
            self.fill_scenes(); return
        self.playing=False
        self._leave_scene()
        self._enter_scene(row)
        if self.all_scenes():
            # Whole video: the playhead jumps to where this element ends (finished).
            try:
                lengths,joins=self.scene_timeline()
                total=max(1e-6,sum(lengths)+sum(joins))
                self.position=max(0.,min(1.,(self.element_start()+lengths[row]*.999)/total))
                self.slider.blockSignals(True); self.slider.setValue(round(self.position*1000)); self.slider.blockSignals(False)
                self.refresh()
            except Exception as exc:
                import applog; applog.error('Whole-video position',exc)
        self.status.setText(f'Editing element {row+1} of {len(self.scenes)}: {self.scene_label(row)}')

    def add_scene(self):
        """A new scene after the current one (starts as a copy; import its own artwork)."""
        if not self.drawing or (self.builder and self.builder.isRunning()): return
        import copy, applog
        applog.info('Adding a scene after scene %d',self.scene_index+1)
        self.playing=False
        self._leave_scene()
        current=self.scenes[self.scene_index]
        new=dict(state=copy.deepcopy(current['state']),transition=current['transition'],
                 transition_seconds=current['transition_seconds'],name=f'Element {len(self.scenes)+1}',
                 thumb=current.get('thumb'))
        self.scenes.insert(self.scene_index+1,new)
        self.project_changes.mark_changed()
        self._enter_scene(self.scene_index+1)
        self.status.setText(f'Scene {self.scene_index+1} added as a copy. Import an SVG or image for it '
                            '(Import, Library or Create image); its settings are its own.')

    def add_element_menu(self,same_spot=False,button=None):
        """'+ Add element' / '+ Same spot': what the new element is (like VideoScribe, it
        does not start as a copy of the one before)."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QCursor
        if not self.drawing or (self.builder and self.builder.isRunning()): return
        menu=QMenu(self)
        menu.addAction('Picture or SVG file…',lambda: self.new_element('file',same_spot))
        menu.addAction('Text (handwriting)…',lambda: self.new_element('text',same_spot))
        menu.addAction('From the Library…',lambda: self.new_element('library',same_spot))
        menu.addAction('Create an image with AI…',lambda: self.new_element('ai',same_spot))
        menu.addSeparator()
        menu.addAction('Copy of this element',lambda: self.new_element('copy',same_spot))
        where=button.mapToGlobal(button.rect().bottomLeft()) if button is not None else QCursor.pos()
        menu.exec(where)

    def new_element(self,how,same_spot=False,path=None,text=None,item=None):
        """Acquire first, then send the complete result through Add placement."""
        from PySide6.QtWidgets import QInputDialog
        if self._artwork_busy(): return False
        if how=='file':
            if path is None:
                path,_=QFileDialog.getOpenFileName(self,'New element: choose artwork','',
                                'Pictures and SVG (*.svg *.png *.jpg *.jpeg *.webp *.bmp)')
            if not path: return False
            return self.request_artwork(path,kind='svg' if str(path).lower().endswith('.svg') else 'image',
                                        placement='add',same_spot=same_spot,whole_preview=True)
        if how=='library':
            if item is None:
                from library_dialog import LibraryDialog
                chosen=[]
                LibraryDialog(self,'images',lambda category,it:chosen.append(it)).exec()
                if not chosen:return False
                item=chosen[-1]
            return self.use_library_item('images',item,as_element=True,same_spot=same_spot)
        if how=='ai':
            if path is None:
                from create_image_dialog import CreateImageDialog
                import ai_engine
                if self.ai_engine is None:self.ai_engine=ai_engine.Engine()
                made=[]
                CreateImageDialog(self,None,lambda kind,p,original=None:made.append((kind,p,original)),
                                  self.ai_engine).exec()
                made=[m for m in made if m[0]!='sound']
                if not made:return False
                kind,path,original=made[-1]
            else:kind,original='image',None
            return self.use_ai_result(kind,path,original,as_element=True,same_spot=same_spot)
        if how=='text':
            if text is None:
                text,ok=QInputDialog.getMultiLineText(self,'New element: text','Text to write by hand:','')
                if not ok or not text.strip():return False
            if self.drawing:(self.add_picture if same_spot else self.add_scene)()
            self.scenes[self.scene_index]['name']=text.strip().splitlines()[0][:30]
            self.text.setPlainText(text);self.letter()
        elif how=='copy' and self.drawing:
            (self.add_picture if same_spot else self.add_scene)()
        else:return False
        if len(self.scenes)>1 and self.preview_scope.currentIndex()==0:
            self.preview_scope.setCurrentIndex(1)
        self.store_scene();self.fill_scenes()
        return True

    def page_members(self,k=None):
        """The elements drawn on the same page as element k (joined by 'Same page')."""
        k=self.scene_index if k is None else k
        first=k
        while first>0 and self.scenes[first-1]['transition']=='Same page': first-=1
        last=k
        while last<len(self.scenes)-1 and self.scenes[last]['transition']=='Same page': last+=1
        return list(range(first,last+1))

    def page_occupancy(self,members,width=160):
        """Where the page already has pictures: a bool mask (rows x cols) of the frame."""
        import numpy as np
        from scenes import thumbnail
        height=max(2,round(width*self.board_aspect()))
        used=np.zeros((height,width),bool)
        for k in members:
            try:
                if k==self.scene_index and self.drawing is not None:
                    drawing,options=self.drawing,self.options()
                else:
                    drawing,options,_,_=self.preview_scene(k,width,height)
                options=dict(options,background=False,overlays=[],layers='all')
                image=thumbnail(drawing,options,width).convertToFormat(QImage.Format.Format_RGBA8888)
                a=np.frombuffer(bytes(image.constBits()),np.uint8).reshape(image.height(),image.bytesPerLine())
                a=a[:,3::4][:,:image.width()]>24
                if a.shape!=used.shape:
                    import cv2
                    a=cv2.resize(a.astype(np.uint8),(width,height),interpolation=cv2.INTER_NEAREST).astype(bool)
                used|=a
            except Exception as exc:
                import applog; applog.error('Page layout',exc)
        return used

    @staticmethod
    def free_spot(used,sizes=(.6,.55,.5,.42,.34)):
        """(artwork size, x %, y %) of the biggest free place on the page, in reading
        order (top-left first), or None when the page is full."""
        import numpy as np, cv2
        h,w=used.shape
        # A little air around what is already there.
        grow=max(1,round(w*.025))
        busy=cv2.dilate(used.astype(np.uint8),np.ones((2*grow+1,2*grow+1),np.uint8))>0
        total=np.pad(busy.astype(np.int32).cumsum(0).cumsum(1),((1,0),(1,0)))
        def area(x0,y0,x1,y1):
            return total[y1,x1]-total[y0,x1]-total[y1,x0]+total[y0,x0]
        margin=.03
        # How far each free point is from the pictures: a new one goes in the middle
        # of a free area, not squeezed into a corner of it.
        room=cv2.distanceTransform(np.pad((~busy).astype(np.uint8),1),cv2.DIST_L2,3)[1:-1,1:-1]
        room_sum=np.pad(room.cumsum(0).cumsum(1),((1,0),(1,0)))
        def space(x0,y0,x1,y1):
            return room_sum[y1,x1]-room_sum[y0,x1]-room_sum[y1,x0]+room_sum[y0,x0]
        for size in sizes:
            bw,bh=round(.82*size*w),round(.78*size*h)
            if bw<4 or bh<4: continue
            best=None
            step=max(1,round(w*.0125))
            for y0 in range(round(margin*h),h-round(margin*h)-bh+1,step):
                for x0 in range(round(margin*w),w-round(margin*w)-bw+1,step):
                    if area(x0,y0,x0+bw,y0+bh)<=bw*bh*.002:
                        # Most room around the whole box first; then reading order.
                        key=(-round(float(space(x0,y0,x0+bw,y0+bh))/(bw*bh)*4),round(y0/max(1.,h*.2)),x0)
                        if best is None or key<best[0]:
                            best=(key,(x0,y0))
            if best:
                best=best[1]
                cx,cy=(best[0]+bw/2)/w,(best[1]+bh/2)/h
                return size*100,round((cx-.5)*100,1),round((cy-.5)*100,1)
        return None

    def add_picture(self):
        """Another picture on the same page (like VideoScribe): it goes to the biggest
        free place on the page; when the page is full, to a new page (the camera moves).
        Returns True on the same page, False on a new page."""
        if not self.drawing or (self.builder and self.builder.isRunning()): return None
        import copy
        self.playing=False
        self.store_scene(thumbnail=False)
        members=self.page_members()
        spot=self.free_spot(self.page_occupancy(members))
        if spot is None and members==[self.scene_index] and self.artwork_size.value()>60:
            # One big picture on the page: it moves to the left half to make room.
            self.artwork_size.setValue(55.); self.picture_x.setValue(-22.); self.picture_y.setValue(0.)
            self.store_scene(thumbnail=False)
            spot=self.free_spot(self.page_occupancy(members))
        if spot is None:
            # The page is full: like VideoScribe, the camera moves on to a new place.
            self.add_scene()
            self.status.setText('This page is full, so the new picture goes on a new page: the camera moves there. '
                                'Make pictures smaller (Artwork size) to fit more on one page.')
            return False
        self._leave_scene()
        current=self.scenes[self.scene_index]
        state=copy.deepcopy(current['state'])
        settings=state.setdefault('settings',{})
        settings['artwork_size'],settings['picture_x'],settings['picture_y']=spot
        if 'erase_mode' in settings: settings['erase_mode']='Off'   # the page stays until it is finished
        new=dict(state=state,transition=current['transition'],transition_seconds=current['transition_seconds'],
                 name=f'Picture {self.scene_index+2}',thumb=None)
        current['transition']='Same page'
        self.scenes.insert(self.scene_index+1,new)
        self._base_cache=OrderedDict()
        self._enter_scene(self.scene_index+1)
        self.status.setText('Picture added in a free place on the same page. Drag it on the preview to move it; '
                            'Artwork size makes it bigger or smaller. When the page is full, the next one goes to a new page.')
        return True

    def delete_scene(self):
        if len(self.scenes)<2: return
        answer=QMessageBox.question(self,'Delete element',
            f'Delete element {self.scene_index+1} ({self.scene_label(self.scene_index)})?')
        if answer!=QMessageBox.StandardButton.Yes: return
        self.playing=False
        removed=self.scene_index
        import applog
        applog.info('Deleting scene %d of %d',removed+1,len(self.scenes))
        del self.scenes[removed]
        self._scene_cache={}; self._base_cache=OrderedDict()
        self._enter_scene(min(removed,len(self.scenes)-1))
        self.status.setText(f'Scene {removed+1} deleted.')

    def move_scene(self,direction):
        k=self.scene_index; j=k+direction
        if not 0<=j<len(self.scenes): return
        self.scenes[k],self.scenes[j]=self.scenes[j],self.scenes[k]
        self.scene_index=j
        self.fill_scenes(); self.refresh()

    def scene_transition_changed(self):
        scene=self.scenes[self.scene_index]
        scene['transition']=self.scene_transition.currentText()
        scene['transition_seconds']=self.scene_transition_time.value()
        last=self.scene_index==len(self.scenes)-1
        self.scene_transition_time.setEnabled(scene['transition']=='Show everything' if last
                                              else scene['transition'] not in ('Cut','Same page'))
        self._base_cache=OrderedDict()
        self.fill_scenes()
        self.refresh()

    def all_scenes(self):
        return self.preview_scope.currentIndex()==1 and len(self.scenes)>1

    def board_mode(self):
        """Preview → Board: the whole board from above, to arrange the scenes' frames."""
        return self.preview_scope.currentIndex()==2 and len(self.scenes)>1

    def preview_scope_changed(self):
        self.playing=False
        if self.preview_sound is not None: self.preview_sound.stop()
        if hasattr(self,'board_arrange'): self.board_arrange.setVisible(self.board_mode())
        if self.board_mode():
            self.status.setText('Board: drag a frame to move it, mouse wheel on a frame to make it bigger or '
                                'smaller, double-click to edit that scene. A frame inside another one: the '
                                'camera zooms in to draw there.')
            self.order.clearSelection()
        elif self.all_scenes():
            self.status.setText('Previewing all scenes (no sound in this preview; the export has it). '
                                'Lines can be clicked again in "This scene" preview.')
            self.order.clearSelection()
        self.refresh()

    def preview_scene(self,k,width,height):
        """(drawing, options, seconds, camera) of scene k for the preview, at preview size."""
        from scenes import job_from_state, seconds_of
        over=self.drawn_over(k)
        if k==self.scene_index:
            # Asked for every frame of the whole video: made once per change, not per frame.
            memo=self.__dict__.setdefault('_memo',{})
            key=('scene',width,height,over,self._view_token())
            if key in memo: return memo[key]
            options=self.options(); options.pop('fps',None)
            if over: options['background']=False
            options['hand_scale']/=options['artwork_scale']
            options['width'],options['height']=width,height
            options['ghost']=.22
            memo[key]=(self.drawing,options,seconds_of(self.drawing,options),self.preview_camera(options))
            return memo[key]
        state=self.scenes[k]['state']
        key=(id(state),width,height,over)
        cached=self._scene_cache.get(id(state))
        if cached is None or cached[0]!=key:
            drawing,options,_=job_from_state(state,self.hand)
            options.pop('fps',None); options.pop('audio',None)
            if over: options['background']=False
            options['hand_scale']/=options['artwork_scale']
            options['width'],options['height']=width,height
            options['ghost']=.22
            camera=None
            if options.get('camera_zoom',1.)>1.0001:
                from frame_render import camera_for
                camera=camera_for(drawing,options,options['camera_zoom'],rate=20.)
            if options.get('final_image') is not None and options.get('reveal_mode') in ('adaptive','zigzag','rows','columns','short_zigzag'):
                from adaptive_hand import plan_ready, plan_for
                drawing.paint_method=options['reveal_mode']
                if not plan_ready(drawing,options['final_image'],options['brush_width'],options['stroke_spacing']):
                    self._preparing=True
                    try:
                        self.show_busy_now(f'Preparing scene {k+1}','Planning how the hand paints the colours…')
                        plan_for(drawing,options['final_image'],options['brush_width'],options['stroke_spacing'])
                    finally:
                        self._preparing=False
                        self.clear_busy()
            cached=(key,(drawing,options,seconds_of(drawing,options),camera))
            self._scene_cache[id(state)]=cached
        return cached[1]

    # ------------------------------------------------------------ the board
    def board_aspect(self):
        try:
            w,h=[int(x.strip()) for x in self.res.currentText().split('×')]
            return h/w
        except Exception:
            return 9/16

    def board_frames(self):
        """(cx, cy, w) of every scene on the board."""
        import board
        return board.frames(self.scenes,self.board_aspect())

    def drawn_over(self,k):
        """True when pictures of earlier scenes can be seen in scene k's frame."""
        import board
        if k<=0 or len(self.scenes)<2 or k>=len(self.scenes): return False
        return board.has_base(self.board_frames(),k,self.board_aspect())

    def edited_key(self):
        """Changes whenever the scene being edited would look different when finished."""
        settings=self.settings_state()
        return ('edit',self.scene_index,id(self.drawing),len(getattr(self.drawing,'strokes',()) or ()),
                id(self.final_image),hash(repr(sorted((k,repr(v)) for k,v in settings.items()))))

    def preview_world(self,width,height):
        """The board for the preview: every scene, drawn sharp at any camera zoom."""
        import board
        memo=self.__dict__.setdefault('_memo',{})
        mkey=('world',width,height,self._view_token(),
              tuple((s['transition'],repr(s.get('board'))) for s in self.scenes))
        if mkey in memo: return memo[mkey]
        items=[]
        for k,frame in enumerate(self.board_frames()):
            drawing,options,_,_=self.preview_scene(k,width,height)
            key=self.edited_key() if k==self.scene_index else ('scene',id(self.scenes[k]['state']))
            items.append(dict(drawing=drawing,options=options,frame=frame,key=key))
        cache=self.__dict__.setdefault('_world_cache',OrderedDict())
        memo[mkey]=board.World(items,height/width,cache)
        return memo[mkey]

    BOARD_WIDTH=1280

    def show_board(self):
        """Draw the board view: every finished scene in its frame, frame outlines and numbers."""
        import board
        from PySide6.QtCore import QRectF, QPointF
        from PySide6.QtGui import QPainter, QPen, QFont, QPainterPath
        import theme
        c=theme.colors()
        self.sync_workspace()
        aspect=self.board_aspect()
        W=self.BOARD_WIDTH; H=round(W*aspect)
        try:
            world=self.preview_world(960,round(960*aspect))
        except Exception as exc:
            import applog; applog.error('Board could not be drawn',exc)
            self.status.setText('Board could not be drawn: '+str(exc)[:200]); return
        frames=world.frames
        view=getattr(self,'_board_view',None) if getattr(self,'_board_drag',None) else None
        if view is None:
            view=board.bounds(frames,aspect,margin=.12)
        self._board_map=(view,W,H)
        image=world.view(view,W,H,upto=len(frames))
        p=QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Camera path: from one frame to the next.
        centres=[world.place(f,view,W,H) for f in frames]
        path=QPainterPath()
        for n,(x,y,w,h) in enumerate(centres):
            point=QPointF(x+w/2,y+h/2)
            path.moveTo(point) if n==0 else path.lineTo(point)
        p.setPen(QPen(QColor(c['accent']),2,Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        font=QFont(self.font()); font.setBold(True); font.setPointSizeF(9.5); p.setFont(font)
        for n,(x,y,w,h) in enumerate(centres):
            current=n==self.scene_index
            p.setPen(QPen(QColor(c['accent'] if current else c['muted']),3 if current else 1.6,
                          Qt.PenStyle.SolidLine if current else Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(x,y,w,h),6,6)
            label=f' {n+1} · {self.scene_label(n)} '[:26]
            tw=p.fontMetrics().horizontalAdvance(label)+8
            badge=QRectF(x+6,y+6,tw,22)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['accent'] if current else '#444A55'))
            p.drawRoundedRect(badge,11,11)
            p.setPen(QColor('white')); p.drawText(badge,Qt.AlignmentFlag.AlignCenter,label)
        # What the Board is for, on the board itself.
        hint=('BOARD: every element on one big page, seen from above. The camera flies along the dashed '
              'line.   Drag a frame to move it  •  mouse wheel on a frame: bigger / smaller (the camera '
              'zooms)  •  double-click: edit it')
        small=QFont(self.font()); small.setPointSizeF(9.); p.setFont(small)
        box=QRectF(10,H-40,W-20,30)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(20,22,30,215)); p.drawRoundedRect(box,10,10)
        p.setPen(QColor('white'))
        p.drawText(box.adjusted(12,0,-12,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(hint,Qt.TextElideMode.ElideRight,int(box.width()-24)))
        p.end()
        self.canvas.frame=image; self.canvas.highlight=[]; self.canvas.update()
        segments,lengths,joins=self.whole_segments(960,round(960*aspect))
        self.show_whole_timeline(segments,lengths,joins,self.options())
        total=sum(lengths)+sum(joins)
        self.clock.setText(timecode(self.position*total)); self.clock_total.setText(timecode(total))

    def board_point(self,x,y):
        """Board (world) point under a pixel of the board view."""
        view,W,H=self._board_map
        vx,vy,vw=view
        return vx-vw/2+x*vw/W, vy-vw*H/W/2+y*vw/W

    def board_pick(self,x,y):
        """The scene whose frame is under (x, y) of the board view: the smallest one (frames
        inside frames), or None."""
        import board
        if not getattr(self,'_board_map',None): return None
        wx,wy=self.board_point(x,y)
        aspect=self.board_aspect()
        hits=[(f[2],k) for k,f in enumerate(self.board_frames())
              if board.rect(f,aspect)[0]<=wx<=board.rect(f,aspect)[2] and board.rect(f,aspect)[1]<=wy<=board.rect(f,aspect)[3]]
        return min(hits)[1] if hits else None

    def pin_board(self):
        """Give every scene its own fixed frame (before the first move on the board), so moving one
        frame does not move the scenes placed after it."""
        for scene,(cx,cy,w) in zip(self.scenes,self.board_frames()):
            if not scene.get('board'): scene['board']=dict(cx=cx,cy=cy,w=w)

    def arrange_board(self):
        """Forget the moved frames: every scene next to the one before it again."""
        for scene in self.scenes: scene.pop('board',None)
        self._base_cache=OrderedDict()
        self.fill_scenes(); self.refresh()
        self.status.setText('Frames arranged again from the transitions (Camera move: to the right, Pan up: above…).')

    def board_select(self,k):
        if k is None or k==self.scene_index: return
        self.playing=False
        self._leave_scene(); self._enter_scene(k)

    def board_drag(self,kind,dx,dy):
        import board
        if kind=='start':
            k=self.board_pick(dx,dy)
            if k is None: return False
            self.board_select(k)
            self.pin_board()
            b=self.scenes[k]['board']
            self._board_drag=(k,b['cx'],b['cy'])
            self._board_view=self._board_map[0]           # the view stays still while dragging
            return True
        drag=getattr(self,'_board_drag',None)
        if drag is None: return
        k,cx0,cy0=drag
        if kind=='move':
            vw=self._board_view[2]; aspect=self.board_aspect()
            cx,cy=cx0+dx*vw,cy0+dy*vw*aspect
            # Snap to the centre of other frames (to put a picture exactly on another frame).
            for j,f in enumerate(self.board_frames()):
                if j==k: continue
                if abs(cx-f[0])<.015*vw: cx=f[0]
                if abs(cy-f[1])<.015*vw*aspect: cy=f[1]
            self.scenes[k]['board'].update(cx=cx,cy=cy)
            self._base_cache=OrderedDict()
            self.show_board()
        else:
            self._board_drag=None; self._board_view=None
            self.fill_scenes(); self.show_board()
            self.note_change()

    def preview_wheel(self,steps,x,y):
        """Mouse wheel on the preview: resize a frame on the Board, or the overlay under the mouse."""
        if self.board_mode(): return self.board_wheel(steps,x,y)
        if self.all_scenes(): return False
        item=self.overlay_at(x,y)
        if item is None: return False
        item['size']=max(.01,min(3.,float(item.get('size',.3))*(1.08**steps)))
        self.selected_overlay=item['id']
        self.note_change(); self.refresh()
        return True

    def board_wheel(self,steps,x,y):
        k=self.board_pick(x,y)
        if k is None: k=self.scene_index
        self.pin_board()
        b=self.scenes[k]['board']
        b['w']=max(.05,min(20.,b['w']*(1.12**steps)))
        self._base_cache=OrderedDict()
        self.fill_scenes(); self.show_board(); self.note_change()
        self.status.setText(f'Scene {k+1}: frame size {b["w"]*100:.0f}% of a normal scene. '
                            'Smaller frame = the camera zooms in more.')

    def preview_double(self,x,y):
        if self.board_mode(): return self.board_double(x,y)
        if self.all_scenes(): return
        item=self.overlay_at(x,y)
        if item is not None: self.edit_overlay(item['id'])

    def board_double(self,x,y):
        k=self.board_pick(x,y)
        if k is None: return
        self.board_select(k)
        self.preview_scope.setCurrentIndex(1)

    def scene_base(self,k,width,height,fraction=1.,camera=None):
        """What the camera sees of earlier scenes while scene k is drawn (None: nothing)."""
        import board
        if not self.drawn_over(k): return None
        world=self.preview_world(width,height)
        view=world.frames[k]
        if camera is not None:
            view=board.sub_view(view,*camera.at(fraction),world.aspect)
        key=(k,width,height,view,tuple(it['key'] for it in world.items[:k]))
        cache=self.__dict__.setdefault('_base_cache',OrderedDict())
        if key in cache:
            cache.move_to_end(key); return cache[key]
        base=world.view(view,width,height,upto=k)
        cache[key]=base
        while len(cache)>8: cache.popitem(last=False)
        return base

    @staticmethod
    def stage_parts(options):
        """[(stage key, seconds)] of one element: Draw, Paint, Hold (+ pause), Out."""
        colour=options.get('final_image') is not None
        erase=options.get('erase')
        return [('draw',float(options.get('duration',0))),
                ('paint',float(options.get('fade_duration',0)) if colour else 0.),
                ('hold',(float(options.get('hold_duration',0)) if colour else 0.)+float(options.get('pause',0) or 0)),
                ('erase',float(erase['seconds']) if erase else 0.)]

    def whole_segments(self,width=960,height=540):
        """The whole video for the timeline: elements (with their parts) and camera moves."""
        lengths,joins=self.scene_timeline(width,height)
        segments=[]
        for n,(length,join) in enumerate(zip(lengths,joins)):
            parts=self.stage_parts(self.preview_scene(n,width,height)[1])
            whole=sum(v for _,v in parts)
            if whole>0 and abs(whole-length)>1e-3:          # match the real length of the element
                parts=[(key,v*length/whole) for key,v in parts]
            segments.append((f'{n+1} · {self.scene_label(n)}',length,'scene',parts))
            if join>0: segments.append((self.scenes[n]['transition'],join,'join',()))
        return segments,lengths,joins

    def show_whole_timeline(self,segments,lengths,joins,options):
        """Whole video on the timeline; the edited element keeps its edges, pictures and audio."""
        tl=self.stage_timeline
        tl.set_scenes(segments,current=self.scene_index)
        tl.set_overlays(self.overlays,self.selected_overlay)
        tl.set_audio(self.timeline_audio())
        tl.editable={'draw','paint','hold','erase'} if self.duration.isEnabled() else {'paint','hold','erase'}
        mine=dict(self.stage_parts(options))
        length=lengths[self.scene_index]
        whole=sum(mine.values())
        if whole>0 and abs(whole-length)>1e-3:
            mine={k:v*length/whole for k,v in mine.items()}
        tl.update_state(mine['draw'],mine['paint'],mine['hold'],self.position,mine['erase'])

    def element_start(self,k=None):
        """Whole video: the second where element k starts."""
        k=self.scene_index if k is None else k
        lengths,joins=self.scene_timeline()
        return sum(lengths[:k])+sum(joins[:k])

    def timeline_element_clicked(self,k):
        """Whole video: a click on another element's block works on that element (the
        playhead stays where it was clicked)."""
        position=self.position
        self.select_scene(k)
        if self.all_scenes():
            self.position=position
            self.slider.blockSignals(True); self.slider.setValue(round(position*1000)); self.slider.blockSignals(False)
            self.refresh()

    def scene_timeline(self,width=960,height=540):
        """Lengths of all scenes and the moves between them (seconds)."""
        from scenes import transition_seconds
        memo=self.__dict__.setdefault('_memo',{})
        key=('timeline',width,height,self._view_token(),
             tuple((s['transition'],s['transition_seconds']) for s in self.scenes))
        if key in memo: return memo[key]
        lengths=[self.preview_scene(k,width,height)[2] for k in range(len(self.scenes))]
        last=len(self.scenes)-1
        joins=[transition_seconds(s['transition'],s['transition_seconds'],k==last) for k,s in enumerate(self.scenes)]
        memo[key]=(lengths,joins)
        return lengths,joins

    def all_scenes_frame(self,width,height,fraction=None):
        """Preview frame of the whole video at the playhead (or at `fraction`): the camera
        over the board, as in the export."""
        import board
        from frame_render import compose_frame
        from scenes import transition_frame, stack
        lengths,joins=self.scene_timeline(width,height)
        total=sum(lengths)+sum(joins)
        where,k,f=board.locate(lengths,joins,(self.position if fraction is None else fraction)*total)
        if where=='scene':
            drawing,options,_,camera=self.preview_scene(k,width,height)
            frame=compose_frame(drawing,f,options,camera)
            if options.get('layers')=='hand': return frame,k,lengths,joins
            from scenes import composite_element
            # Keeping the normal path byte-for-byte where no artwork effect is set.
            result=composite_element(self.scene_base(k,width,height,f,camera),
                                     drawing,f,options,camera)
            return result,k,lengths,joins
        world=self.preview_world(width,height)
        if self.preview_scene(k,width,height)[1].get('layers')=='hand':
            from PySide6.QtGui import QImage
            blank=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); blank.fill(0)
            return blank,k,lengths,joins
        kind=self.scenes[k]['transition']
        last=k==len(self.scenes)-1
        if kind in board.SCREEN_KINDS and not last:
            a=world.view(world.frames[k],width,height,upto=k+1)
            b=world.view(world.frames[k+1],width,height,upto=k+1)
            return transition_frame(a,b,kind,f),k,lengths,joins
        view=board.join_view(world.frames,k,kind,f,world.aspect,self.scenes[k]['transition_seconds'])
        return world.view(view,width,height,upto=k+1),k,lengths,joins

    def open_batch_export(self):
        from batch_export import BatchExportDialog
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'Batch export','Please wait for the current export to finish.'); return
        BatchExportDialog(self,self.settings_state(),self.hand,
                          play_finished_sound if self.export_done_sound.isChecked() else None).exec()

    # ------------------------------------------------------------ AI images
    def open_create_image(self,task=None):
        from create_image_dialog import CreateImageDialog
        import ai_engine
        if self.ai_engine is None:
            self.ai_engine=ai_engine.Engine()
        current=self.image_path if self.is_image_artwork() else None
        dialog=CreateImageDialog(self,current,self.use_ai_result,self.ai_engine,task=task)
        dialog.exec()

    def use_ai_result(self,kind,path,original=None,as_element=False,placement=None,same_spot=False):
        """Line art: trace it over `original`; image: import it as the image source;
        sound: use it as the pencil/brush/eraser sound (original = which one)."""
        if kind=='sound':
            # Keep a copy in the Library: the engine's output folder is not a safe home.
            import library
            try:
                kept=str(library.Library().add('audio',path).path)
            except Exception:
                kept=str(path)
            self.set_sound_file(original or 'sound_pencil_file',kept)
            self.status.setText('New '+{'sound_pencil_file':'pencil','sound_brush_file':'brush',
                                       'sound_eraser_file':'eraser'}.get(original,'pencil')
                                +' sound in use (saved in the Library → Audio). Press Play to hear it.')
            return
        return self.request_artwork(path,kind=kind,original=original,
                                    placement='add' if as_element else placement,same_spot=same_spot,whole_preview=as_element)

    def use_own_line_drawing(self):
        """Trace a line drawing you already have (black lines on white) over the image."""
        if not self.image_path:
            QMessageBox.information(self,'Line drawing','Import the colour image first.'); return
        name,_=QFileDialog.getOpenFileName(self,'Choose the line drawing of this image','',
                                           'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if name:
            self.build_image(self.image_path,line_guide=name)

    def rebuild_image(self):
        metadata=getattr(self.drawing,'artwork_assets',None)
        if metadata:
            from artwork_assets import materialize_assets
            self.image_path,self.image_guide=materialize_assets(metadata)
        if self.image_path and Path(self.image_path).is_file():
            if self.image_guide and not Path(self.image_guide).is_file():
                QMessageBox.information(self,'Drawing guide unavailable',
                    'The saved drawing and colors still work. Reattach the original guide before rebuilding.')
                return
            self.build_image(self.image_path)
        else:
            QMessageBox.information(self,'Source unavailable',
                'The embedded drawing and colors still work. Reattach the source image to rebuild.')

    def image_stage(self,message,percent,indeterminate):
        self.analysis_stage=message
        if self.busy:
            self.canvas.set_busy('Preparing your drawing',None if indeterminate else int(percent),message+'…')
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

    def build_image(self,path,line_guide=None,intake=None):
        if self.builder and self.builder.isRunning(): return
        self.playing=False
        if intake is None:
            if path!=self.image_path or line_guide is not None:
                self.image_guide=line_guide
            self.image_path=path
        self.builder=ImageBuilder(path,self.image_detail.currentText().lower(),
                                  self.brush_width.value(),self.stroke_spacing.value(),
                                  clean_faint=self.clean_faint.isChecked(),
                                  style=('clean','detailed')[self.image_style.currentIndex()],
                                  animation=('artist','standard')[self.image_animation_style.currentIndex()],
                                  paint_method=self.image_paint_method(),
                                  line_guide=line_guide if intake is not None else self.image_guide)
        self.builder._artwork_request=intake
        if intake is None:
            from artwork_assets import capture_assets
            self.builder._source_assets=capture_assets(path,self.image_guide)
        self.builder.ready.connect(self.image_ready)
        self.builder.failed.connect(self.image_failed)
        self.builder.stage.connect(self.image_stage)
        self.builder.finished.connect(self.image_finished)
        self.analysis_started=time.perf_counter()
        self.analysis_stage='Preparing line art'
        self.progress.setRange(0,100); self.progress.setValue(0)
        self.source_type.setEnabled(False)
        self.import_button.setEnabled(False)
        self.rebuild_button.setEnabled(False)
        self.export.setEnabled(False)
        self.quick_export.setEnabled(False)
        self.update_analysis_elapsed()
        self.analysis_timer.start()
        self.set_busy('Preparing your drawing',0,'Reading the image…')
        self.builder.start()

    def export_svg(self,folder=None):
        """Save the current image drawing as an editable SVG + matching PNG."""
        if not self.image_result or not self.drawing or getattr(self.drawing,'source_kind',None)!='image':
            QMessageBox.information(self,'Export SVG','Import an image first.'); return None
        if folder is None:
            folder=QFileDialog.getExistingDirectory(self,'Choose a folder for the SVG and its colour PNG')
            if not folder: return None
        from svg_export import export_drawing
        from adaptive_hand import pil_image
        stem=Path(self.image_result.filename).stem+'_drawing'
        try:
            svg,png=export_drawing([(s.name,s.points,s.color,s.width) for s in self.drawing.strokes],
                                   pil_image(self.image_result.image),folder,stem)
        except Exception as exc:
            QMessageBox.warning(self,'Export SVG',str(exc)); return None
        self.status.setText(f'Saved {svg.name} and {png.name} in {svg.parent}. '
                            'Edit the SVG in Inkscape, then import it with SVG source + '
                            'Load matching colored PNG.')
        self.status.setWordWrap(True)
        return svg,png
    def image_failed(self,error):
        if (getattr(self.builder,'_artwork_request',None) or {}).get('cancelled'):
            return
        self.status.setText('Image analysis failed: '+str(error)[:140])
        QMessageBox.warning(self,'Image reconstruction',error)

    def image_ready(self,result):
        ctx=getattr(self.builder,'_artwork_request',None)
        if ctx is not None and ctx.get('source_edit'):
            self.accept_drawing_source(result,ctx)
            return
        if ctx is not None:
            self._accept_artwork_result(result,ctx)
            return
        if getattr(self.builder,'_source_assets',None):
            result.drawing.artwork_assets=self.builder._source_assets
            if hasattr(result.drawing,'source_frame'):
                result.drawing.artwork_assets['frame']=result.drawing.source_frame
        self.image_result=result
        self.update_project_title(result.filename)
        self.set_drawing(result.drawing)
        self.color_note.setText(result.filename+' • original colors; adaptive brush reveal')

    def image_finished(self):
        ctx=getattr(self.builder,'_artwork_request',None)
        self._pending_artwork=None
        self.analysis_timer.stop()
        self.clear_busy()
        self.source_type.setEnabled(True)
        self.import_button.setEnabled(True)
        self.rebuild_button.setEnabled(True)
        self.export.setEnabled(self.drawing is not None and not (self.worker and self.worker.isRunning()))
        self.quick_export.setEnabled(self.drawing is not None and not (self.worker and self.worker.isRunning()))
        self.progress.setRange(0,100)
        if self.builder and self.builder.success:
            self.progress.setValue(100)
            times=self.builder.timings
            self.status.setText(
                f'Line art ready ({"Artist layers" if self.builder.animation=="artist" else "Clean drawing" if self.builder.style=="clean" else "Detailed"}, '
                f'{self.builder.detail.title()} detail, {len(self.drawing.strokes)} strokes): '
                f'lines {times.get("lines",0):.1f}s; brush plan {times.get("brush",0):.1f}s.')
        else:
            self.progress.setValue(0)
            message=self.builder.failed_message if self.builder else 'Unknown problem'
            self.status.setText('Image analysis failed: '+str(message)[:140])
        if ctx is not None and not ctx.get('committed'):
            self.status.setText('Import cancelled or not applied; existing artwork kept.')
        self.analysis_stage=''
    def keep_in_library(self,category,path):
        """Copy an imported file into the library (if enabled) and return the path to use."""
        import library
        if not library.load_settings().get('keep_imports',True):
            return path
        try:
            return str(library.Library().add(category,path).path)
        except Exception as exc:
            import applog; applog.error('Could not keep a library copy',exc)
            self.status.setText('Could not keep a library copy: '+str(exc)[:150])
            return path


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
                    # Not downloaded yet: get it now (a small file, with its open license).
                    from font_library import download_google_font
                    self.show_busy_now('Getting the font',f'Downloading {label} from Google Fonts…')
                    try:
                        font_path=download_google_font(label)
                    except Exception as exc:
                        QMessageBox.information(self,'Handwriting font',
                            f'"{label}" could not be downloaded ({exc}). Check the internet connection, '
                            'or import a local TTF/OTF file.')
                        return
                    finally:
                        self.clear_busy()
                drawing=make_font_text(self.text.toPlainText(),font_path,
                                       int(self.font_size.value()))
            drawing.source_kind=getattr(drawing,'source_kind','lettering')
            self.apply_letter_style(drawing)
            # A new text source owns its font appearance; retain the preceding
            # element's image only in its saved scene, never as this text's paint.
            self.image_result=None;self.image_path=None;self.image_guide=None;self.svg_state=None
            self.final_image=None;self.color_original=None;self.color_path=None
            self.use_color.blockSignals(True);self.use_color.setChecked(False);self.use_color.blockSignals(False)
            self.color_note.setText('Lettering • no image painting')
            self.source_type.setCurrentIndex(0)
            self.update_project_title('Lettering — '+self.text.toPlainText()[:16].replace('\n',' '))
            self.set_drawing(drawing)
        except Exception as e: QMessageBox.warning(self,'Lettering',str(e))

    def reletter(self):
        """Letter detail changed: trace the same text again (keeps the playhead)."""
        if getattr(self.drawing,'source_kind',None)!='font' or (self.builder and self.builder.isRunning()):
            return
        if getattr(self.drawing,'font_point',None)==int(self.font_size.value()):
            return                                # already traced at this detail (a project loading)
        position=self.position
        self.letter()
        self.position=position
        self.slider.blockSignals(True); self.slider.setValue(round(position*1000)); self.slider.blockSignals(False)
        self.refresh()

    def font_choice_changed(self):
        """Another font chosen (by the user): the text on screen is written again with it."""
        builtin=self.font_select.currentText().strip() in ('','Built-in single-line pen')
        self.font_size.setEnabled(not builtin)
        if getattr(self.drawing,'source_kind',None) not in ('font','lettering') or not self.text.toPlainText().strip():
            return
        if self.builder and self.builder.isRunning(): return
        position=self.position
        self.letter()
        self.position=position
        self.slider.blockSignals(True); self.slider.setValue(round(position*1000)); self.slider.blockSignals(False)
        self.refresh()

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
        strokes=list(self.drawing.strokes)
        strokes[i],strokes[j]=strokes[j],strokes[i]
        self.change_lines(strokes,keep={id(strokes[j])},current=j)
    def loadhand(self):
        name,_=QFileDialog.getOpenFileName(self,'Hand overlay','','PNG (*.png)')
        if name:
            image=QImage(name)
            if image.isNull(): QMessageBox.warning(self,'Hand','Could not read PNG.'); return
            kept=self.keep_in_library('hands',name)
            self.set_hand(image,Path(name).name,kept)
    def set_hand(self,image,label,path=None,tip=None):
        """Use a hand image; place its pen tip automatically unless one is saved."""
        import library
        self.hand=image; self.hand_builtin=False; self.hand_path=path
        lib_tip=library.Library().tip_for(path) if path else None
        tip=tip or lib_tip
        note='saved pen tip'
        if tip is None:
            from hand_tip import find_tip
            found=find_tip(image)
            if found:
                tip=found[:2]; note='pen tip found automatically'
                if path and lib_tip is None:
                    try:
                        lib=library.Library()
                        item=next((i for i in lib.items('hands') if str(i.path)==str(path)),None)
                        if item: lib.set_tip(item,tip)
                    except Exception:
                        pass
        if tip:
            for box,value in ((self.ax,tip[0]),(self.ay,tip[1])):
                box.blockSignals(True); box.setValue(round(value,3)); box.blockSignals(False)
        self.hand_name.setText(f'Hand: {label}' + (f'  •  {note} (adjust below if needed)' if tip else ''))
        self.refresh()

    def find_pen_tip(self):
        if self.hand is None or self.hand.isNull(): return
        from hand_tip import find_tip
        found=find_tip(self.hand)
        if not found:
            QMessageBox.information(self,'Pen tip','The pen tip could not be found; click it instead.'); return
        self.ax.setValue(round(found[0],3)); self.ay.setValue(round(found[1],3))
        self.remember_tip()

    def pick_pen_tip(self):
        if self.hand is None or self.hand.isNull(): return
        from library_dialog import PenTipDialog
        dialog=PenTipDialog(self,self.hand,(self.ax.value(),self.ay.value()))
        if dialog.exec():
            self.ax.setValue(round(dialog.tip[0],3)); self.ay.setValue(round(dialog.tip[1],3))
            self.remember_tip()

    def remember_tip(self):
        """Store the current pen tip with the hand in the library, if it is there."""
        path=getattr(self,'hand_path',None)
        if not path: return
        try:
            import library
            lib=library.Library()
            item=next((i for i in lib.items('hands') if str(i.path)==str(path)),None)
            if item: lib.set_tip(item,(self.ax.value(),self.ay.value()))
        except Exception:
            pass

    def open_library(self,category='images'):
        from library_dialog import LibraryDialog
        LibraryDialog(self,category,self.use_library_item).exec()

    def use_library_item(self,category,item,as_element=False,placement=None,same_spot=False):
        if category=='audio':
            self.set_audio(str(item.path)); return
        if category=='hands':
            image=QImage(str(item.path))
            if image.isNull():
                QMessageBox.warning(self,'Hand','Could not read this hand image.'); return
            self.set_hand(image,item.name,str(item.path),item.tip)
            return
        path=str(item.path)
        try:
            assets=getattr(item,'artwork',None)
        except Exception as exc:
            QMessageBox.warning(self,'Cannot import artwork','The Library artwork pairing could not be read: '+str(exc))
            return False
        return self.request_artwork(path,kind='svg' if path.lower().endswith('.svg') else 'image',
                                    placement='add' if as_element else placement,name=item.name,
                                    same_spot=same_spot,assets=assets,whole_preview=as_element)

    def use_builtin_tool(self,name):
        """Built-in hand, pencil or marker, with its tip and a fitting size."""
        import tools_kit
        if name=='hand':
            self.use_builtin_hand(refresh=False)
        else:
            image=tools_kit.builtin_image(name)
            if image.isNull(): return
            self.hand=image; self.hand_builtin=name; self.hand_path=None
            self.hand_name.setText('Hand: '+tools_kit.LABELS[name])
        _,tip,size=tools_kit.BUILTIN[name]
        for widget,value in ((self.ax,tip[0]),(self.ay,tip[1]),(self.handsize,size)):
            widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
        self.note_change()
        self.refresh()

    def update_paint_hand_label(self):
        import tools_kit
        choice=self.paint_hand.currentText()
        library=choice==tools_kit.PAINT_LIBRARY
        self.paint_hand_choose.setVisible(library)
        self.paint_hand_size.setEnabled(choice!=tools_kit.PAINT_SAME)
        if library:
            name=Path(self.paint_hand_path).stem if self.paint_hand_path else 'none chosen yet'
            missing=self.paint_hand_path and not Path(self.paint_hand_path).is_file()
            self.paint_hand_name.setText('Painting hand: '+name+(' (file missing: using the drawing hand)' if missing else ''))
        else:
            self.paint_hand_name.setText('')

    def paint_hand_changed(self):
        import tools_kit
        if self.paint_hand.currentText()==tools_kit.PAINT_LIBRARY and not self.paint_hand_path:
            self.choose_paint_hand()
            if not self.paint_hand_path:
                self.paint_hand.setCurrentText(tools_kit.PAINT_BRUSH)
        self.update_paint_hand_label()
        self.refresh()

    def choose_paint_hand(self):
        """Pick the painting hand from the Hands library."""
        from library_dialog import LibraryDialog
        import tools_kit
        def chosen(category,item):
            if category!='hands': return
            self.set_paint_hand(str(item.path),item.tip)
        LibraryDialog(self,'hands',chosen).exec()

    def set_paint_hand(self,path,tip=None):
        import tools_kit
        image=QImage(str(path))
        if image.isNull():
            QMessageBox.warning(self,'Painting hand','Could not read this hand image.'); return
        self.paint_hand_path=str(path)
        self.paint_hand_tip=list(tools_kit.tip_for_image(image,tip))
        self.paint_hand.setCurrentText(tools_kit.PAINT_LIBRARY)
        self.update_paint_hand_label()
        self.note_change()
        self.refresh()

    def update_sound_buttons(self):
        for key,(button,text) in self.sound_file_buttons.items():
            path=self.sound_files.get(key)
            button.setText(f'{text}: {Path(path).stem[:14]}' if path else f'{text}: add sound…')
            button.setToolTip(f'{text} sound: {Path(path).name}. Click to choose another.' if path
                              else f'No {text.lower()} sound yet. Click to choose a recording (MP3, WAV, M4A…).')

    def choose_sound_file(self,key):
        import audio_track
        name,_=QFileDialog.getOpenFileName(self,'Choose a sound recording','',
            'Audio ('+' '.join('*'+t for t in audio_track.AUDIO_TYPES)+')')
        if name: self.set_sound_file(key,self.keep_in_library('audio',name))

    def set_sound_file(self,key,path):
        if path:
            from sound import load_recording
            if load_recording(path) is None:
                QMessageBox.warning(self,'Sound','This recording could not be read (or it is silent).'); return
            self.sound_on.setChecked(True)
        self.sound_files[key]=str(path) if path else None
        self.update_sound_buttons()
        self.note_change()
        if self.playing: self.sync_preview_sound()

    def use_builtin_hand(self,refresh=True):
        """Load the bundled StrokeScribe hand (calibrated pencil tip X 0.08, Y 0.13)."""
        image=QImage(str(DEFAULT_HAND)) if DEFAULT_HAND.is_file() else QImage()
        if image.isNull():
            self.hand_name.setText('Hand: none (built-in hand file missing)'); return
        self.hand=image; self.hand_builtin=True; self.hand_path=None
        self.hand_name.setText('Hand: StrokeScribe built-in hand')
        if refresh: self.refresh()
    def reload_color(self):
        """Re-clean retained normalized source pixels, for every supported image type."""
        if self.is_image_artwork():return False
        name=getattr(self,'color_path',None)
        if getattr(self.drawing,'svg_has_fill',False) and not name:
            from svg_appearance import render_appearance
            self.final_image=render_appearance(self.drawing)
            self.update_source_labels();self.refresh();return True
        original=getattr(self,'color_original',None)
        try:
            if original is None and name and name!='from-project':
                from image_reconstruct import load_raster
                from adaptive_hand import qimage
                original=qimage(load_raster(name));self.color_original=original
            if original is None:return False
            from color_reveal import clean_qimage
            self.final_image=clean_qimage(original) if self.clean_color.isChecked() else original
            self.update_source_labels();self.refresh();return True
        except Exception as exc:
            QMessageBox.warning(self,'Final artwork',str(exc));return False

    def load_color(self):
        name,_=QFileDialog.getOpenFileName(self,'Change original image' if self.is_image_artwork() else 'Change matching colors','',
                                        'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        return self.replace_paint_source(name) if name else False

    def effective_duration(self): return self.duration.value()/self.speed.value()
    def timeline_length(self):
        from frame_render import timeline_seconds
        if self.all_scenes():
            lengths,joins=self.scene_timeline()
            return sum(lengths)+sum(joins)
        return timeline_seconds(self.drawing,self.options())
    def change_image_animation(self,*args):
        # Direct painting has to retain its color source; never let the user
        # accidentally request an invisible, no-color animation.
        if self.image_animation.currentIndex()==1 and self.is_image_artwork():
            self.preserve_colors.setChecked(True)
        self.preserve_colors.setEnabled(self.image_animation.currentIndex()!=1)
        self.refresh()

    def schedule_brush_refresh(self,*args):
        # Debounce potentially expensive plan_for() rebuilds while controls
        # are changing. A single preview reflects the final requested value,
        # planned quietly in the background (no loading card).
        self.brush_preview_timer.start()

    def quiet_refresh(self):
        """Refresh after a brush width / spacing change: plan without the loading card."""
        self._quiet_plan=True
        self.refresh()
        self._quiet_plan=False

    def image_paint_method(self):
        mode=REVEAL_MODES[self.reveal_mode.currentIndex()]
        return mode if mode in ('adaptive','zigzag','rows','columns','short_zigzag') else 'adaptive'

    def settings_state(self):
        from projects import widget_value
        state={name:widget_value(getattr(self,name)) for name in self.PROJECT_SETTINGS}
        state['audio_path']=self.audio_path
        state['paint_hand_path']=self.paint_hand_path
        state.update(self.sound_files)
        state['paint_hand_tip']=self.paint_hand_tip
        state['background_color']=getattr(self,'background_color',None)
        return state

    # ------------------------------------------------- voiceover, timing
    def load_audio(self):
        import audio_track
        name,_=QFileDialog.getOpenFileName(self,'Load voiceover or music','',
            'Audio ('+' '.join('*'+t for t in audio_track.AUDIO_TYPES)+')')
        if name: self.set_audio(self.keep_in_library('audio',name))

    def remove_audio(self):
        self.set_audio(None)

    def audio_dropped(self,path):
        """An audio file was dropped on the timeline."""
        self.set_audio(self.keep_in_library('audio',path))
        self.status.setText(f'Audio track added: {Path(path).name}. Drag it on the timeline to choose when it starts.')

    def set_stage_seconds(self,key,seconds):
        """A clip edge was dragged on the timeline."""
        if key=='draw':
            if not self.duration.isEnabled(): return
            self.duration.setValue(seconds*self.speed.value())
        elif key=='paint':
            (self.image_duration if self.is_image_artwork() else self.color_fade).setValue(seconds)
        elif key=='hold':
            # The hold clip shows the colour hold plus the pause after the element.
            if self.options().get('final_image') is not None:
                self.color_hold.setValue(max(0.,seconds-self.pause_after.value()))
            else:
                self.pause_after.setValue(seconds)
        elif key=='erase':
            self.erase_time.setValue(seconds)

    def timeline_audio(self):
        """The voiceover/music clip for the timeline lane."""
        if not self.audio_path or not self.audio_seconds: return None
        import audio_track
        return dict(start=self.audio_offset.value(),seconds=self.audio_seconds,
                    name=Path(self.audio_path).stem,envelope=audio_track.envelope(self.audio_path))

    def set_audio(self,path,refresh=True):
        import audio_track
        self.audio_path=str(path) if path else None
        self.audio_seconds=audio_track.duration(path) if path else None
        if self.preview_sound is not None: self.preview_sound.stop()
        if path:
            length=f'{self.audio_seconds:.1f} s' if self.audio_seconds else 'length unknown'
            self.audio_note.setText(f'{Path(path).name}  •  {length}')
        else:
            self.audio_note.setText('No audio track')
        self.remove_audio_button.setEnabled(bool(path))
        self.fit_audio_button.setEnabled(bool(path and self.audio_seconds))
        self.note_change()
        if refresh: self.refresh()

    def timing_parts(self):
        """Current stage times (seconds actually played) of the stages that are on."""
        options=self.options()
        image=self.is_image_artwork()
        paint_only=image and self.image_animation.currentIndex()==1
        painting=options['final_image'] is not None
        return dict(draw=0. if paint_only else options['duration'],
                    paint=options['fade_duration'] if painting else 0.,
                    hold=options['hold_duration'] if painting else 0.,
                    erase=options['erase']['seconds'] if options.get('erase') else 0.)

    def apply_timing(self,times):
        image=self.is_image_artwork()
        widgets=[(self.duration,times['draw']*self.speed.value()),
                 (self.image_duration if image else self.color_fade,times['paint']),
                 (self.color_hold,times['hold']),(self.erase_time,times['erase'])]
        for widget,value in widgets:
            if value>0 or widget is self.color_hold:
                widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
        self.refresh()

    def auto_timing(self):
        """Times from the drawing (or fitted to the voiceover when one is loaded)."""
        if not self.drawing: return
        import auto_timing
        current=self.timing_parts()
        image=self.is_image_artwork()
        times=auto_timing.suggest(self.drawing,paint=current['paint']>0,erase=current['erase']>0,
                                  image=image,paint_only=image and self.image_animation.currentIndex()==1)
        note='Auto timing: '
        if self.audio_path and self.audio_seconds:
            target=self.audio_seconds+self.audio_offset.value()
            times,reached=auto_timing.fit(times,target)
            note+=f'fitted to the audio ({target:.1f} s)' if reached else 'the audio is longer than the longest possible animation'
        else:
            note+='{:.1f} s in total'.format(sum(times.values()))
        self.apply_timing(times)
        self.status.setText(note)

    def fit_to_audio(self):
        if not self.drawing or not self.audio_seconds: return
        import auto_timing
        target=self.audio_seconds+self.audio_offset.value()
        times,reached=auto_timing.fit(self.timing_parts(),target)
        self.apply_timing(times)
        self.status.setText(f'Animation fitted to the audio: {target:.1f} s' if reached else
                            'The audio is longer than the longest possible animation; times set to their maximum.')

    def preview_camera(self,options):
        """Camera path for the preview, planned once per timing/drawing change."""
        zoom=options.get('camera_zoom',1.)
        if zoom<=1.0001: return None
        key=(id(self.drawing),len(self.drawing.strokes),zoom,
             repr({k:v for k,v in options.items() if isinstance(v,(int,float,str,tuple)) and k not in ('width','height')}),
             repr(options.get('erase') and {k:v for k,v in options['erase'].items() if k!='image'}),
             options.get('final_image') is not None)
        if key!=self._camera_key:
            from frame_render import camera_for
            self._camera_path=camera_for(self.drawing,options,zoom,rate=20.)
            self._camera_key=key
        return self._camera_path

    def options(self):
        from export_job import options_from_settings
        image_source=self.is_image_artwork()
        options=options_from_settings(
            self.settings_state(),self.drawing,
            color_image=None if image_source else self.final_image,hand=self.hand,
            image_source=self.image_result.image if image_source and self.image_result else None,
            image_mode=image_source)
        if not image_source and getattr(self.drawing,'svg_has_fill',False) and self.use_color.isChecked() and not self.color_path:
            from svg_appearance import render_appearance
            options['final_image']=render_appearance(self.drawing,max(options['width'],options['height']))
        options['overlays']=list(getattr(self,'overlays',[]))
        return options

    # ------------------------------------------------------------ preview
    PREVIEW_WIDTH=960
    PREVIEW_FPS=30                    # playback shows the frames the export will have
    FRAME_BUDGET=600*1024*1024        # memory for ready-made preview frames

    def _view_token(self):
        """Things that change the picture without a settings signal."""
        d=self.drawing
        return (id(d),id(getattr(d,'strokes',None)),len(getattr(d,'strokes',()) or ()),self.scene_index,
                self.all_scenes(),self.source_type.currentIndex(),id(self.final_image),
                self.hand.cacheKey() if self.hand is not None else None,len(self.scenes),
                repr(getattr(self,'overlays',[])) if not self.playing else None)

    def clear_frames(self):
        """Forget the ready-made preview frames (something changed)."""
        self._frames=OrderedDict(); self._frame_bytes=0
        self._memo={}               # whole-video lengths and the edited element's options
        if hasattr(self,'prerender_timer'): self.prerender_timer.stop()

    def refresh(self,*args):
        """Show the frame at the playhead. Any change rebuilds the view; moving the
        playhead (scrub, play) only draws a frame, from the ready-made ones if it can."""
        playhead=getattr(self,'_playhead_only',False); self._playhead_only=False
        if self._preparing:
            return
        if self.drawing and self.board_mode():
            self._view=None; self.clear_frames()
            self.show_board(); return
        view=getattr(self,'_view',None)
        if not playhead or view is None or view['token']!=self._view_token() or not self.drawing:
            if not self.build_view(): return
            view=self._view
        try:
            frame=self.preview_frame(self.position,playing=self.playing)
        except Exception as exc:
            # An invalid/expensive brush configuration must not throw out of
            # the Qt signal handler and terminate the application.
            import applog; applog.error('Preview could not be updated',exc)
            self.status.setText('Preview could not be updated: '+str(exc)[:220])
            return
        self.canvas.frame=frame
        self.canvas.art_frame=None
        self.canvas.hand_frame=None
        self.canvas.overlay_frame=None
        self.canvas.art_opacity=100.
        # Page/whole-video composition happens against earlier elements; in
        # single-element view the canvas supplies the visible background.
        if not view['all'] and not view.get('page') and view['options'].get('layers')!='hand':
            opts=dict(view['options'],width=frame.width(),height=frame.height())
            mode=opts.get('blend_mode','Normal')
            opacity=float(opts.get('artwork_opacity',100))
            if mode!='Normal' or opacity!=100:
                from frame_render import compose_frame
                camera=self.preview_camera(opts)
                from frame_render import independent_overlays
                self.canvas.art_frame=compose_frame(self.drawing,self.position,
                    dict(opts,layers='art',ghost=0,background=False,overlays=[],artwork_opacity=100),camera)
                self.canvas.hand_frame=compose_frame(self.drawing,self.position,
                    dict(opts,layers='hand',ghost=0,background=False,overlays=[]),camera)
                self.canvas.overlay_frame=independent_overlays(self.drawing,self.position,opts,camera)
                self.canvas.art_opacity=opacity
        self.canvas.blend_mode=('Normal' if view['all'] or view.get('page') else
                                self.blend_mode.currentText())
        if view['all']: self.canvas.highlight=[]
        self.canvas.update()
        self.stage_timeline.progress=max(0.,min(1.,self.position)); self.stage_timeline.update()
        if not view['all'] and self.order.selectedItems(): self.update_highlight()
        length=view['length']
        self.clock.setText(timecode(self.position*length))
        self.clock_total.setText(timecode(length))
        if not self.playing: self.start_prerender()

    def build_view(self):
        """Options and timeline for the current state (after any change)."""
        self.clear_frames(); self._view=None
        self.sync_workspace()
        if not self.drawing:
            self.canvas.frame=None;self.canvas.highlight=[];self.canvas.update()
            self.stage_timeline.update_state(0,0,0,0)
            self.clock.setText(timecode(0)); self.clock_total.setText(timecode(0))
            return False
        options=self.options()
        if not (self.builder and self.builder.isRunning()):
            if self.ensure_brush_plan(options) is False:
                return False              # the new brush route is being planned
        ratio=options['height']/options['width']
        if self.all_scenes():
            width,height=self.PREVIEW_WIDTH,round(self.PREVIEW_WIDTH*ratio)
            try:
                segments,lengths,joins=self.whole_segments(width,height)
            except Exception as exc:
                import applog; applog.error('Preview could not be updated',exc)
                self.status.setText('Preview could not be updated: '+str(exc)[:220]); return False
            self.show_whole_timeline(segments,lengths,joins,options)
            total=sum(lengths)+sum(joins)
            self._view=dict(all=True,length=total,ratio=ratio,token=self._view_token())
            return True
        self.stage_timeline.set_scenes(None,current=self.scene_index)
        self.stage_timeline.set_overlays(self.overlays,self.selected_overlay)
        self.stage_timeline.set_audio(self.timeline_audio())
        self.stage_timeline.editable={'draw','paint','hold','erase'} if self.duration.isEnabled() \
            else {'paint','hold','erase'}
        erase=options.get('erase')
        self.stage_timeline.update_state(options['duration'],
            options['fade_duration'] if options['final_image'] is not None else 0,
            (options['hold_duration'] if options['final_image'] is not None else 0)+options.get('pause',0),
            self.position,erase['seconds'] if erase else 0)
        options.pop('fps')
        # The artwork is scaled after rasterization. Compensating the hand
        # before that transform keeps its FINAL size independent of Artwork
        # Size, while its pen-tip coordinates move with the artwork.
        options['hand_scale']/=options['artwork_scale']
        options['ghost']=.22            # Hand only: still show faintly what is being written
        # Pictures of earlier scenes in this frame stay on the board under it.
        page=self.drawn_over(self.scene_index) and options.get('layers')!='hand'
        if page: options['background']=False
        self._view=dict(all=False,options=options,page=page,ratio=ratio,length=self.timeline_length(),
                        token=self._view_token())
        self.show_hand_pictures(options)
        return True

    def show_hand_pictures(self,options=None):
        """Hand tab: small pictures of the hand that draws and the one that paints."""
        pictures=getattr(self,'hand_pictures',None)
        if not pictures: return
        try:
            options=options or self.options()
            draw=options.get('hand') if self.showhand.isChecked() else None
            paint=options.get('painting_hand') if self.show_paint_hand.isChecked() else None
            if paint is None and self.show_paint_hand.isChecked() and self.paint_hand.currentIndex()==0:
                paint=draw
            for key,image in (('draw',draw),('paint',paint)):
                label=pictures[key]
                stamp=image.cacheKey() if image is not None and not image.isNull() else None
                if getattr(label,'_stamp','x')==stamp: continue
                label._stamp=stamp
                if stamp is None:
                    label.clear(); label.setText('hidden'); continue
                label.setPixmap(QPixmap.fromImage(image).scaled(label.width()-8,label.height()-8,
                    Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        except Exception as exc:
            import applog; applog.error('Hand pictures',exc)

    def render_view(self,fraction,width):
        """One preview frame of the current view at this width."""
        view=self._view
        height=round(width*view['ratio'])
        if view['all']:
            return self.all_scenes_frame(width,height,fraction)[0]
        from frame_render import compose_frame
        options=dict(view['options'],width=width,height=height)
        camera=self.preview_camera(options)
        frame=compose_frame(self.drawing,fraction,options,camera)
        if view['page']:
            from scenes import composite_element
            return composite_element(self.scene_base(self.scene_index,width,height,fraction,camera),
                                     self.drawing,fraction,options,camera)
        return frame

    def frame_index(self,fraction):
        count=max(1,round(self._view['length']*self.PREVIEW_FPS))
        return max(0,min(count,round(fraction*count))),count

    def preview_frame(self,fraction,playing=False):
        """Paused: the exact frame. Playing: the nearest video frame, ready-made when possible,
        else drawn smaller if the computer cannot keep up."""
        if not playing:
            return self.render_view(fraction,self.PREVIEW_WIDTH)
        index,count=self.frame_index(fraction)
        cached=self._frames.get(index)
        if cached is not None:
            self._frames.move_to_end(index)
            return cached
        cost=getattr(self,'_play_cost',0.)
        width=self.PREVIEW_WIDTH if cost<.03 else 768 if cost<.045 else 640
        began=time.perf_counter()
        frame=self.render_view(index/count,width)
        spent=time.perf_counter()-began
        self._play_cost=spent if not cost else .7*cost+.3*spent*self.PREVIEW_WIDTH/width
        if width==self.PREVIEW_WIDTH: self.keep_frame(index,frame)
        return frame

    def keep_frame(self,index,frame):
        size=frame.sizeInBytes()
        while self._frames and self._frame_bytes+size>self.FRAME_BUDGET:
            _,old=self._frames.popitem(last=False); self._frame_bytes-=old.sizeInBytes()
        self._frames[index]=frame; self._frame_bytes+=size

    def start_prerender(self):
        """When the preview is idle, make the next frames ready so Play is smooth."""
        if not hasattr(self,'prerender_timer'):
            self.prerender_timer=QTimer(self); self.prerender_timer.setSingleShot(True)
            self.prerender_timer.timeout.connect(self.prerender_step)
        self.prerender_timer.start(450)

    def prerender_step(self):
        view=getattr(self,'_view',None)
        if (view is None or not self.isVisible() or self.playing or self.busy or self._preparing or not self.drawing
                or (self.builder and self.builder.isRunning()) or (self.worker and self.worker.isRunning())
                or view['token']!=self._view_token()):
            return
        if QApplication.mouseButtons()!=Qt.MouseButton.NoButton:
            self.prerender_timer.start(200); return     # the user is dragging something
        index,count=self.frame_index(self.position)
        frame_bytes=max(1,next(iter(self._frames.values())).sizeInBytes()) if self._frames else 0
        if frame_bytes and self._frame_bytes+frame_bytes>self.FRAME_BUDGET: return
        # From the playhead to the end, then from the start.
        target=next((i for i in list(range(index,count+1))+list(range(0,index)) if i not in self._frames),None)
        if target is None: return
        try:
            self.keep_frame(target,self.render_view(target/count,self.PREVIEW_WIDTH))
        except Exception:
            return
        self.prerender_timer.start(1)

    def ready_frames(self):
        """(frames ready, frames in the video) of the preview (for tests and the status)."""
        if getattr(self,'_view',None) is None: return 0,0
        return len(self._frames),self.frame_index(1.)[1]+1

    def scrub(self,value):
        self.position=value/1000
        if self.playing and self.preview_sound is not None:
            self.sync_preview_sound()     # user moved the playhead while playing
        self._playhead_only=True
        self.refresh()
    def toggle(self):
        if not self.drawing or self.busy: return
        if self.board_mode(): self.preview_scope.setCurrentIndex(1)
        if self.position>=1: self.slider.setValue(0)
        self.playing=not self.playing; self.last=time.perf_counter(); self.sync_workspace()
        self.sync_preview_sound()
    def sync_preview_sound(self):
        """Start the soundtrack at the playhead when playing; stop it otherwise."""
        wants=self.sound_on.isChecked() or self.audio_path
        if not self.playing or not wants or not self.sound_preview.isChecked() or self.all_scenes():
            if self.preview_sound is not None: self.preview_sound.stop()
            return
        try:
            if self.preview_sound is None: self.preview_sound=PreviewSound()
            options=self.options(); options.pop('fps',None)
            ratio=options['height']/options['width']
            options['width']=960; options['height']=round(960*ratio)
            effects=self.sound_volume.value()/100 if self.sound_on.isChecked() else None
            self.preview_sound.play(self.drawing,options,effects,self.position*self.timeline_length())
            self.last=time.perf_counter()     # sound preparation must not skip frames
        except Exception as exc:
            self.status.setText('Preview sound unavailable: '+str(exc)[:160])
    def restart(self):
        if not self.drawing or self.busy: return
        if self.board_mode(): self.preview_scope.setCurrentIndex(1)
        self.slider.setValue(0); self.playing=True; self.last=time.perf_counter(); self.sync_workspace()
        self.sync_preview_sound()
    def tick(self):
        if not self.playing or not self.drawing or self.busy: return
        view=getattr(self,'_view',None)
        length=view['length'] if view is not None and view['token']==self._view_token() else self.timeline_length()
        now=time.perf_counter(); self.position=min(1,self.position+(now-self.last)/max(1e-3,length)); self.last=now
        self.slider.blockSignals(True); self.slider.setValue(round(self.position*1000)); self.slider.blockSignals(False)
        self._playhead_only=True; self.refresh()
        if self.position>=1:
            self.playing=False; self.sync_workspace()
            if self.preview_sound is not None: self.preview_sound.stop()
    def save(self):
        if not self.drawing or (self.builder and self.builder.isRunning()) or (self.worker and self.worker.isRunning()): return
        parent=QFileDialog.getExistingDirectory(self,'Choose destination; a new sequence folder will be created')
        if not parent: return
        import copy
        folder=Path(parent)/datetime.now().strftime('StrokeScribe_%Y%m%d_%H%M%S_%f')
        options=self.options()
        if len(self.scenes)>1 and self.export_all_scenes.isChecked():
            self._leave_scene()
            scene_list=[dict(state=copy.deepcopy(s['state']),transition=s['transition'],
                             transition_seconds=s['transition_seconds'],board=s.get('board')) for s in self.scenes]
            self.scenes[self.scene_index]['state']=None       # still edited here
            self.worker=SceneExporter(scene_list,folder,self.settings_state(),self.hand)
        else:
            self.worker=None
        if self.worker is None: self.worker=Exporter(copy.deepcopy(self.drawing),folder,options,
                             self.mov.isChecked(),self.webm.isChecked(),
                             self.webm_quality.value(),self.keep_png.isChecked(),
                             mp4=self.mp4.isChecked(),
                             **self.export_backgrounds(),
                             sound_volume=self.sound_volume.value()/100 if self.sound_on.isChecked() else None)
        self.worker.progress.connect(self.export_progress); self.worker.done.connect(lambda p:self.export_done('Saved: '+p)); self.worker.done.connect(lambda _p: self.export_done_sound.isChecked() and play_finished_sound()); self.worker.failed.connect(lambda e:self.export_done('Export stopped: '+e)); self.worker.finished.connect(self.export_finished)
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
        import applog; applog.info('Export finished: %s (took %s)',message,self.export_elapsed())
        if hasattr(self,'export_clock'): self.export_clock.stop()
        self.status.setText(f'{message}  •  took {self.export_elapsed()}'); self.status.setWordWrap(True)
    def export_finished(self):
        if hasattr(self,'export_clock'): self.export_clock.stop()
        self.cancel.setEnabled(False); self.progress.setRange(0,100); self.progress.setValue(100); self.sync_workspace()
    def cancel_export(self):
        if self.worker:
            self.worker.requestInterruption()
            self.status.setText('Cancelling after current frame. FFmpeg encoding, if started, must finish.')
    # ------------------------------------------------------------ updates
    def update_found(self,version):
        """A new version is ready: show the update banner."""
        self.latest_version=version
        short=version.replace('0.5.3-','').replace('experimental','exp')
        self.update_button.setText(f'⬆ Update to {short}')
        self.update_banner_text.setText(f'✨  A new version of StrokeScribe is ready: {version}')
        self.banner_update.setText('Update now'); self.banner_update.setEnabled(True)
        self.banner_news.show(); self.banner_later.show()
        self._banner_state='ready'
        self.update_banner.show()

    def banner_update_clicked(self):
        """Update now → download and install; Restart now → start the new version."""
        state=getattr(self,'_banner_state','ready')
        if state=='updated':
            self.restart_after_update(); return
        if state=='failed':
            self.open_updates(); return
        if not self.confirm_before_app_update():
            return
        import updater
        from update_dialog import UpdateWorker
        settings=updater.load_settings()
        self.banner_update.setEnabled(False); self.banner_later.hide(); self.banner_news.hide()
        self.update_banner_text.setText('Downloading and installing the new version…')
        self.banner_worker=UpdateWorker('update',token=settings.get('token') or None,branch=settings['branch'])
        self.banner_worker.progress.connect(lambda p,text: self.update_banner_text.setText(text))
        self.banner_worker.done.connect(self.banner_update_done)
        self.banner_worker.failed.connect(self.banner_update_failed)
        self.banner_worker.start()

    def banner_update_done(self,result):
        _,info=result
        self._banner_state='updated'
        self.update_banner_text.setText(f'✅  Updated to {info["version"]}. Restart StrokeScribe to use it.')
        self.banner_update.setText('Restart now'); self.banner_update.setEnabled(True)
        self.banner_later.setText('Later'); self.banner_later.show()

    def banner_update_failed(self,message):
        self._banner_state='failed'
        self.update_banner_text.setText('The update did not finish: '+message.splitlines()[0][:160])
        self.banner_update.setText('Details…'); self.banner_update.setEnabled(True)
        self.banner_later.show()

    def show_whats_new(self):
        import updater
        version=self.latest_version
        try:
            settings=updater.load_settings()
            text=updater.whats_new(settings.get('token'),version,settings['branch'])
        except Exception as exc:
            text=''
        QMessageBox.information(self,f"What's new in {version}",text or 'No notes for this version.')

    def open_updates(self):
        from update_dialog import UpdateDialog
        UpdateDialog(self,self.latest_version).exec()

    def restart_after_update(self):
        """Confirm and spawn the replacement before closing this working app.

        A failed restart never leaves the user without an application window.
        """
        if ((self.font_worker and self.font_worker.isRunning())
                or (self.builder and self.builder.isRunning())
                or (self.worker and self.worker.isRunning())):
            QMessageBox.information(self, 'Restart',
                'Wait for downloads, analysis, or export to finish before restarting.')
            return False
        if not self.confirm_leave_project('restart StrokeScribe'):
            return False
        import updater
        try:
            new_process = updater.restart()
        except Exception as exc:
            QMessageBox.warning(self, 'Restart',
                'Could not launch the new StrokeScribe. This window will stay open.\n\n' + str(exc))
            return False
        # We just confirmed a save/discard decision; do not ask twice.
        self._restart_preconfirmed = True
        try:
            self.close()
        finally:
            self._restart_preconfirmed = False
        if self.isVisible():
            # A late export or another close veto must not leave two copies
            # running; stop the newly launched child where possible.
            if new_process is not None and hasattr(new_process, 'terminate'):
                try:
                    new_process.terminate()
                except Exception:
                    pass
            return False
        QApplication.instance().quit()
        return True

    def closeEvent(self,event):
        if self.preview_sound is not None: self.preview_sound.stop()
        if self.font_worker and self.font_worker.isRunning():
            QMessageBox.information(self,'Font downloads',
                'Please wait for the current font download to finish.')
            event.ignore()
            return
        if self.builder and self.builder.isRunning():
            QMessageBox.information(self,'Image analysis','Please wait for image analysis to finish.'); event.ignore(); return
        if self.worker and self.worker.isRunning():
            self.cancel_export(); QMessageBox.information(self,'Export running','Please wait for the current export to stop before closing.'); event.ignore()
        else:
            if not getattr(self, '_restart_preconfirmed', False) and not self.confirm_leave_project('close StrokeScribe'):
                event.ignore()
                return
            if self.ai_engine is not None:
                self.ai_engine.stop()        # never leave the AI engine running
            # Only a successful close stops autosaving; a rejected close must
            # leave the recovery timer active for the still-open project.
            self._closed=True
            self.autosave_timer.stop()
            if not getattr(self,'_keep_autosave',False):
                import autosave; autosave.clear()
            event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setStyle('Fusion'); window=Window()
    if len(sys.argv)>1:
        try: window.set_drawing(import_svg(sys.argv[1]))
        except Exception as e: QMessageBox.warning(window,'Cannot import',str(e))
    window.show(); sys.exit(app.exec())
