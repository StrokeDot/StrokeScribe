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
REVEAL_MODES = ('brush', 'adaptive', 'zigzag', 'rows', 'columns', 'short_zigzag', 'painter')

def timecode(seconds):
    """00:04.25 style time for the monitor."""
    seconds=max(0.,float(seconds))
    minutes,rest=divmod(seconds,60)
    return f'{int(minutes):02d}:{rest:05.2f}'


class Canvas(QWidget):
    """Program monitor: the frame on its preview background, plus a loading card."""
    def __init__(self):
        super().__init__(); self.frame=None; self.background=0; self.custom_colour=None; self.blend_mode='Normal'; self.setMinimumSize(550,330)
        self.art_frame=None; self.hand_frame=None; self.artwork_opacity=100
        self.busy_text=None; self.busy_percent=None; self.busy_detail=''
        self._spin=0
        self._spinner=QTimer(self); self._spinner.setInterval(40)
        self._spinner.timeout.connect(self._advance)
        self.on_click=None          # on_click(x, y, add) in frame pixels
        self.on_drag=None           # on_drag('start', x, y) then ('move', dx, dy) / ('done'): dx, dy in fractions of the frame
        self.on_wheel=None          # on_wheel(steps, x, y) → False when not used
        self.on_double=None         # on_double(x, y)
        self.box_provider=None      # () → (x, y, w, h) in frame pixels of a box to outline, or None
        self.titles_frame=None      # exp.116: texts / pictures on top, over everything (screen)
        self.rest_frame=None        # exp.143: the hand waiting in its corner (screen)
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
            # Artwork and hand are separate: blending must never touch the
            # moving pencil, including during partially painted frames.
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            from blend_modes import composition_mode
            rect=QRectF(x,y,size.width(),size.height())
            if self.art_frame is not None:
                from artwork_compositor import bounded_opacity
                p.setCompositionMode(composition_mode(self.blend_mode))
                p.setOpacity(bounded_opacity(self.artwork_opacity))
                p.drawImage(rect,self.art_frame)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                p.setOpacity(1.)
                if self.hand_frame is not None:
                    p.drawImage(rect,self.hand_frame)
            else:
                p.drawImage(rect,self.frame)
            if self.titles_frame is not None:
                p.drawImage(rect,self.titles_frame)
            if self.rest_frame is not None:
                p.drawImage(rect,self.rest_frame)
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
    def __init__(self,scene_list,folder,settings,hand,titles=None,cameras=None):
        super().__init__()
        self.scene_list=scene_list; self.folder=Path(folder); self.settings=settings; self.hand=hand
        self.titles=titles; self.cameras=cameras
    def run(self):
        try:
            from scenes import export_scenes
            self.done.emit(export_scenes(self.scene_list,self.folder,self.settings,self.hand,
                                         progress=self.progress.emit,interrupted=self.isInterruptionRequested,
                                         titles=self.titles,cameras=self.cameras))
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

class ReadyFrames:
    """The current preview's ready-made frames by frame number (a view of the
    segment cache, kept for code and tests that index frames directly)."""
    def __init__(self, window):
        self.window = window

    def _key(self, index):
        segment, local, _, _, _ = self.window.segment_at(index)
        return segment, local, self.window.PREVIEW_WIDTH

    def get(self, index, default=None):
        if getattr(self.window, '_view', None) is None:
            return default
        frame = self.window.segment_cache.get(*self._key(index))
        return default if frame is None else frame

    def __getitem__(self, index):
        frame = self.get(index)
        if frame is None:
            raise KeyError(index)
        return frame

    def __contains__(self, index):
        return getattr(self.window, '_view', None) is not None and \
            self.window.segment_cache.has(*self._key(index))


def help_label(text, tip):
    """A row name; its explanation shows when the mouse rests on it (exp.137: no ? buttons,
    the user did not want them)."""
    label=QLabel(text); label.setToolTip(tip)
    return label


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
        self.project_undo=[];self.project_redo=[]     # element list changes (see record_structure)
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
        self.move_hand_path=None
        self.sound_files={'sound_pencil_file':None,'sound_brush_file':None,'sound_eraser_file':None}
        from scenes import DEFAULT_TRANSITION, DEFAULT_TRANSITION_SECONDS
        self.scenes=[dict(state=None,transition=DEFAULT_TRANSITION,
                          transition_seconds=DEFAULT_TRANSITION_SECONDS,name=None,thumb=None)]
        self.scene_index=0
        self._scene_cache={}           # preview of other scenes: id(state) -> prepared scene
        self._camera_key=None; self._camera_path=None
        from preview_cache import SegmentCache
        self.segment_cache=SegmentCache()        # ready-made preview frames, per segment
        try:
            from prerender_dialog import keep_render
            if not keep_render():
                self.segment_cache.clear_disk()      # a render left by a crash: not kept
        except Exception:
            pass
        self._frames=ReadyFrames(self); self._view=None
        self._fp_tokens={}; self._fp_counter=0
        self._prerender_all=False; self._prerender_next=0
        self.overlays=[]               # pictures and titles on top of this scene (overlays.py)
        self.selected_overlay=None
        self.selected_overlays=set()    # exp.117: Ctrl+click chooses more than one
        self.cameras=[]                 # exp.119: the Camera track's clips (camera_clips.py)
        self.selected_camera=None
        self.text_hidden=set()          # text tracks hidden from the video
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
        # exp.112: a new element starts from these settings (as a fresh StrokeScribe has
        # them), not from the element that was being edited.
        from projects import widget_value
        self._fresh_settings={name:widget_value(getattr(self,name)) for name in self.PROJECT_SETTINGS
                              if getattr(self,name,None) is not None}
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
        from engine import import_svg_cached          # exp.130: the sample, kept ready
        self.set_drawing(import_svg_cached(Path(__file__).parent/'samples'/'drawing.svg'))
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
        if mode in ('adaptive','zigzag','rows','columns','short_zigzag','painter'):
            self.drawing.paint_method=mode
        elif not image_source:
            return
        from adaptive_hand import plan_ready, plan_for
        bw,sp=options.get('brush_width',.14),options.get('stroke_spacing',.55)
        if plan_ready(self.drawing,image,bw,sp):
            self._plan_deferred=False
            return True
        if getattr(self,'_look_preview',False) and not self.playing and not self.all_scenes():
            # Adjusting Ink on the page / Colour / Light (exp.100): show the finished
            # picture at once; the brush route is planned on Play, a scrub or Pre-render.
            self._plan_deferred=True
            return 'deferred'
        self._plan_deferred=False                 # planned now (here or in the background)
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
            try:
                plan_for(self.drawing,image,bw,sp)
            except ValueError as exc:
                # E.g. Ink on the page made the whole picture see-through: nothing to paint.
                # Say so instead of stopping the preview (exp.100).
                self.status.setText('Nothing to paint: '+str(exc)[:160])
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
        """Export Animation (top right): opens the Export panel, also when the right panel
        is closed (exp.126: it only changed the hidden panel's page, so nothing happened)."""
        from studio_workspace import TABS
        if hasattr(self,'show_right_panel'):
            self.show_right_panel('export')
        else:
            self.inspector_tabs.setCurrentIndex(TABS['export'])
        self.export.setFocus()



    def show_quick_help(self):
        QMessageBox.information(self,'StrokeScribe Studio — Quick help',
            '1. Use the Source panel (right) or the File menu to import SVG or image artwork.\\n'
            '2. For text, open the Handwriting panel (left), choose a font and Animate lettering.\\n'
            '3. Use the right rail for Source, Animation, Hand, Sound and Export.\\n'
            '4. Use the timeline to preview and the Export Animation button to render.\\n'
            'Undo and Redo apply to stroke-order changes.')

    def update_project_title(self,name):
        self.project_title=str(name or 'Untitled artwork')
        short=self.project_title if len(self.project_title)<=27 else self.project_title[:24]+'…'
        self.project_menu.setText('▣  '+short+'  ▾')
        self.project_menu.setToolTip('Current artwork: '+self.project_title)

    # ------------------------------------------------ undo / redo (everything)
    def next_seq(self):
        """A number that grows with every recorded change (orders element and project undo)."""
        self._undo_seq=getattr(self,'_undo_seq',0)+1
        return self._undo_seq

    def snapshot(self):
        import json
        from history import EXTRA_NAMES
        d=self.drawing
        extras={n:getattr(d,n) for n in EXTRA_NAMES if d is not None and hasattr(d,n)}
        return {'settings':self.settings_state(),
                'strokes':tuple(self.drawing.strokes) if self.drawing else (),
                'source':self.source_snapshot(),
                'extras':extras,
                'seq':self.next_seq()}

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
            self.project_redo.clear()                # a new change: nothing to redo any more
        self.update_history_controls()

    # ---------------------------------------------- project undo (elements added, deleted, moved)
    def structure_copy(self):
        """The element list as it is now, with the element being edited saved into it."""
        scenes=[dict(s) for s in self.scenes]
        if self.drawing is not None and 0<=self.scene_index<len(scenes):
            if self.history_timer.isActive(): self.commit_history()
            scenes[self.scene_index]['state']=self.scene_state()
            scenes[self.scene_index]['history']=self.history
        return scenes,self.scene_index

    def record_structure(self,label):
        """Remember the element list before a change to it (add, delete, move, transition)."""
        if self._restoring or not getattr(self,'drawing',None): return
        scenes,index=self.structure_copy()
        import copy
        self.project_undo.append((self.next_seq(),scenes,index,label,self._extras_copy()))
        del self.project_undo[:-30]
        self.project_redo.clear(); self.history.redo_stack.clear()
        self.update_history_controls()

    def _extras_copy(self):
        """The video's own clips (texts, camera clips) kept with a project undo step."""
        import copy
        return {'titles':copy.deepcopy(self.overlays),'cameras':copy.deepcopy(getattr(self,'cameras',[]))}

    def restore_structure(self,scenes,index,titles=None):
        from history import History
        self.playing=False
        if titles is not None:
            import copy
            extras=titles if isinstance(titles,dict) else {'titles':titles}
            self.overlays=copy.deepcopy(extras.get('titles') or [])
            if 'cameras' in extras: self.cameras=copy.deepcopy(extras['cameras'] or [])
            if not any(o.get('id')==self.selected_overlay for o in self.overlays): self.selected_overlay=None
            if not any(c.get('id')==getattr(self,'selected_camera',None) for c in self.cameras): self.selected_camera=None
        self.scenes=[dict(s) for s in scenes]
        self._scene_cache={}; self._base_cache=OrderedDict()
        self.scene_index=-1
        self.history=History()
        self._enter_scene(index)
        self.fill_scenes(); self.refresh()

    def _project_step(self,from_stack,to_stack,verb):
        seq,scenes,index,label,*rest=from_stack.pop()
        here,here_index=self.structure_copy()
        import copy
        to_stack.append((seq,here,here_index,label,self._extras_copy()))
        self.restore_structure(scenes,index,rest[0] if rest else None)
        self.project_changes.mark_changed()
        self.status.setText(f'{verb}: {label}')
        self.update_history_controls()

    def _stash_history(self):
        """Leaving an element: its undo history stays with it (it comes back with it)."""
        from history import History
        if 0<=self.scene_index<len(self.scenes):
            if self.history_timer.isActive(): self.commit_history()
            self.scenes[self.scene_index]['history']=self.history
        self.history=History()

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
        self.undo_button.setEnabled(self.history.can_undo() or bool(self.project_undo))
        self.redo_button.setEnabled(self.history.can_redo() or bool(self.project_redo))

    def _setting_names(self,names):
        from projects import widget_value  # noqa: F401
        pretty=[]
        for n in names[:3]:
            if n in ('seq',): continue
            pretty.append(n.replace('_',' ').replace('picture x','position X').replace('picture y','position Y'))
        more=len(names)-3
        return ', '.join(pretty)+(f' and {more} more' if more>0 else '')

    def undo(self):
        """Undo the latest change: of this element, or to the element list (whichever came last)."""
        if self.history_timer.isActive(): self.commit_history()
        element=self.history.current.get('seq',0) if self.history.can_undo() and self.history.current else -1
        project=self.project_undo[-1][0] if self.project_undo else -1
        if element<0 and project<0:
            self.status.setText('Nothing to undo.'); return
        if project>element:
            self._project_step(self.project_undo,self.project_redo,'Undone'); return
        from history import changed_settings
        before=self.history.current
        self.restore(self.history.undo())
        names=changed_settings(before,self.history.current)
        self.status.setText('Undone'+(f': {self._setting_names(names)}' if names else '')+'  •  Ctrl+Y redoes it')

    def redo(self):
        if self.history_timer.isActive(): self.commit_history()
        element=self.history.redo_stack[-1].get('seq',0) if self.history.can_redo() else -1
        project=self.project_redo[-1][0] if self.project_redo else -1
        if element<0 and project<0:
            self.status.setText('Nothing to redo.'); return
        if project>element:
            self._project_step(self.project_redo,self.project_undo,'Redone'); return
        from history import changed_settings
        before=self.history.current
        self.restore(self.history.redo())
        names=changed_settings(before,self.history.current)
        self.status.setText('Redone'+(f': {self._setting_names(names)}' if names else ''))

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
            # Older snapshots lack appearance controls. Revert to their
            # historical full-opacity, no-cleanup defaults when switching.
            for name,default in (('artwork_opacity',100),('paper_cleanup',False),
                                 ('paper_tolerance',22),('paper_softness',8),('move_hand',False),
                                 ('entrance_part','The whole picture'),('paint_look','Classic'),
                                 *__import__('picture_look').DEFAULTS.items()):
                if name not in settings:
                    widget=getattr(self,name,None)
                    if widget is not None:
                        widget.blockSignals(True)
                        set_widget_value(widget,default)
                        widget.blockSignals(False)
            if 'paint_left_handed' not in settings:      # older snapshots: one switch for both hands
                settings=dict(settings,paint_left_handed=bool(settings.get('left_handed',False)))
            for name in self.PROJECT_SETTINGS:
                widget=getattr(self,name,None)
                if widget is None or name not in settings: continue
                widget.blockSignals(True); set_widget_value(widget,settings[name]); widget.blockSignals(False)
            if settings.get('audio_path')!=self.audio_path:
                self.set_audio(settings.get('audio_path'),refresh=False)
            self.paint_hand_path=settings.get('paint_hand_path')
            self.paint_hand_tip=settings.get('paint_hand_tip')
            self.update_paint_hand_label()
            self.move_hand_path=settings.get('move_hand_path')
            self.update_move_hand_label()
            for key in self.sound_files: self.sound_files[key]=settings.get(key)
            self.update_sound_buttons()
            self.canvas.set_background(self.preview_background.currentIndex())
            self.preserve_colors.setEnabled(self.image_animation.currentIndex()==0)
            if self.drawing is not None and snapshot['strokes']:
                selected=set(id(s) for s in self.selected_strokes())
                self.drawing.strokes=list(snapshot['strokes'])
                self.fill_order(keep=selected)
            if self.drawing is not None and 'extras' in snapshot:
                from history import EXTRA_NAMES
                extras=snapshot['extras'] or {}
                for name in EXTRA_NAMES:
                    if name in extras: setattr(self.drawing,name,extras[name])
                    elif hasattr(self.drawing,name): delattr(self.drawing,name)
                self.update_painter_parts()
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

    def video_seconds(self):
        """The playhead in seconds of the whole video (This element: where it is in it)."""
        try:
            if self.all_scenes() or self.board_mode():
                return self.position*self.timeline_layout().total
            start=self.element_start() if len(self.scenes)>1 else 0.
            return start+self.position*self.scene_seconds()
        except Exception:
            return 0.

    def video_length(self):
        try:
            return self.timeline_layout().total if len(self.scenes)>1 else self.scene_seconds()
        except Exception:
            return self.scene_seconds()

    def add_overlay(self,item):
        """Put a new text / picture on top at the playhead (on a free track)."""
        import overlays
        total=max(.5,self.video_length())
        start=min(max(0.,self.video_seconds()),max(0.,total-.5))
        if self.position>=.999: start=0.
        item['start']=round(start,2); item['duration']=round(max(.5,min(3.,total-start)),2)
        # exp.118: a text sits on a track like an element: the first free track above the
        # elements shown at that time (so it is seen on top of them).
        end=overlays.end_of(item)
        busy=[int(o.get('track',0)) for o in self.overlays if overlays.end_of(o)>item['start'] and o['start']<end]
        try:
            lay=self.timeline_layout()
            playing=[it.track for it in lay.items if it.end>item['start'] and it.start<end]
            busy+=playing
            lowest=max(playing)+1 if playing else 0
        except Exception:
            lowest=1
        item['track']=next(t for t in range(lowest,lowest+40) if t not in busy)
        self.record_structure('add '+('text' if item.get('kind')=='text' else 'picture on top'))
        self.overlays.append(item)
        self.project_changes.mark_changed()
        self.selected_overlay=item['id']; self.selected_overlays={item['id']}
        if self.board_mode(): self.preview_scope.setCurrentIndex(1)
        self.refresh()
        return item

    def sync_titles_timeline(self,force=False):
        """The texts on the timeline: in seconds of the whole video; in This element the
        timeline starts where the element starts."""
        tl=self.stage_timeline
        try:
            offset=0. if (self.all_scenes() or len(self.scenes)<2) else -self.element_start()
        except Exception:
            offset=0.
        key=(offset,tuple(id(o) for o in self.overlays),self.selected_overlay)
        if force or key!=getattr(self,'_titles_key',None):
            self._titles_key=key
            tl.title_offset=offset
            tl.text_hidden=set(getattr(self,'text_hidden',set()))
            tl.set_overlays(self.overlays,self.selected_overlay)
            tl.selected_overlays=set(getattr(self,'selected_overlays',set()))

    # ------------------------------------------------------------ camera track (exp.119)
    def add_camera_at(self,kind,seconds):
        """exp.128: double-click on a camera row of the timeline: a camera there."""
        if kind=='hand':                     # exp.148: the Hand row: what the hand does there
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QCursor
            menu=QMenu(self)
            menu.addAction('Hand leaves the picture',lambda: self.add_camera_clip('Hand leaves',at=seconds))
            menu.addAction('Hide the hand',lambda: self.add_camera_clip('Hand hidden',at=seconds))
            return menu.exec(QCursor.pos())
        if kind: return self.add_camera_clip(kind,at=seconds)
        return self.add_camera_menu(None,at=seconds)

    def add_camera_menu(self,button=None,at=None):
        """'+ Camera': what the camera does (exp.121)."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QCursor
        menu=self.camera_menu(at)
        where=button.mapToGlobal(button.rect().bottomLeft()) if button is not None else QCursor.pos()
        menu.exec(where)

    def camera_menu(self,at=None):
        from PySide6.QtWidgets import QMenu
        from camera_clips import MENU as MOVING, CUSTOM, FIXED      # exp.142: zoom in, zoom out
        menu=QMenu(self)
        # exp.136 (the user): the fixed camera is the one of the elements; + Add camera adds
        # moving cameras (they go, stay, and come back).
        for kind in MOVING:
            menu.addAction(kind,lambda kind=kind: self.add_camera_clip(kind,at=at))
        return menu

    def find_camera(self,cid):
        if any('in_s' not in c or c.get('kind') in ('Custom',__import__('camera_clips').CUSTOM)
               or (c.get('kind')=='Zoom out' and not float(c.get('out_s',0) or 0)) for c in getattr(self,'cameras',[])):
            import camera_clips                          # exp.124: in / hold / back
            for c in self.cameras: camera_clips.upgrade(c)
        return next((c for c in getattr(self,'cameras',[]) if c.get('id')==cid),None)

    def camera_moves(self):
        """The transitions' times, (start, end), in seconds of the whole video."""
        try:
            return [(m.start,m.end) for m in self.timeline_layout().moves]
        except Exception:
            return []

    def camera_editing(self):
        """A camera clip chosen: the preview shows the page without that clip, with a frame
        where it takes the camera (drag it, wheel to zoom)."""
        return bool(getattr(self,'selected_camera',None)) and self.all_scenes()

    def live_clips(self):
        """The camera clips the preview uses (exp.125: all but the one being aimed)."""
        clips=list(getattr(self,'cameras',None) or ())
        if self.camera_editing():
            # exp.128: aiming a clip, the preview shows the page as it is without camera
            # clips (the frame you drag is where the camera goes on that page).
            clips=[]
        return clips

    def video_camera(self,k,base,total=None):
        """Element k's camera in the whole video: its own camera with the camera clips."""
        clips=self.live_clips()
        if not clips: return base
        import camera_clips
        try:
            lay=self.timeline_layout()
            item=lay.items[k]
        except Exception:
            return base
        return camera_clips.wrap(base,item.start,clips,[(m.start,m.end) for m in lay.moves],
                                 item.length if total is None else total)

    def cameras_signature(self,a=None,b=None):
        """The camera clips that touch the stretch of the video from a to b seconds (exp.125:
        changing a clip makes only its own stretch of ready frames old, not the whole video)."""
        import camera_clips
        clips=self.live_clips()
        if a is not None and b is not None:
            moves=self.camera_moves() if any(camera_clips.fixed(c) for c in clips) else []
            clips=[c for c in clips if float(c['start'])<=b+1e-6 and camera_clips.until(c,moves,clips)>=a-1e-6]
        return camera_clips.signature(clips)

    def segment_span(self,where,k):
        """(start, end) in seconds of the whole video of an element (where='scene') or of the
        camera move after it ('join')."""
        try:
            lay=self.timeline_layout()
            if where=='scene':
                it=lay.items[k]; return it.start,it.end
            m=next(m for m in lay.moves if m.k==k); return m.start,m.end
        except Exception:
            return None,None

    def sync_camera_timeline(self):
        tl=self.stage_timeline
        import camera_clips as _cc
        _cc.assign_lanes(getattr(self,'cameras',[]))
        tl.cam_clips=list(getattr(self,'cameras',[]))
        moves=self.camera_moves() if tl.cam_clips else []
        import camera_clips
        tl.cam_holds={c['id']:min(camera_clips.until(c,moves,tl.cam_clips),self.video_length() if tl.cam_clips else 0.)
                      for c in tl.cam_clips}
        tl.selected_camera=getattr(self,'selected_camera',None)
        tl.hand_under=self.hand_under.isChecked() if hasattr(self,'hand_under') else False     # exp.155
        tl.hand_marks=self.hand_marks()                 # exp.147
        lanes=tl._cam_lane_count()
        if lanes!=getattr(tl,'_cam_lanes_seen',None):     # exp.136: more Moving camera rows
            tl._cam_lanes_seen=lanes; tl._fit_height()
        tl.update()

    def add_camera_clip(self,kind='Zoom in',at=None):
        """A camera clip at the playhead (or at `at` seconds) on the Camera track (whole video)."""
        import camera_clips
        if not self.drawing: return None
        if len(self.scenes)>1 and not self.all_scenes(): self.preview_scope.setCurrentIndex(1)
        start=float(at) if at is not None else (self.video_seconds() if self.position<.999 else 0.)
        total=max(.5,self.video_length())
        clip=camera_clips.new_clip(kind,min(start,max(0.,total-.5)))
        if kind in camera_clips.HAND_KINDS:              # exp.147/148: on the Hand row
            clip['side']='Right'
            if kind==camera_clips.HAND and hasattr(self,'hand_rest') and not self.hand_rest.isChecked():
                self.hand_rest.setChecked(True)          # it moves the waiting hand
        elif not camera_clips.fixed(clip):                # exp.138: a free Moving camera row
            clip['lane']=camera_clips.free_lane(self.cameras,float(clip['start']),camera_clips.until(clip))
        self.record_structure('add camera clip')
        self.cameras.append(clip)
        self.project_changes.mark_changed()
        self.select_camera(clip['id'])
        if hasattr(self,'show_left_panel'): self.show_left_panel('camera')
        if kind==camera_clips.FIXED:
            self.status.setText(f'Reframe at {clip["start"]:.1f} s: the camera goes there and stays. Drag the frame on '
                                'the preview to choose where; double-click it on the timeline for its settings.')
        else:
            self.status.setText(f'Camera clip "{kind}" added at {clip["start"]:.1f} s: the camera goes in, stays, and comes '
                                'back. Drag the frame on the preview to choose where it looks.')
        return clip

    def select_camera(self,cid):
        """A camera clip chosen ('' / None: none). Choosing it leaves the texts."""
        cid=cid or None
        if cid and (self.selected_overlay or getattr(self,'selected_overlays',None)):
            self.selected_overlay=None; self.selected_overlays=set(); self.sync_titles_choice()
        self.selected_camera=cid
        self.fill_camera_panel()
        self.sync_camera_timeline()
        self.refresh()

    def move_camera_clip(self,cid,start,length):
        clip=self.find_camera(cid)
        if clip is None: return
        if getattr(self,'_cam_recorded',None)!=cid:
            self.record_structure('move camera clip'); self._cam_recorded=cid
        import camera_clips
        old=float(clip['start'])
        if camera_clips.fixed(clip) and abs(float(start)-old)>1e-3:
            # exp.168 (the user): a fixed camera moved along the timeline moves everything
            # after it (elements, cameras, texts) by the same time.
            self.push_after(old,float(start)-old)
            self.fill_scenes()
        clip['start'],clip['duration']=round(float(start),2),round(max(.4,float(length)),2)
        camera_clips.fit(clip)
        self.project_changes.mark_changed()
        self.fill_camera_panel(); self.sync_camera_timeline(); self.refresh()

    def move_camera_lane(self,cid,lane):
        """exp.138: a moving camera dragged onto another row (the higher row wins)."""
        clip=self.find_camera(cid)
        if clip is None or int(clip.get('lane',0) or 0)==int(lane): return
        if getattr(self,'_cam_recorded',None)!=cid:
            self.record_structure('move camera clip'); self._cam_recorded=cid
        clip['lane']=max(0,int(lane))
        self.project_changes.mark_changed()
        self.sync_camera_timeline(); self.refresh()

    def camera_clip_done(self,cid):
        self._cam_recorded=None

    def edit_camera_clip(self,cid):
        import camera_clips
        clip=self.find_camera(cid)
        if clip is not None and camera_clips.fixed(clip):
            return self.edit_fixed_camera(cid)
        if clip is not None and clip.get('kind') in camera_clips.HAND_KINDS:
            return self.edit_hand_clip(cid)
        if clip is not None:
            return self.edit_moving_camera(cid)

    def edit_moving_camera(self,cid):
        """exp.136 (the user): double-click a moving camera: its own window, like the fixed
        ones (short words, a ? for each)."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QComboBox, QDoubleSpinBox
        import camera_clips
        clip=self.find_camera(cid)
        if clip is None: return
        dialog=QDialog(self); dialog.setWindowTitle('Moving camera')
        form=QFormLayout(dialog)
        kinds=list(camera_clips.MENU)+([clip['kind']] if clip.get('kind') not in camera_clips.MENU else [])
        kind=QComboBox(); kind.addItems(kinds)
        kind.setCurrentIndex(kinds.index(clip['kind']) if clip.get('kind') in kinds else 0)
        form.addRow(help_label('Kind','Zoom in: goes close to the place below, stays, and comes back.\n'
                               'Zoom out: starts close at the place below and opens out.'),kind)
        def number(value,low,high):
            box=QDoubleSpinBox(); box.setRange(low,high); box.setSingleStep(.1); box.setDecimals(1)
            box.setSuffix(' s'); box.setValue(float(value)); return box
        a,b=float(clip.get('in_s',1.2)),float(clip.get('out_s',1.2))
        start=number(clip['start'],0,3600)
        go=number(a,.1,30); stay=number(max(0.,float(clip['duration'])-a-b),0,600); back=number(b,.1,30)
        form.addRow(help_label('Starts','When it begins (seconds of the video).'),start)
        form.addRow(help_label('Going','How long it takes to get there. Longer = slower.'),go)
        form.addRow(help_label('Stays','How long it stays there.'),stay)
        form.addRow(help_label('Back','How long it takes to come back. Longer = slower.'),back)
        # exp.157/158 (the user): where the zoom goes: how close and the X / Y of the middle of
        # the view, on sliders; the dashed frame on the preview moves while you slide.
        from PySide6.QtWidgets import QSlider, QHBoxLayout, QWidget
        z0,x0,y0=tuple(clip.get('to') or (1.6,.5,.5))
        original_to=tuple(clip.get('to') or (1.6,.5,.5))
        def slider(low,high,value,text):
            box=QWidget(); hl=QHBoxLayout(box); hl.setContentsMargins(0,0,0,0)
            bar=QSlider(Qt.Orientation.Horizontal); bar.setRange(low,high); bar.setValue(int(round(value)))
            bar.setMinimumWidth(180)
            label=QLabel(); label.setMinimumWidth(48)
            bar.valueChanged.connect(lambda v: label.setText(text(v))); label.setText(text(bar.value()))
            hl.addWidget(bar,1); hl.addWidget(label)
            return box,bar
        # exp.159: from far away (.2 x: the page small in the middle) to very close (10 x)
        close_row,close=slider(20,1000,float(z0)*100,lambda v: f'{v/100:.2f} x')
        x_row,px=slider(0,100,float(x0)*100,lambda v: f'{v} %')
        y_row,py=slider(0,100,float(y0)*100,lambda v: f'{v} %')
        form.addRow(help_label('How close','1 x = the whole page; 2 x = twice as close; 0.5 x = twice as far '
                               '(more than the page).'),close_row)
        form.addRow(help_label('Left / right','Where the camera looks, from the left (0 %) to the right (100 %).'),x_row)
        form.addRow(help_label('Up / down','Where the camera looks, from the top (0 %) to the bottom (100 %).'),y_row)
        def framing():
            return camera_clips.keep_in((close.value()/100.,px.value()/100.,py.value()/100.))
        previous_selected=getattr(self,'selected_camera',None)
        self.selected_camera=cid                         # the dashed frame shows on the preview
        def live(*_):
            if kinds[kind.currentIndex()] in ('Zoom in',camera_clips.ZOOM_OUT,camera_clips.CUSTOM):
                clip['to']=framing()
                for bar,v in ((px,clip['to'][1]),(py,clip['to'][2])):     # the frame stays on the page
                    if bar.value()!=int(round(v*100)): bar.setValue(int(round(v*100)))
            self.canvas.update()
        for bar in (close,px,py): bar.valueChanged.connect(live)
        def kind_changed(*_):          # exp.159: a zoom out goes further away, a zoom in closer
            out=kinds[kind.currentIndex()]==camera_clips.ZOOM_OUT
            if out and close.value()>=100: close.setValue(60)
            elif not out and kinds[kind.currentIndex()]=='Zoom in' and close.value()<=100: close.setValue(160)
        kind.currentIndexChanged.connect(kind_changed)
        self.canvas.update()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        remove=buttons.addButton('Delete',QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        wants={'delete':False}
        remove.clicked.connect(lambda: (wants.update(delete=True),dialog.accept()))
        accepted=dialog.exec()==QDialog.DialogCode.Accepted
        clip['to']=original_to                           # as it was (undo keeps it)
        if not accepted:
            self.selected_camera=previous_selected; self.canvas.update(); return
        if wants['delete']:
            return self.camera_clip_action(cid,'delete')
        self.record_structure('camera clip settings')
        new_kind=kinds[kind.currentIndex()]
        if new_kind!=clip.get('kind'):
            camera_clips.set_kind(clip,new_kind)
        clip['start']=round(start.value(),2)
        clip['in_s'],clip['out_s']=round(go.value(),2),round(back.value(),2)
        clip['duration']=round(go.value()+stay.value()+back.value(),2)
        camera_clips.fit(clip)
        if new_kind in ('Zoom in',camera_clips.ZOOM_OUT,camera_clips.CUSTOM):
            clip['to']=framing()
        self.project_changes.mark_changed()
        self.select_camera(cid)                      # stays chosen: its frame can be dragged too
        self.fill_camera_panel(); self.sync_camera_timeline(); self.refresh()

    def edit_fixed_camera(self,cid):
        """exp.129 (the user): a fixed camera opens the same window as the moves between pages:
        how it moves, how long, and where it goes (the frame on the preview)."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QComboBox, QDoubleSpinBox, QPushButton, QLabel
        import camera_clips
        clip=self.find_camera(cid)
        if clip is None: return
        dialog=QDialog(self); dialog.setWindowTitle('Camera')
        form=QFormLayout(dialog)
        where=QComboBox()
        where.addItem('Pick on preview',None)
        where.addItem('Whole page',tuple(camera_clips.REST))
        for other in sorted(self.cameras,key=lambda c: float(c['start'])):
            if other is not clip and camera_clips.fixed(other) and other.get('to'):
                where.addItem(f'Same as {float(other["start"]):.1f} s',tuple(other['to']))
        now=tuple(clip.get('to') or ())
        for i in range(1,where.count()):
            if where.itemData(i) is not None and tuple(where.itemData(i))==now:
                where.setCurrentIndex(i); break
        form.addRow(help_label('Goes to','Where the camera looks from this point on, on the same page.\n'
                               'Pick on preview: after OK a dashed frame shows on the picture. Drag it '
                               'where you want; mouse wheel = closer / further.\n'
                               'Whole page: back to the full page.\n'
                               'Same as ...: back to the place of an earlier camera.\n'
                               'It stays there until the next camera on this row.'),where)
        how=QComboBox(); how.addItems(['Smooth','Cut']); how.setCurrentIndex(1 if clip.get('how')=='Cut' else 0)
        form.addRow(help_label('Move','Smooth: the camera glides there. Cut: it jumps there.'),how)
        secs=QDoubleSpinBox(); secs.setRange(.2,30); secs.setSingleStep(.1); secs.setDecimals(1)
        secs.setSuffix(' s'); secs.setValue(float(clip.get('duration',1.2)))
        form.addRow(help_label('Time','How long the glide takes. Longer = slower.'),secs)
        how.currentTextChanged.connect(lambda text: secs.setEnabled(text!='Cut'))
        secs.setEnabled(how.currentText()!='Cut')
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        remove=buttons.addButton('Delete',QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        wants={'delete':False}
        remove.clicked.connect(lambda: (wants.update(delete=True),dialog.accept()))
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        if wants['delete']:
            return self.camera_clip_action(cid,'delete')
        target=where.currentData()
        if target is not None and tuple(clip.get('to') or ())!=tuple(target):
            self.record_structure('camera move')
            clip['to']=tuple(target)
            self.project_changes.mark_changed()
        new_how='Cut' if how.currentText()=='Cut' else 'Camera move'; new_secs=round(secs.value(),2)
        wants['aim']=target is None
        if (clip.get('how') or 'Camera move',float(clip['duration']))!=(new_how,new_secs):
            self.record_structure('camera move')
            clip['how']=None if new_how=='Camera move' else new_how
            clip['duration']=new_secs; camera_clips.fit(clip)
            self.project_changes.mark_changed()
        if wants['aim']:
            self.select_camera(cid)
            self.status.setText('Drag the frame on the preview to where the camera goes (mouse wheel: closer / '
                                'further). Click an empty spot of the timeline when it is right.')
        else:
            self.fill_camera_panel(); self.sync_camera_timeline(); self.refresh()

    def camera_clip_action(self,cid,action):
        clip=self.find_camera(cid)
        if clip is None: return
        if action=='delete':
            self.record_structure('delete camera clip')
            self.cameras=[c for c in self.cameras if c.get('id')!=cid]
            if self.selected_camera==cid: self.selected_camera=None
            self.status.setText('Camera clip deleted (Ctrl+Z brings it back).')
        else:
            import camera_clips
            self.record_structure('camera clip kind')
            camera_clips.set_kind(clip,action)
        self.project_changes.mark_changed()
        self.fill_camera_panel(); self.sync_camera_timeline(); self.refresh()

    def fill_camera_panel(self):
        """The Camera panel shows the chosen camera clip."""
        if not hasattr(self,'camera_clip_box'): return
        clip=self.find_camera(getattr(self,'selected_camera',None))
        self.camera_clip_box.setVisible(clip is not None)
        self.camera_clip_none.setVisible(clip is None)
        if clip is None: return
        self._filling_camera=True
        try:
            self.cam_clip_kind.setCurrentText(clip.get('kind') if clip.get('kind') not in ('Custom',__import__('camera_clips').CUSTOM) else 'Zoom in')
            self.cam_clip_start.setValue(float(clip['start']))
            a,b=float(clip.get('in_s',1.2)),float(clip.get('out_s',1.2))
            self.cam_clip_in.setValue(a); self.cam_clip_out.setValue(b)
            self.cam_clip_hold.setValue(max(0.,float(clip['duration'])-a-b))
            moving=clip.get('kind')!=__import__('camera_clips').FIXED     # exp.128: a fixed one stays
            for field in (self.cam_clip_hold,self.cam_clip_out):
                field.setVisible(moving)
                name=self.cam_clip_form.labelForField(field)
                if name is not None: name.setVisible(moving)
            pan=clip.get('from') is not None
            for key in ('to','from'):
                framing=clip.get(key) or (1.,.5,.5)
                for name,value in zip(('zoom','x','y'),framing):
                    field=self.cam_clip_fields[(key,name)]
                    field.setValue(round(value*100.))
                    if key=='from': field.parentWidget().setVisible(pan)
                if key=='from': self.cam_clip_fields[(key,'head')].setVisible(pan)
        finally:
            self._filling_camera=False

    def camera_panel_changed(self,what=None):
        if getattr(self,'_filling_camera',False): return
        clip=self.find_camera(getattr(self,'selected_camera',None))
        if clip is None: return
        if getattr(self,'_cam_recorded',None)!=('panel',clip['id']):
            self.record_structure('camera clip settings'); self._cam_recorded=('panel',clip['id'])
            QTimer.singleShot(1500,lambda: setattr(self,'_cam_recorded',None))
        import camera_clips
        if what=='kind':
            to=clip.get('to')
            camera_clips.set_kind(clip,self.cam_clip_kind.currentText())
            if to and clip['kind'] in camera_clips.MENU: clip['to']=tuple(to)     # exp.157: keeps its place
        else:
            clip['start']=round(self.cam_clip_start.value(),2)
            a,b,hold=self.cam_clip_in.value(),self.cam_clip_out.value(),self.cam_clip_hold.value()
            if camera_clips.fixed(clip): b,hold=0.,0.
            clip['in_s'],clip['out_s'],clip['duration']=round(a,2),round(b,2),round(a+hold+b,2)
            camera_clips.fit(clip)
            get=lambda key: tuple(self.cam_clip_fields[(key,n)].value()/100. for n in ('zoom','x','y'))
            clip['to']=get('to')
            if clip.get('from') is not None: clip['from']=get('from')
            # exp.157: a zoom keeps its kind wherever it looks (no more "zoom to a spot")
        self.project_changes.mark_changed()
        self.fill_camera_panel(); self.sync_camera_timeline(); self.refresh()

    def camera_box(self):
        """The chosen camera clip's framing as a frame on the preview (frame pixels)."""
        clip=self.find_camera(getattr(self,'selected_camera',None))
        if clip is None or self.canvas.frame is None or not self.all_scenes() or self.zoomed_out(): return None
        W,H=self.canvas.frame.width(),self.canvas.frame.height()
        z,x,y=clip.get('to') or (1.,.5,.5)
        w,h=W/max(.05,z),H/max(.05,z)            # exp.159: further than the page: bigger than it
        return (x*W-w/2,y*H-h/2,w,h)

    def drag_camera_frame(self,kind,dx,dy):
        clip=self.find_camera(getattr(self,'selected_camera',None))
        if clip is None: return False
        if kind=='start':
            box=self.camera_box()
            if box is None: return False
            bx,by,bw,bh=box
            if not (bx<=dx<=bx+bw and by<=dy<=by+bh): return False
            self.record_structure('move camera frame')
            self._cam_drag=tuple(clip.get('to') or (1.,.5,.5))
            return True
        start=getattr(self,'_cam_drag',None)
        if start is None: return False
        if kind=='move':
            z,x,y=start
            import camera_clips
            clip['to']=camera_clips.keep_in((z,x+dx,y+dy))
            if clip.get('kind') not in ('Zoom in','Zoom out','Fixed camera'): clip['kind']='Zoom in'   # exp.157
        else:
            self._cam_drag=None; self.project_changes.mark_changed()
        self.fill_camera_panel(); self.sync_camera_timeline(); self.canvas.update()
        return True

    def titles_for_element(self,k=None):
        """The texts / pictures on top in element k's own time (an export of that element alone)."""
        import copy
        try:
            start=self.element_start(k) if len(self.scenes)>1 else 0.
        except Exception:
            start=0.
        return [dict(copy.deepcopy(o),start=float(o.get('start',0))-start,
                     **({'_until':float(o['_until'])-start} if o.get('_until') is not None else {}))
                for o in self.visible_titles()]

    def titles_layer(self,width,height,seconds=None):
        """The texts / pictures on top at the playhead, on a clear picture (None: nothing).
        `seconds`: the time of the frame shown (playing: the video frame, exp.126)."""
        import overlays
        if self.board_mode(): return None
        t=self.video_seconds() if seconds is None else float(seconds)
        shown=self.visible_titles() if self.zoomed_out() else self.titles_split(t)[0]
        if not shown or not any(overlays.state_at(o,t) is not None for o in shown): return None
        layer=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); layer.fill(0)
        placed=self.text_view(t,width,height)          # exp.123: on their pages
        import timeline_render
        if placed is None:
            return timeline_render.paint_texts(layer,shown,t)
        frames,place,view=placed
        return timeline_render.paint_texts(layer,shown,t,frames,place,view)

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
        if at is not None:                    # whole-video seconds (exp.116)
            if self.all_scenes():
                self.position=max(0.,min(1.,at/max(.01,self.video_length())))
            else:
                start=self.element_start() if len(self.scenes)>1 else 0.
                self.position=max(0.,min(1.,(at-start)/max(.01,self.scene_seconds())))
        item=self.add_overlay(item)
        self.status.setText(f'Picture "{item["name"]}" added at {item["start"]:.1f} s with a {item["effect_in"]} '
                            'effect. Drag it on the preview to place it, double-click its clip for more.')
        return item

    def eraser_dialog(self,item=None):
        """exp.186: what an Eraser clip erases, how, and for how long. None when cancelled."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QComboBox, QDoubleSpinBox
        import eraser_clips
        dialog=QDialog(self); dialog.setWindowTitle('Eraser')
        form=QFormLayout(dialog)
        target=QComboBox()
        for k,s in enumerate(self.scenes):
            target.addItem(f'{k+1} · {self.scene_label(k)}',s.get('uid'))
        k0=eraser_clips.target_of(item,[dict(uid=s.get('uid')) for s in self.scenes]) if item else None
        if k0 is None:
            k0=self.scene_index           # the element being edited (chosen on the timeline)
        target.setCurrentIndex(max(0,min(len(self.scenes)-1,int(k0))))
        style=QComboBox(); style.addItems(list(eraser_clips.MODES))
        if item: style.setCurrentText({v:k for k,v in eraser_clips.MODES.items()}.get(item.get('mode'),'Zigzag (follows the shapes)'))
        length=QDoubleSpinBox(); length.setRange(.3,30.); length.setDecimals(1); length.setSingleStep(.5); length.setSuffix(' s')
        length.setValue(float(item.get('duration',3.)) if item else 3.)
        form.addRow(help_label('Erases','The element it rubs out (wherever it is on the board).'),target)
        form.addRow(help_label('How','Zigzag: back and forth over the picture. Along the lines: follows the lines it drew.'),style)
        form.addRow(help_label('How long','How long the erasing takes.'),length)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return None
        k=target.currentIndex()
        return dict(target=self.scenes[k].get('uid'),target_k=k,name=f'Erase {k+1} · {self.scene_label(k)}'[:40],
                    mode=eraser_clips.MODES[style.currentText()],duration=round(length.value(),2))

    def add_eraser(self):
        """exp.186: an Eraser clip at the playhead (whole video)."""
        import overlays
        if not self.drawing: return None
        if not self.all_scenes():
            self.preview_scope.setCurrentIndex(1); self.app_events()
        choice=self.eraser_dialog()
        if choice is None: return None
        item=overlays.new_eraser(choice['target'],choice['target_k'],choice['name'],mode=choice['mode'])
        item=self.add_overlay(item)
        item['duration']=choice['duration']
        self.project_changes.mark_changed(); self.refresh()
        self.status.setText('Eraser added. Drag it on the timeline to choose when; double-click it to change it.')
        return item

    def app_events(self):
        QApplication.processEvents()

    def add_overlay_text(self):
        import overlays
        if not self.drawing: return None
        item=self.add_overlay(overlays.new_text())
        self.edit_overlay(item['id'])
        return item

    def element_camera_marks(self,items=None):
        """exp.115: the elements' own cameras on the Camera row: [(k, start, length, until)],
        whole-video seconds; `until`: where the camera move after it has fully taken over."""
        try:
            lay=self.timeline_layout()
        except Exception:
            return []
        ends={m.k:m.end for m in lay.moves}
        marks=[]
        for it in lay.items:
            plan=self.preview_scene(it.k,960,540)[1].get('cam_plan')
            if not plan or (plan[0]<=100.01 and plan[3]<=100.01): continue
            begin,length=float(plan[6]),float(plan[7])
            start=it.start+begin
            until=ends.get(it.k,it.end)
            marks.append((it.k,start,length,until if start+length>until else None))
        return marks

    def edit_element_camera(self,k):
        """An element's own camera clicked on the timeline: that element, Camera panel."""
        if k!=self.scene_index: self.timeline_element_clicked(k)
        if self.scene_index==k and hasattr(self,'show_left_panel'):
            self.show_left_panel('camera')

    def go_to_overlay(self,k,oid):
        """Whole video: another element's text or picture clicked on the timeline: work on that
        element, with it chosen (the preview stays on the whole video)."""
        self.timeline_element_clicked(k)
        if self.scene_index==k and self.find_overlay(oid) is not None:
            self.select_overlay(oid)

    def find_overlay(self,oid):
        return next((o for o in self.overlays if o.get('id')==oid),None)

    def select_overlay(self,oid):
        """One text chosen ('' / None: none). exp.117: choosing one leaves the others."""
        if oid and getattr(self,'selected_camera',None):
            self.selected_camera=None; self.fill_camera_panel(); self.sync_camera_timeline()
        self.selected_overlay=oid or None
        self.selected_overlays={oid} if oid else set()
        self.sync_titles_choice()
        self.refresh()

    def toggle_overlay(self,oid):
        """Ctrl+click: add a text to the choice, or take it out."""
        chosen=set(getattr(self,'selected_overlays',set()))
        if self.selected_overlay: chosen.add(self.selected_overlay)
        if oid in chosen: chosen.discard(oid)
        else: chosen.add(oid)
        self.selected_overlays=chosen
        if self.selected_overlay not in chosen:
            self.selected_overlay=next(iter(chosen),None)
        if oid in chosen: self.selected_overlay=oid
        self.sync_titles_choice()
        self.refresh()

    def chosen_overlays(self):
        ids=set(getattr(self,'selected_overlays',set()))
        if self.selected_overlay: ids.add(self.selected_overlay)
        return [o for o in self.overlays if o.get('id') in ids]

    def sync_titles_choice(self):
        tl=self.stage_timeline
        tl.selected_overlay=self.selected_overlay
        tl.selected_overlays=set(getattr(self,'selected_overlays',set()))
        tl.update()

    def toggle_text_track(self,t):
        """A text track's hide button: its texts are not in the video (exp.117)."""
        hidden=set(getattr(self,'text_hidden',set()))
        self.record_structure('hide text track')
        if t in hidden: hidden.discard(t)
        else: hidden.add(t)
        self.text_hidden=hidden
        self.stage_timeline.text_hidden=set(hidden)
        self.project_changes.mark_changed()
        self.refresh()

    def visible_titles(self):
        """The texts in the video: not on a hidden track (exp.118: the element tracks' own
        hide buttons)."""
        self.mark_title_holds()
        hidden=set(getattr(self,'text_hidden',set()))
        hidden|={int(t) for t,f in (getattr(self,'track_flags',{}) or {}).items() if f.get('hidden')}
        return [o for o in self.overlays if int(o.get('track',0)) not in hidden]

    def mark_title_holds(self):
        """exp.123: a text lives on its page like the drawings: the page the camera shows when
        it starts ('_page'); with no way out it stays there to the end of the video ('_until'),
        so the camera can move away from it and come back to it."""
        if not self.overlays: return
        try:
            end=self.video_length()
            lay=self.timeline_layout() if len(self.scenes)>1 else None
        except Exception:
            end,lay=None,None
        import overlays as _ov
        import timeline_render
        for o in self.overlays:
            clip_end=_ov.end_of(o)
            o['_until']=round(max(clip_end,end or clip_end),3)
            try:
                o['_page']=timeline_render.page_of(lay,float(o.get('start',0))) if lay is not None else 0
            except Exception:
                o['_page']=0

    def text_view(self,seconds,width,height):
        """(frames, place, view) of the camera at `seconds` (whole video), for drawing the texts
        on their pages; None: on the screen as it is (This element, one element)."""
        if not self.all_scenes() or self.board_mode(): return None
        try:
            from timeline_model import state_at
            import timeline_render
            lay=self.timeline_layout()
            world=self.preview_world(width,height)
            elements=[]
            for k in range(len(self.scenes)):
                _,_,secs,camera=self.preview_scene(k,width,height)
                elements.append(dict(camera=self.video_camera(k,camera,secs),transition=self.scenes[k]['transition'],
                                     move_seconds=self.scenes[k]['transition_seconds']))
            view=timeline_render.view_of(world,lay,state_at(lay,seconds),elements)
            if self.zoomed_out():
                z=self.preview_zoom_out; px,py=getattr(self,'preview_pan',(0.,0.))
                w=view[2]*z; view=(view[0]+px*w,view[1]+py*w*world.aspect,w)
            return world.frames,world.place,view
        except Exception as exc:
            import applog; applog.error('Texts on their pages',exc)
            return None

    def text_rect(self,item,seconds,width,height):
        """Where the text's page is on the preview now (x, y, w, h)."""
        placed=self.text_view(seconds,width,height)
        if placed is None: return (0.,0.,float(width),float(height))
        frames,place,view=placed
        k=min(max(0,int(item.get('_page',0) or 0)),len(frames)-1)
        return place(frames[k],view,width,height)

    def titles_split(self,seconds):
        """(on top, under): the texts over every element being drawn at `seconds`, and the
        ones on a lower track than one of them (drawn inside the frame, under it)."""
        shown=self.visible_titles()
        if not self.all_scenes(): return shown,[]
        try:
            lay=self.timeline_layout()
            if lay.sequential: return shown,[]
            from timeline_model import state_at
            hidden=self.hidden_elements()
            tracks={it.k:it.track for it in lay.items}
            top=max([tracks[k] for k,_ in state_at(lay,seconds).active if k not in hidden],default=-1)
        except Exception:
            return shown,[]
        # exp.168 (the user): nothing is above the hand: every text goes into the picture (on its
        # track, under the elements of higher tracks), and the hand is drawn over all of it.
        return [],list(shown)

    def move_overlay_clip(self,oid,start,duration,track):
        item=self.find_overlay(oid)
        if item is None: return
        if not getattr(self,'_clip_recorded',None)==oid:          # one undo step per drag
            self.record_structure('move text'); self._clip_recorded=oid
            self._clip_from={o['id']:float(o.get('start',0)) for o in self.chosen_overlays()}
            self._clip_from[oid]=float(item.get('start',0))
        moved=abs(float(duration)-float(item.get('duration',3)))<1e-6
        item.update(start=start,duration=duration,track=track)
        if moved:                          # the other chosen texts move with it (exp.117)
            starts=getattr(self,'_clip_from',{})
            shift=float(start)-starts.get(oid,float(start))
            for o in self.chosen_overlays():
                if o is not item and o['id'] in starts:
                    o['start']=round(max(0.,starts[o['id']]+shift),2)
        self.project_changes.mark_changed()
        self.refresh()

    def overlay_clip_done(self,oid):
        self._clip_recorded=None

    def edit_overlay(self,oid):
        from overlay_dialog import OverlayDialog
        import copy
        item=self.find_overlay(oid)
        if item is None: return
        if item.get('kind')=='eraser':                  # exp.186
            choice=self.eraser_dialog(item)
            if choice is None: return
            self.record_structure('edit eraser'); item.update(choice)
            self.project_changes.mark_changed(); self.refresh(); return
        self.selected_overlay=oid
        before=copy.deepcopy(item)
        self.record_structure('text settings')
        dialog=OverlayDialog(self,item,max(item.get('duration',3)+item.get('start',0),self.video_length()),
                             changed=lambda it: self.refresh())
        dialog.exec()
        if dialog.deleted:
            self.overlay_action(oid,'delete',recorded=True); return
        if item==before and self.project_undo and self.project_undo[-1][3]=='text settings':
            self.project_undo.pop(); self.update_history_controls()      # nothing changed
        self.refresh()

    def overlay_action(self,oid,action,recorded=False):
        import copy, uuid
        item=self.find_overlay(oid)
        if item is None: return
        if action=='edit':
            self.edit_overlay(oid); return
        if not recorded: self.record_structure(action+' text')
        if action=='duplicate':
            twin=copy.deepcopy(item); twin['id']=uuid.uuid4().hex[:10]
            twin['track']=max(int(o.get('track',0)) for o in self.overlays)+1
            self.overlays.append(twin); self.selected_overlay=twin['id']; self.selected_overlays={twin['id']}
        elif action=='delete':
            gone={o['id'] for o in self.chosen_overlays()} if oid in {o['id'] for o in self.chosen_overlays()} else set()
            gone.add(oid)                  # exp.117: every chosen text goes
            self.overlays=[o for o in self.overlays if o.get('id') not in gone]
            if self.selected_overlay in gone: self.selected_overlay=None
            self.selected_overlays=set()
            self.status.setText(f'Overlay "{item.get("name","")}" deleted (Ctrl+Z brings it back).')
        self.project_changes.mark_changed(); self.refresh()

    def overlay_at(self,x,y):
        """The overlay shown at (x, y) of the preview now (the selected one first), or None."""
        import overlays
        if self.canvas.frame is None or not self.overlays: return None
        if self.board_mode() or self.zoomed_out(): return None
        W,H=self.canvas.frame.width(),self.canvas.frame.height()
        t=self.video_seconds()                   # in whole-video time (exp.116), on its page (exp.123)
        order=sorted(self.visible_titles(),key=lambda o: (o.get('id')!=self.selected_overlay,-int(o.get('track',0))))
        for item in order:
            if overlays.state_at(item,t) is None: continue
            rx,ry,rw,rh=self.text_rect(item,t,W,H)
            bx,by,bw,bh=overlays.box(item,W,H)
            bx,by,bw,bh=rx+bx*rw/W,ry+by*rh/H,bw*rw/W,bh*rh/H
            if bx-6<=x<=bx+bw+6 and by-6<=y<=by+bh+6:
                return item
        return None

    def overlay_box(self):
        """Dashed box around the selected overlay on the preview (frame pixels), or None.

        exp.114: asked while the preview is PAINTED, so it must never do real work there:
        in Whole video, finding the box needs the timeline of every element, which can load
        and plan elements and repaint the window (a paint inside a paint: StrokeScribe froze).
        The box is worked out just after the paint and kept until something changes."""
        key=(self.selected_overlay,round(float(self.position),5),self.scene_index,
             self.preview_scope.currentIndex(),
             None if self.canvas.frame is None else (self.canvas.frame.width(),self.canvas.frame.height()),
             repr(self.find_overlay(self.selected_overlay)) if self.selected_overlay else None)
        if self.zoomed_out() and self.canvas.frame is not None:
            # exp.121: zoomed out: the dashed frame is what the video shows (it can be hidden).
            if hasattr(self,'preview_frame_toggle') and not self.preview_frame_toggle.isChecked(): return None
            return self.camera_frame_rect(self.canvas.frame.width(),self.canvas.frame.height())
        if getattr(self,'selected_camera',None):
            return self.camera_box()                 # cheap: no timeline work
        cached=getattr(self,'_box_cache',None)
        if cached is not None and cached[0]==key:
            return cached[1]
        if not self.selected_overlay:
            self._box_cache=(key,None); return None
        if not getattr(self,'_box_pending',False):
            self._box_pending=True
            def work():
                self._box_pending=False
                if getattr(self,'_closed',False): return
                try:
                    box=self.compute_overlay_box()
                except Exception as exc:
                    import applog; applog.error('Overlay box',exc); box=None
                self._box_cache=(key,box)
                self.canvas.update()
            QTimer.singleShot(0,work)
        return cached[1] if cached is not None and cached[0][0]==key[0] else None

    def compute_overlay_box(self):
        import overlays
        item=self.find_overlay(self.selected_overlay) if self.selected_overlay else None
        if item is None or self.canvas.frame is None or self.board_mode(): return None
        t=self.video_seconds()
        if overlays.state_at(item,t) is None: return None
        W,H=self.canvas.frame.width(),self.canvas.frame.height()
        rx,ry,rw,rh=self.text_rect(item,t,W,H)
        bx,by,bw,bh=overlays.box(item,W,H)
        return (rx+bx*rw/W,ry+by*rh/H,bw*rw/W,bh*rh/H)

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
        if self.camera_editing() and (kind=='start' or getattr(self,'_cam_drag',None) is not None):
            if self.drag_camera_frame(kind,dx,dy): return True
        if self.zoomed_out() and (kind=='start' or getattr(self,'_pan_drag',None) is not None):
            # exp.122: zoomed out, drag the preview to look around (the video is not changed).
            if kind=='start':
                self._pan_drag=getattr(self,'preview_pan',(0.,0.)); self.playing=False; return True
            if kind=='move':
                z=self.preview_zoom_out; x0,y0=self._pan_drag
                limit=(z-1)/2+.5
                self.preview_pan=(max(-limit,min(limit,x0-dx)),max(-limit,min(limit,y0-dy)))
                self._playhead_only=True; self.refresh()
            else:
                self._pan_drag=None
            return True
        if self.board_mode() or (kind!='start' and getattr(self,'_board_drag',None)):
            return self.board_drag(kind,dx,dy)
        if kind=='start':
            item=self.overlay_at(dx,dy)
            if item is not None:
                self.playing=False
                if item['id'] not in getattr(self,'selected_overlays',set()):
                    self.selected_overlays={item['id']}
                self.selected_overlay=item['id']
                self.record_structure('move text on the screen')
                W,H=self.canvas.frame.width(),self.canvas.frame.height()
                rx,ry,rw,rh=self.text_rect(item,self.video_seconds(),W,H)
                self._overlay_drag=(item,float(item.get('x',.5)),float(item.get('y',.5)),W/max(1.,rw),H/max(1.,rh))
                return True
        drag=getattr(self,'_overlay_drag',None)
        if drag is not None and kind!='start':
            item,x0,y0,sx,sy=drag
            if kind=='move':
                item['x'],item['y']=round(x0+dx*sx,4),round(y0+dy*sy,4)
                self.refresh()
            else:
                self._overlay_drag=None; self.project_changes.mark_changed(); self.refresh()
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
        if not self.board_mode():
            item=self.overlay_at(x,y)
            if item is not None and add:
                self.toggle_overlay(item['id']); return
            if item is not None or self.selected_overlay or getattr(self,'selected_overlays',None):
                self.select_overlay(item['id'] if item is not None else None)
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
        self.status.setText(f'Selected: line {index+1}  •  Line order (Animation tab) moves, reverses, '
                            'deletes and times the selected lines.')

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
        self.speed.setEnabled(not paint_only)            # Draw time: update_applicable
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
        self.update_element_panels()
        self.update_applicable()

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
        if drawing is not None and not hasattr(drawing,'default_order'):
            drawing.default_order=[s.name for s in drawing.strokes]   # Line order: Default
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
        self.update_element_panels()
        self.update_painter_parts()
        self.reset_history()
        if getattr(self,'scenes',None) and not getattr(self,'_entering_scene',False):
            self.scenes[self.scene_index]['thumb']=None      # new artwork: new thumbnail
            if hasattr(self,'scene_list'): QTimer.singleShot(0,self.fill_scenes)
    def change_source(self,index):
        # This chooses an intake type, never replaces the current element.
        self.image_controls.setVisible(bool(index))
        self.update_element_panels()
        self.refresh()

    # ------------------------------------------------------------ projects
    PROJECT_SETTINGS=('paint_look','duration','speed','thickness','artwork_size','picture_x','picture_y','reveal_mode','blend_mode','artwork_opacity','paper_cleanup','paper_tolerance','paper_softness','color_fade',
                      'image_duration','image_animation','brush_width','stroke_spacing','color_hold',
                      'use_color','preserve_colors','showhand','left_handed','paint_left_handed','entrance','entrance_part','pause_after','show_paint_hand','handsize','ax','ay',
                      'res','fps','webm','webm_quality','mov','mp4','mp4_background','keep_png',
                      'sound_on','sound_volume','sound_preview','preview_background','image_detail',
                      'image_style','image_animation_style','clean_faint',
                      'erase_mode','erase_time','erase_size','eraser',
                      'camera','audio_volume','audio_offset','pen_ease','paint_hand','paint_hand_size','fast_export','export_layers','clean_color','export_done_sound',
                      'move_hand','move_hand_size','move_hand_gx','move_hand_gy','hand_rest','hand_rest_corner','hand_rest_travel','hand_under',
                      'cam_start_zoom','cam_start_x','cam_start_y','cam_end_zoom','cam_end_x','cam_end_y','cam_begin','cam_time',
                      'ink_on','ink_edges','ink_edge_size','ink_removal','ink_strength','ink_colour','look_colour_on','look_temperature','look_tint','look_saturation','look_light_on','look_exposure','look_brightness','look_contrast','look_highlights','look_shadows','look_whites','look_blacks')

    def project_state(self):
        """Everything needed to reopen this project: the edited scene plus all scenes."""
        from scenes import scenes_to_project
        self.settle_rev()
        self.store_scene(thumbnail=False)
        data=scenes_to_project(self.scene_state(),self.scenes,self.scene_index)
        flags={str(t):f for t,f in getattr(self,'track_flags',{}).items() if f.get('muted') or f.get('hidden')}
        if flags: data['track_flags']=flags
        if self.overlays:
            import copy
            data['titles']=[{k:v for k,v in o.items() if k not in ('_until','_page')} for o in copy.deepcopy(self.overlays)]   # exp.116
            if getattr(self,'text_hidden',None): data['text_hidden']=sorted(self.text_hidden)
        if getattr(self,'cameras',None):
            import copy
            data['cameras']=copy.deepcopy(self.cameras)        # exp.119: the Camera track
        data.pop('overlays',None)
        return data

    def scene_state(self):
        """Everything needed to reopen the scene being edited."""
        from projects import drawing_to_dict, qimage_to_b64, qimage_to_b64_cached, widget_value
        from tools_kit import hand_to_project
        image_source=self.is_image_artwork()
        state={'title':self.project_title,'source':'image' if image_source else 'svg',
               'element_kind':self.element_kind(),
               'drawing':drawing_to_dict(self.drawing),
               'settings':self.settings_state(),
               'hand':hand_to_project(getattr(self,'hand_builtin',False),self.hand),
               'letter':{'ink':self.letter_ink_color,'background':self.letter_bg_color},
               'audio':str(self.audio_path or '')}
        if image_source and self.image_result:
            r=self.image_result
            state['image']={'png':qimage_to_b64_cached(r.image),'filename':r.filename,'detail':r.detail,
                            'path':str(self.image_path or ''),'guide':str(self.image_guide or '')}
        else:
            original=getattr(self,'color_original',None)
            keep=original if original is not None else self.final_image
            state['color_png']=None if getattr(self.drawing,'svg_has_fill',False) and not self.color_path else qimage_to_b64_cached(keep)
            state['svg_color_override']=bool(getattr(self,'color_path',None))
        if self.paint_hand_path and Path(self.paint_hand_path).is_file():
            import base64
            state['paint_hand_png']=base64.b64encode(Path(self.paint_hand_path).read_bytes()).decode('ascii')
        move=getattr(self,'move_hand_path',None)
        if move and Path(move).is_file():
            import base64
            state['move_hand_png']=base64.b64encode(Path(move).read_bytes()).decode('ascii')
        metadata=getattr(self.drawing,'artwork_assets',None)
        if metadata:
            state['artwork']=metadata
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
            if path:
                folder=Path(path).parent
            else:
                import home_screen
                folder=home_screen.projects_folder()
                try: folder.mkdir(parents=True,exist_ok=True)
                except OSError: folder=Path.home()
            suggested=str(folder)+'/'+ \
                ''.join(c if c.isalnum() or c in ' -_' else '_' for c in self.project_title).strip()+projects.SUFFIX
            path,_=QFileDialog.getSaveFileName(self,'Save project',suggested,'StrokeScribe project (*.strokescribe)')
            if not path: return None
        try:
            state=self.project_state()
            path=projects.save(path,self.with_thumbs(state))
        except Exception as exc:
            QMessageBox.warning(self,'Save project',str(exc)); return None
        self.project_path=str(path)
        self.status.setText('Project saved: '+str(path))
        self.setWindowTitle(f'{Path(path).stem}  •  {DISPLAY_NAME}')
        self.remember_recent(path)
        self.keep_home_preview(path)
        self.project_changes.mark_saved(state)
        self._autosaved_signature=None
        self._autosaved=self.history.current
        import autosave; autosave.clear()
        return path

    def keep_home_preview(self,path):
        """A small picture of the project for its card on the Home screen."""
        try:
            if not path or self.drawing is None or not self.drawing.strokes: return False
            from scenes import thumbnail
            import home_screen
            return home_screen.store_preview(path,thumbnail(self.drawing,self.options(),width=home_screen.PREVIEW_W))
        except Exception as exc:
            import applog; applog.error('Home preview',exc)
            return False

    # ------------------------------------------------------------ Home screen
    def show_home(self):
        """The Home screen: new project, open, and every project as a card (exp.107)."""
        if getattr(self,'home',None) is None:
            import home_screen
            from version import APP_VERSION
            self.home=home_screen.HomeScreen(self.centralWidget(),version=APP_VERSION)
            self.home.new_requested.connect(self.home_new)
            self.home.open_requested.connect(self.home_open)
            self.home.back_requested.connect(self.hide_home)
            self.centralWidget().installEventFilter(self)
        self.home.hand=getattr(self,'hand',None)
        self.home.restyle()
        self.home.set_can_go_back(bool(getattr(self,'project_path',None)) or
                                  bool(self.drawing is not None and self.drawing.strokes))
        self.home.setGeometry(self.centralWidget().rect())
        self.home.refresh()
        self.home.show(); self.home.raise_(); self.home.setFocus()
        return self.home

    def hide_home(self):
        if getattr(self,'home',None) is not None:
            self.home.hide()

    def home_visible(self):
        return getattr(self,'home',None) is not None and self.home.isVisible()

    def quit_app(self):
        """File > Exit: close StrokeScribe even from inside a project."""
        self._quitting=True
        if not self.close():
            self._quitting=False

    def home_new(self):
        if self.new_project():
            self.hide_home()

    def home_open(self,path=''):
        if self.open_project(path or None):
            self.hide_home()

    def eventFilter(self,obj,event):
        from PySide6.QtCore import QEvent
        home=getattr(self,'home',None)
        if home is not None and obj is self.centralWidget() and event.type()==QEvent.Type.Resize:
            home.setGeometry(obj.rect())
        return super().eventFilter(obj,event)

    def with_thumbs(self,data):
        """exp.120: the elements' small pictures go into the saved file, so opening a project
        shows them at once (they were made again, one by one, every time)."""
        from projects import qimage_to_b64_cached
        data=dict(data)
        try:
            thumbs=[qimage_to_b64_cached(s.get('thumb')) if s.get('thumb') is not None else None for s in self.scenes]
            if 'scenes' in data:
                data['scenes']=[dict(item,thumb_png=t) if t else item for item,t in zip(data['scenes'],thumbs)]
            elif thumbs and thumbs[0]:
                data['thumb_png']=thumbs[0]
        except Exception as exc:
            import applog; applog.error('Element pictures for the project file',exc)
        return data

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
            autosave.save(self.with_thumbs(state),getattr(self,'project_path',None),self.project_title)
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
        self.hide_home()
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
        import time as _time
        began=_time.perf_counter()
        held=getattr(self,'_suspend_refresh',False); self._suspend_refresh=True   # exp.130: one preview at the end
        try:
            self.apply_project(data)
        except Exception as exc:
            self._suspend_refresh=held
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
        try:
            self.start_whole_video()
        finally:
            self._suspend_refresh=held
        if not held: self.refresh()
        self.remember_recent(path)
        QTimer.singleShot(400,lambda p=str(path): self.keep_home_preview(p) if self.project_path==p else None)
        # exp.130: the project's fingerprint (to know later whether it changed) is worked out
        # just after it shows, not before: it was most of the time spent opening.
        self.project_changes.mark_saved(); self.project_changes.saved_signature=None
        opened=(str(path),self.project_changes.revision)
        def fingerprint_later():
            if (getattr(self,'project_path',None),self.project_changes.revision)==opened and not self._closed:
                self.project_changes.mark_saved(self.project_state())
        QTimer.singleShot(1500,fingerprint_later)
        import applog
        applog.info('Opened a project of %d elements in %.1f s',len(self.scenes),_time.perf_counter()-began)
        self._autosaved_signature=None
        import autosave; autosave.clear()
        self._autosaved=self.history.current
        return True

    def start_whole_video(self):
        """exp.118: an opened project shows the whole video, from the beginning."""
        self.playing=False
        if len(self.scenes)>1: self.preview_scope.setCurrentIndex(1)
        self.position=0.
        self.slider.blockSignals(True); self.slider.setValue(0); self.slider.blockSignals(False)
        self.refresh()

    def apply_project(self,data):
        """Open project data: its scenes, then the scene that was being edited."""
        from scenes import scenes_from_project
        scene_list=scenes_from_project(data)
        index=max(0,min(len(scene_list)-1,int(data.get('scene_index',0) or 0)))
        main={k:v for k,v in data.items() if k not in ('scenes','scene_index','track_flags','titles','text_hidden','cameras')}
        self.text_hidden={int(t) for t in data.get('text_hidden') or ()}
        self.selected_overlays=set()
        self.track_flags={int(t):dict(f) for t,f in (data.get('track_flags') or {}).items()}
        import copy
        self.overlays=copy.deepcopy(data.get('titles') or [])
        import camera_clips
        self.cameras=[camera_clips.upgrade(dict(c,**{'from':tuple(c['from']) if c.get('from') else None,
                                                     'to':tuple(c.get('to') or (1.,.5,.5))}))
                      for c in copy.deepcopy(data.get('cameras') or [])]
        self.selected_camera=None
        self.selected_overlay=None
        self._legacy_titles=[]
        from projects import qimage_from_b64
        for k,scene in enumerate(scene_list):
            # exp.120: the pictures saved with the project (none: made after opening).
            try: scene['thumb']=qimage_from_b64(scene.pop('thumb_png',None))
            except Exception: scene['thumb']=None
            if k==index: scene['state']=None          # lives in the editor
            elif scene.get('state') and scene['state'].get('overlays'):
                state=dict(scene['state']); self._legacy_titles.append((k,list(state.pop('overlays'))))
                scene['state']=state
            if k!=index and scene.get('state') and (scene['state'].get('settings') or {}).get('camera')=='Zoom (start → end)':
                state=dict(scene['state']); settings=dict(state['settings'])
                self.__dict__.setdefault('_legacy_cameras',[]).append((k,dict(settings)))
                settings['camera']='Off'; state['settings']=settings; scene['state']=state
        self.scenes=scene_list; self.scene_index=index
        self._rev_fp=None
        self._scene_cache={}
        if not self._restoring:
            self.project_undo=[];self.project_redo=[]   # another project: nothing of this one to undo
        self.apply_scene_state(main)
        self.adopt_legacy_titles()
        self.sync_workspace()
        self.settle_rev()
        self.fill_scenes()
        self.make_missing_thumbs()

    def adopt_legacy_titles(self):
        """Texts saved inside elements (before exp.116) become the video's own clips, at the
        same moment of the whole video as before."""
        cams=getattr(self,'_legacy_cameras',None)
        if cams:
            self._legacy_cameras=[]
            try:
                starts={it.k:it.start for it in self.timeline_layout().items}
            except Exception:
                starts={}
            import camera_clips
            for k,st in cams:
                g=lambda key,d: float(st.get(key,d))
                ramp=g('cam_time',1.2)
                clip=camera_clips.new_clip(camera_clips.CUSTOM,starts.get(k,0.)+g('cam_begin',0.),ramp*2+2.)
                clip['in_s'],clip['out_s']=ramp,ramp
                clip['from']=(g('cam_start_zoom',100.)/100.,g('cam_start_x',50.)/100.,g('cam_start_y',50.)/100.)
                clip['to']=(g('cam_end_zoom',160.)/100.,g('cam_end_x',50.)/100.,g('cam_end_y',50.)/100.)
                self.cameras.append(clip)
        legacy=getattr(self,'_legacy_titles',None)
        if not legacy: return
        self._legacy_titles=[]
        try:
            starts={it.k:it.start for it in self.timeline_layout().items} if len(self.scenes)>1 else {0:0.}
        except Exception as exc:
            import applog; applog.error('Placing older texts',exc); starts={}
        for k,items in legacy:
            for o in items:
                self.overlays.append(dict(o,start=round(float(o.get('start',0))+starts.get(k,0.),2)))

    def apply_scene_state(self,data):
        from projects import drawing_from_dict, qimage_from_b64, set_widget_value
        self.playing=False
        settings_in=data.get('settings') or {}
        from camera import ZOOM_MODE
        if settings_in.get('camera')==ZOOM_MODE:
            # exp.115's element zoom becomes a camera clip (exp.119), at the same moment.
            self.__dict__.setdefault('_legacy_cameras',[]).append((self.scene_index,dict(settings_in)))
            data=dict(data,settings=dict(settings_in,camera='Off'))
        if data.get('overlays'):
            # Before exp.116 texts belonged to an element: they become the video's own clips
            # (apply_project / _enter_scene place them at the same moment).
            self.__dict__.setdefault('_legacy_titles',[]).append((self.scene_index,list(data['overlays'])))
        drawing=drawing_from_dict(data['drawing'])
        metadata=data.get('artwork') or getattr(drawing,'artwork_assets',None)
        managed=None
        if metadata:
            from artwork_assets import validate_assets,materialize_assets
            drawing.artwork_assets=validate_assets(metadata)
            managed=materialize_assets(drawing.artwork_assets)
        settings=data.get('settings',{})
        # Reset optional appearance fields while switching scenes so a legacy
        # image cannot inherit cleanup or opacity from the preceding element.
        settings=dict({'artwork_opacity':100,'paper_cleanup':False,
                       'paper_tolerance':22,'paper_softness':8,
                       # Older projects: slides came in without a hand.
                       'move_hand':False,'entrance_part':'The whole picture',
                       'paint_look':'Classic',          # exp.180: Paint look (older projects: Classic)
                       # exp.115: the element's own camera (older projects: none).
                       'cam_start_zoom':100.,'cam_start_x':50.,'cam_start_y':50.,'cam_end_zoom':160.,
                       'cam_end_x':50.,'cam_end_y':50.,'cam_begin':0.,'cam_time':1.2,
                       # Older projects: no Colour / Light / Ink on the page.
                       **__import__('picture_look').DEFAULTS,
                       # Older projects: one Left-handed switch for both hands.
                       'paint_left_handed':bool(settings.get('left_handed',False))},**settings)
        # Settings first (without a refresh storm), then the drawing.
        # The video's own settings (resolution, frame rate, formats, background) are one
        # for the whole project: switching elements keeps them (exp.100; elements could
        # end up with different resolutions, e.g. a page at 1920 × 1080 and the picture
        # on it at 2560 × 1440).
        from scenes import GLOBAL_SETTINGS
        keep=set(GLOBAL_SETTINGS) if getattr(self,'_entering_scene',False) else set()
        for name in self.PROJECT_SETTINGS:
            widget=getattr(self,name,None)
            if widget is None or name not in settings or name in keep: continue
            widget.blockSignals(True)
            set_widget_value(widget,settings[name])
            widget.blockSignals(False)
        if hasattr(self,'camera_mode_changed'): self.camera_mode_changed()
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
        self.move_hand_path=tools_kit.restore_paint_hand(settings.get('move_hand_path'),data.get('move_hand_png'))
        self.update_move_hand_label()
        for key in self.sound_files:
            path=settings.get(key)
            self.sound_files[key]=path if path and Path(path).is_file() else None
        self.update_sound_buttons()
        letter=data.get('letter',{})
        self.letter_ink_color=letter.get('ink',self.letter_ink_color)
        if 'background_color' not in keep:
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
            self.image_controls.show()
            self.color_note.setText(self.image_result.filename+' • original colors')
        else:
            self.image_result=None;self.image_path=None;self.image_guide=None
            self.source_type.blockSignals(True); self.source_type.setCurrentIndex(0); self.source_type.blockSignals(False)
            self.image_controls.hide()
            # The colour picture as saved; cleaned like a newly loaded PNG (an older
            # project may have kept a painted checkerboard or faint leftovers).
            self.color_path='from-project' if data.get('svg_color_override') else None
            from color_reveal import project_color
            self.color_original,self.final_image=project_color(data)
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

    def make_missing_thumbs(self):
        """After a project opens: the pictures of the elements not edited yet, one by one in
        the background of the window (exp.106: they only showed after being clicked)."""
        pending=[k for k,s in enumerate(self.scenes) if s.get('thumb') is None and s.get('state') is not None]
        if not pending: return
        token=object(); self._thumb_token=token

        def step():
            if getattr(self,'_closed',False) or getattr(self,'_thumb_token',None) is not token: return
            todo=[k for k,s in enumerate(self.scenes) if s.get('thumb') is None and s.get('state') is not None]
            if not todo:
                self.fill_scenes(); return
            k=todo[0]
            try:
                from scenes import job_from_state, thumbnail
                drawing,options,_=job_from_state(self.scenes[k]['state'],self.hand)
                self.scenes[k]['thumb']=thumbnail(drawing,options)
            except Exception as exc:
                import applog; applog.error(f'Picture of element {k+1}',exc)
                self.scenes[k]['thumb']=QImage()          # tried: not again
            if len(todo)==1 or len(todo)%3==0: self.fill_scenes()
            QTimer.singleShot(30,step)
        QTimer.singleShot(50,step)

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
        # exp.110: a "+" after the last element: add the next element there.
        plus=QListWidgetItem('Add\nelement')
        from ui_icons import icon as ui_icon
        import theme
        plus.setIcon(ui_icon('plus',theme.colors()['brand'],size=32))
        plus.setToolTip('Add a new element after the last one')
        plus.setData(Qt.ItemDataRole.UserRole,'add')
        self.scene_list.addItem(plus)
        self.scene_list.setCurrentRow(self.scene_index)
        self.scene_list.blockSignals(False)
        self.update_element_panels()          # the Source card shows the fresh thumbnail
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

    def settle_rev(self):
        """Bring the edited element's revision up to date (before it is left or saved)."""
        try:
            if self.drawing is None or not (0<=self.scene_index<len(self.scenes)): return
            self.__dict__.setdefault('_memo',{}).pop('edited_fp',None)    # what it shows now
            self.current_rev()
        except Exception:
            pass

    def _leave_scene(self):
        """Save the edited scene into the list before editing another one."""
        self.settle_rev()
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
        self._rev_fp=None                          # its saved revision holds until it changes
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
        saved=self.scenes[k].pop('history',None)   # its own undo history, kept while it was not edited
        if saved is not None:
            self.history=saved
            self.update_history_controls()
        self._scene_cache={key:v for key,v in self._scene_cache.items()
                           if any(id(s['state'])==key for s in self.scenes)}
        self.adopt_legacy_titles()
        self.sync_workspace()
        self.settle_rev()                  # as opened = as saved: its frames stay ready
        self.fill_scenes()
        self.refresh()

    def strip_plus_clicked(self):
        """The "+" after the last element in the strip: a new element after the last one."""
        self.scene_list.blockSignals(True)
        # exp.110: a "+" after the last element: add the next element there.
        plus=QListWidgetItem('Add\nelement')
        from ui_icons import icon as ui_icon
        import theme
        plus.setIcon(ui_icon('plus',theme.colors()['brand'],size=32))
        plus.setToolTip('Add a new element after the last one')
        plus.setData(Qt.ItemDataRole.UserRole,'add')
        self.scene_list.addItem(plus)
        self.scene_list.setCurrentRow(self.scene_index)
        self.scene_list.blockSignals(False)
        if not self.drawing or (self.builder and self.builder.isRunning()): return
        if self.scene_index!=len(self.scenes)-1:
            self.select_scene(len(self.scenes)-1)
            if self.scene_index!=len(self.scenes)-1: return
        from PySide6.QtGui import QCursor
        menu_at=getattr(self,'_strip_menu_at',None)
        if menu_at is not None: menu_at()
        else: self.add_element_menu(False,None)

    def select_scene(self,row):
        if row==len(self.scenes) and row>0:
            QTimer.singleShot(0,self.strip_plus_clicked); return
        if row<0 or row==self.scene_index or row>=len(self.scenes): return
        if (self.builder and self.builder.isRunning()) or not self.drawing:
            self.fill_scenes(); return
        self.playing=False
        # exp.130: the preview was drawn 3-4 times while the element was loaded (each part
        # asked for it); now once, at the end.
        held=getattr(self,'_suspend_refresh',False); self._suspend_refresh=True
        try:
            self._leave_scene()
            self._stash_history()
            self._enter_scene(row)
        finally:
            self._suspend_refresh=held
        if not self.all_scenes() and not held:
            self.refresh()
        if self.all_scenes():
            # Whole video: the playhead jumps to where this element ends (finished).
            try:
                # exp.110: the real length of the whole video (elements on tracks overlap), not
                # the sum of every element: with tracks the playhead landed on another element.
                lay=self.timeline_layout()
                it=lay.items[row]
                self.position=max(0.,min(1.,(it.start+it.length*.999)/max(1e-6,lay.total)))
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
        self.record_structure('add element')
        self._leave_scene()
        self._stash_history()
        current=self.scenes[self.scene_index]
        new=dict(state=copy.deepcopy(current['state']),transition=current['transition'],
                 transition_seconds=current['transition_seconds'],name=f'Element {len(self.scenes)+1}',
                 thumb=current.get('thumb'))
        self.scenes.insert(self.scene_index+1,new)
        self.project_changes.mark_changed()
        self._enter_scene(self.scene_index+1)
        self.status.setText(f'Scene {self.scene_index+1} added as a copy. Import an SVG or image for it '
                            '(Import, Library or Create image); its settings are its own.')

    def add_element_menu(self,same_spot=False,button=None,at=None):
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
        where=at if at is not None else button.mapToGlobal(button.rect().bottomLeft()) if button is not None else QCursor.pos()
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
            if self.drawing:
                (self.add_picture if same_spot else self.add_scene)()
                spot=(self.artwork_size.value(),self.picture_x.value(),self.picture_y.value())
                self.fresh_element_settings()            # exp.112: its own settings, from zero
                if same_spot:
                    for control,value in zip((self.artwork_size,self.picture_x,self.picture_y),spot):
                        control.setValue(value)
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
        self.record_structure('add picture on the same page')
        self._leave_scene()
        self._stash_history()
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
        self.record_structure(f'delete element {self.scene_index+1}')
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
        self.record_structure('move element')
        try:
            lay=self.timeline_layout()
            free=lay.sequential
            lengths,joins=(list(v) for v in self.scene_timeline())
        except Exception:
            lay,free=None,True
        if not free:
            # exp.126: elements placed on the timeline change places in time too (they collided).
            from timeline_model import swapped_places
            places=swapped_places(lay,k,j)
            for i,(start,track) in places.items():
                self.scenes[i]['start']=round(start,3); self.scenes[i]['track']=track
        self.scenes[k],self.scenes[j]=self.scenes[j],self.scenes[k]
        if not free:
            # A start that comes out the same with "right after the one before": keep it
            # following (so it still moves when an earlier element gets longer).
            from timeline_model import layout as _layout
            lengths[k],lengths[j]=lengths[j],lengths[k]; joins[k],joins[j]=joins[j],joins[k]
            for i in sorted((k,j)):
                kept=self.scenes[i].get('start')
                trial=[s.get('start') for s in self.scenes]; trial[i]=None
                tracks=[s.get('track') or 0 for s in self.scenes]
                if abs(_layout(lengths,joins,trial,tracks).items[i].start-float(kept))<1e-3:
                    self.scenes[i]['start']=None
        self.scene_index=j
        self.fill_scenes(); self.refresh()

    def scene_transition_changed(self):
        scene=self.scenes[self.scene_index]
        if (scene['transition'],scene['transition_seconds'])!=(self.scene_transition.currentText(),
                                                               self.scene_transition_time.value()):
            last=self.project_undo[-1] if self.project_undo else None
            # One undo step while the time is being changed, not one per arrow click.
            if not (last and last[3]=='transition' and self._undo_seq-last[0]<=1):
                self.record_structure('transition')
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
        self.preview_zoom_out=1.                  # exp.121: back to the camera's view
        self.preview_pan=(0.,0.)
        self.sync_zoom_controls()
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
            from scenes import apply_glide
            apply_glide(options,self.scenes[k])                  # exp.163: its own way there and back
            memo[key]=(self.drawing,options,seconds_of(self.drawing,options),self.preview_camera(options))
            return memo[key]
        state=self.scenes[k]['state']
        rest=self.hand_rest_settings()             # exp.143: the same for every element
        key=(id(state),width,height,over,tuple(sorted(rest.items())),tuple(self.scenes[k].get('glide') or ()))
        cached=self._scene_cache.get(id(state))
        if cached is None or cached[0]!=key:
            drawing,options,_=job_from_state(state,self.hand,overrides=rest)
            from scenes import apply_glide
            apply_glide(options,self.scenes[k])                  # exp.163: its own way there and back
            options.pop('fps',None); options.pop('audio',None)
            if over: options['background']=False
            options['hand_scale']/=options['artwork_scale']
            options['width'],options['height']=width,height
            options['ghost']=.22
            camera=None
            if options.get('camera_zoom',1.)>1.0001:
                from frame_render import camera_for
                camera=camera_for(drawing,options,options['camera_zoom'],rate=20.)
            if options.get('final_image') is not None and options.get('reveal_mode') in ('adaptive','zigzag','rows','columns','short_zigzag','painter'):
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
        self.canvas.frame=image; self.canvas.highlight=[]; self.canvas.titles_frame=None; self.canvas.update()
        segments,lengths,joins=self.whole_segments(960,round(960*aspect))
        self.show_whole_timeline(segments,lengths,joins,self.options())
        total=self.timeline_layout(960,round(960*aspect)).total
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
        from PySide6.QtWidgets import QApplication as _QA
        if _QA.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier and self.all_scenes():
            return self.zoom_preview(steps)
        clip=self.find_camera(getattr(self,'selected_camera',None)) if self.camera_editing() else None
        if clip is not None:                          # the camera frame: wheel to zoom
            if getattr(self,'_cam_wheel',None)!=clip['id']:
                self.record_structure('camera zoom'); self._cam_wheel=clip['id']
                QTimer.singleShot(800,lambda: setattr(self,'_cam_wheel',None))
            z,cx,cy=clip.get('to') or (1.,.5,.5)
            import camera_clips
            clip['to']=camera_clips.keep_in((z*(1.08**steps),cx,cy))     # exp.159: .2 x .. 10 x
            if clip.get('kind') not in ('Zoom in','Zoom out','Fixed camera'): clip['kind']='Zoom in'   # exp.157
            self.project_changes.mark_changed()
            self.fill_camera_panel(); self.sync_camera_timeline(); self.canvas.update()
            return True
        item=self.overlay_at(x,y)
        if item is None: return False
        if getattr(self,'_wheel_recorded',None)!=item['id']:
            self.record_structure('resize text'); self._wheel_recorded=item['id']
            QTimer.singleShot(800,lambda: setattr(self,'_wheel_recorded',None))
        item['size']=max(.01,min(3.,float(item.get('size',.3))*(1.08**steps)))
        self.selected_overlay=item['id']
        self.note_change(); self.refresh()
        return True

    def zoom_preview(self,steps):
        """exp.121: Ctrl + mouse wheel on the Whole video preview: step back to see the pages
        around the camera's view (the preview only; the video is not changed)."""
        old=getattr(self,'preview_zoom_out',1.)
        new=max(1.,min(12.,old*(1.18**(-steps))))
        if new<1.03: new=1.
        if abs(new-old)<1e-6: return True
        self.preview_zoom_out=new
        if new<=1.: self.preview_pan=(0.,0.)
        self.sync_zoom_controls()
        self.status.setText('Preview zoomed out ×%.1f: the dashed frame is what the video shows. '
                            'Ctrl + mouse wheel to zoom back in.'%new if new>1 else 'Preview back to the camera\'s view.')
        self.refresh()
        return True

    def reset_preview_view(self):
        """Back to what the video shows (exp.122)."""
        self.preview_zoom_out=1.; self.preview_pan=(0.,0.)
        self.sync_zoom_controls()
        self.status.setText('Preview back to the camera\'s view.')
        self.refresh()

    def sync_zoom_controls(self):
        zoomed=self.zoomed_out()
        for b in ('preview_frame_toggle','preview_reset_view'):
            if hasattr(self,b): getattr(self,b).setVisible(zoomed)

    def camera_frame_rect(self,W,H):
        """Zoomed out: where the video's frame is on the preview (frame pixels)."""
        z=getattr(self,'preview_zoom_out',1.)
        px,py=getattr(self,'preview_pan',(0.,0.))
        return (W/2-W/z/2-px*W,H/2-H/z/2-py*H,W/z,H/z)

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
        if (options.get('entrance') or 'draw')!='draw':
            # Comes in with an effect: one Move in clip (then the painting, when only the lines move in).
            import move_in
            from frame_render import move_seconds
            lines=move_in.part_of(options)==move_in.PART_LINES
            return [('move',move_seconds(options)),
                    ('paint',float(options.get('fade_duration',0)) if lines else 0.),
                    ('hold',(float(options.get('hold_duration',0)) if lines else 0.)+float(options.get('pause',0) or 0)),
                    ('erase',float(erase['seconds']) if erase else 0.)]
        return [('draw',float(options.get('duration',0))),
                ('paint',float(options.get('fade_duration',0)) if colour else 0.),
                ('hold',(float(options.get('hold_duration',0)) if colour else 0.)+float(options.get('pause',0) or 0)),
                ('erase',float(erase['seconds']) if erase else 0.)]

    def real_parts(self,k,length,width=960,height=540,last_stroke=True):
        """exp.176 (the user: on the timeline the hand went back before the painting ended):
        element k's parts at their real times. The element also holds the hand's glide in
        (before it draws) and the time it takes to go back; they used to be spread over Draw,
        Paint and Hold by stretching them, so the Paint part ended later than the painting
        really did. Now: Hand (glide in), Draw, Paint, Hold (the glide back is during it)."""
        drawing,options,_,_=self.preview_scene(k,width,height)
        parts=list(self.stage_parts(options))
        try:
            from frame_render import travel_plan
            plan=travel_plan(drawing,options) if (options.get('entrance') or 'draw')=='draw' else None
        except Exception:
            plan=None
        if plan is not None and plan[0]>0:
            lead=float(plan[0])
            rest=float(length)-lead-sum(v for _,v in parts)
            if rest>=-1e-3:
                parts=[('glide',lead)]+[(key,v+(rest if key=='hold' else 0.)) for key,v in parts]
                # The painting is over at the hand's last stroke (the brush plan ends a little
                # before the end of its time): Paint ends there, the rest is Hold, so the hand
                # goes back exactly when Paint ends.
                d=dict(parts); hand_end=float(plan[1])
                if last_stroke and d.get('paint',0)>0 and d.get('draw',0)<hand_end<d.get('draw',0)+d['paint']:
                    cut=d.get('draw',0)+d['paint']-hand_end
                    parts=[(key,v-cut if key=='paint' else v+cut if key=='hold' else v) for key,v in parts]
                if not any(key=='hold' for key,_ in parts) and rest>1e-3: parts.append(('hold',rest))
                return parts
        whole=sum(v for _,v in parts)
        if whole>0 and abs(whole-length)>1e-3:
            parts=[(key,v*length/whole) for key,v in parts]
        return parts

    def timeline_layout(self,width=960,height=540):
        """When every element plays in the whole video (timeline_model): its own start and
        track, or right after the element before it (exp.104)."""
        from timeline_model import layout
        lengths,joins=self.scene_timeline(width,height)
        memo=self.__dict__.setdefault('_memo',{})
        key=('layout',tuple(lengths),tuple(joins),tuple((s.get('start'),s.get('track')) for s in self.scenes))
        key=key+(repr(sorted(getattr(self,'track_flags',{}).items())),tuple(sorted(self.hidden_elements())))
        if key not in memo:
            lay=layout(lengths,joins,[s.get('start') for s in self.scenes],
                       [s.get('track') or 0 for s in self.scenes])
            if self.hidden_elements(): lay.sequential=False    # drawn moment by moment, without them
            memo[key]=lay
        return memo[key]

    def timeline_items(self,width=960,height=540):
        """(items, moves) for the timeline: [(k, label, start, seconds, track, parts)], [(k, label, start, seconds)]."""
        lay=self.timeline_layout(width,height)
        items=[]
        for it in lay.items:
            parts=self.real_parts(it.k,it.length,width,height)
            items.append((it.k,f'{it.k+1} · {self.scene_label(it.k)}',it.start,it.length,it.track,parts))
        moves=[(m.k,self.scenes[m.k]['transition'],m.start,m.length) for m in lay.moves]
        return items,moves

    def edit_camera_move(self,k):
        """exp.111: a camera move clicked on the timeline: how it moves and for how long; the
        Board places where the camera goes."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QComboBox, QDoubleSpinBox, QPushButton
        from scenes import TRANSITIONS
        if not 0<=k<len(self.scenes): return
        scene=self.scenes[k]
        last=k==len(self.scenes)-1
        dialog=QDialog(self); dialog.setWindowTitle('Camera')
        form=QFormLayout(dialog)
        goes=QWidget(); gl=QHBoxLayout(goes); gl.setContentsMargins(0,0,0,0)
        gl.addWidget(QLabel(f'Element {k+2}' if not last else 'Everything'),1)
        place=QPushButton('Board…'); place.setObjectName('subtle')
        place.setToolTip('Change where it is: the Board shows all the pages from above.')
        gl.addWidget(place)
        form.addRow(help_label('Goes to','Every element has its own place. After this element, the camera '
                               'travels to the next one. To change where that is, open the Board and move its frame.'),goes)
        kind=QComboBox(); kind.addItems(list(TRANSITIONS)); kind.setCurrentText(scene['transition'])
        form.addRow(help_label('Move','How the camera gets there: a camera move, a pan, a zoom, a fade, a cut. '
                               'Same page: it does not move.'),kind)
        secs=QDoubleSpinBox(); secs.setRange(.2,6); secs.setSingleStep(.1); secs.setDecimals(1)
        secs.setSuffix(' s'); secs.setValue(float(scene['transition_seconds']))
        form.addRow(help_label('Time','How long the trip takes. Longer = slower.'),secs)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        wants_board={'on':False}
        place.clicked.connect(lambda: (wants_board.update(on=True),dialog.accept()))
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        self.set_camera_move(k,kind.currentText(),secs.value())
        if wants_board['on']:
            target=min(k+1,len(self.scenes)-1)
            if target!=self.scene_index: self.select_scene(target)
            self.preview_scope.setCurrentIndex(2)

    def set_camera_move(self,k,kind,seconds):
        """The camera move after element k (one undo step)."""
        scene=self.scenes[k]
        if (scene['transition'],float(scene['transition_seconds']))==(kind,float(seconds)): return
        self.record_structure('camera move')
        scene['transition']=kind; scene['transition_seconds']=float(seconds)
        if k==self.scene_index:
            for widget,value in ((self.scene_transition,kind),(self.scene_transition_time,float(seconds))):
                widget.blockSignals(True)
                if widget is self.scene_transition: widget.setCurrentText(value)
                else: widget.setValue(value)
                widget.blockSignals(False)
        self.project_changes.mark_changed()
        self._base_cache=OrderedDict()
        self.fill_scenes(); self.refresh()
        self.status.setText(f'Camera after element {k+1}: {kind}, {float(seconds):.1f} s.')

    def restore_original_look(self):
        """exp.111: one button puts the picture back as it came in: size, position, blend,
        opacity, ink on the page, colour and light (one undo step)."""
        import picture_look
        changes=[(self.picture_x,0.),(self.picture_y,0.),(self.artwork_size,100.),(self.artwork_opacity,100.)]
        for widget,value in changes:
            widget.setValue(value)
        self.blend_mode.setCurrentText('Normal')
        for key,widget in getattr(self,'look_widgets',{}).items():
            value=picture_look.DEFAULTS.get(key)
            if value is None: continue
            if hasattr(widget,'setChecked') and isinstance(value,bool): widget.setChecked(value)
            elif hasattr(widget,'setValue'): widget.setValue(float(value))
        self.commit_history()
        self.status.setText('Picture restored to the original (Ctrl+Z brings your changes back).')

    def place_element(self,k,start,track):
        """Whole video: element k dragged to its own start and track (one undo step)."""
        if not 0<=k<len(self.scenes): return
        self.record_structure('move in time')
        scene=self.scenes[k]
        scene['start']=round(max(0.,float(start)),2); scene['track']=max(0,int(track))
        self.project_changes.mark_changed()
        self.status.setText(f'Element {k+1} starts at {scene["start"]:.1f} s on Track {scene["track"]+1}. '
                            'Right-click it on the timeline to put it back after the element before it.')
        self.fill_scenes(); self.refresh()

    def toggle_track(self,track,which):
        """A track's mute (its pencil / brush sounds) or hide (not in the video) button."""
        flags=self.__dict__.setdefault('track_flags',{})
        key={'mute':'muted','hide':'hidden'}[which]
        entry=flags.setdefault(int(track),{})
        entry[key]=not entry.get(key,False)
        self.project_changes.mark_changed()
        word={'muted':('muted','sounds on'),'hidden':('hidden from the video','shown')}[key]
        self.status.setText(f'Track {track+1} {word[0] if entry[key] else word[1]}.')
        self.__dict__.setdefault('_memo',{}).clear()
        self.refresh()

    def track_flag(self,scene,key):
        """Hidden / muted: by its track, or the element on its own (exp.106)."""
        return bool(scene.get(key)) or \
            (getattr(self,'track_flags',{}) or {}).get(scene.get('track') or 0,{}).get(key,False)

    def toggle_element_flag(self,k,which):
        if not 0<=k<len(self.scenes): return
        key={'mute':'muted','hide':'hidden'}[which]
        scene=self.scenes[k]
        scene[key]=not scene.get(key,False)
        if not scene[key]: scene.pop(key,None)
        self.project_changes.mark_changed()
        word={'muted':('muted','sounds on'),'hidden':('hidden from the video','shown')}[key]
        self.status.setText(f'Element {k+1} {word[0] if scene.get(key) else word[1]}.')
        self.__dict__.setdefault('_memo',{}).clear()
        self.refresh()

    def hidden_elements(self):
        """Elements on hidden tracks (not drawn in the whole video or the export)."""
        flags=getattr(self,'track_flags',{}) or {}
        hidden={t for t,f in flags.items() if f.get('hidden')}
        return {k for k,s in enumerate(self.scenes) if (s.get('track') or 0) in hidden or s.get('hidden')}

    def reset_element_time(self,k):
        if not 0<=k<len(self.scenes): return
        self.record_structure('move in time')
        self.scenes[k].pop('start',None); self.scenes[k].pop('track',None)
        self.project_changes.mark_changed()
        self.status.setText(f'Element {k+1} starts right after the element before it again, on Track 1.')
        self.fill_scenes(); self.refresh()

    def whole_segments(self,width=960,height=540):
        """The whole video for the timeline: elements (with their parts) and camera moves."""
        lengths,joins=self.scene_timeline(width,height)
        segments=[]
        for n,(length,join) in enumerate(zip(lengths,joins)):
            parts=self.real_parts(n,length,width,height)     # exp.176: at their real times
            segments.append((f'{n+1} · {self.scene_label(n)}',length,'scene',parts))
            if join>0: segments.append((self.scenes[n]['transition'],join,'join',()))
        return segments,lengths,joins

    def show_whole_timeline(self,segments,lengths,joins,options):
        """Whole video on the timeline; the edited element keeps its edges, pictures and audio."""
        tl=self.stage_timeline
        items,moves=self.timeline_items()
        tl.set_scenes(segments,current=self.scene_index,items=items,moves=moves,
                      flags=getattr(self,'track_flags',{}),
                      element_flags={k:{key:True for key in ('hidden','muted') if s.get(key)}
                                     for k,s in enumerate(self.scenes) if s.get('hidden') or s.get('muted')})
        self.sync_titles_timeline(force=True)
        tl.cam_marks=self.element_camera_marks(items)
        tl.set_audio(self.timeline_audio())
        tl.editable={'draw','paint','hold','erase'} if self.duration.isEnabled() else {'paint','hold','erase'}
        length=lengths[self.scene_index]
        mine=dict(self.real_parts(self.scene_index,length,last_stroke=False))   # the settings' own times
        tl.lead=mine.pop('glide',0.)          # exp.176: the hand's glide in, before Draw
        tl.hold_extra=max(0.,mine.get('hold',0.)-dict(self.stage_parts(options)).get('hold',0.))
        moving='move' in mine
        tl.update_state(mine['move' if moving else 'draw'],mine['paint'],mine['hold'],self.position,mine['erase'],
                        first='Move in' if moving else 'Draw')

    def element_start(self,k=None):
        """Whole video: the second where element k starts."""
        k=self.scene_index if k is None else k
        return self.timeline_layout().items[k].start

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

    def zoomed_out(self):
        return getattr(self,'preview_zoom_out',1.)>1. and self.all_scenes()

    def all_scenes_frame(self,width,height,fraction=None):
        """Preview frame of the whole video at the playhead (or at `fraction`): the camera
        over the board, as in the export."""
        import board
        lengths,joins=self.scene_timeline(width,height)
        lay=self.timeline_layout(width,height)
        if not lay.sequential or self.zoomed_out():
            from timeline_model import state_at
            at=(self.position if fraction is None else fraction)*lay.total
            state=state_at(lay,at)
            k=state.current if state.kind=='page' else state.move
            zoom=self.zoomed_out()
            return self.timeline_frame(state,width,height,at,
                                       view_scale=self.preview_zoom_out if zoom else 1.,
                                       view_pan=getattr(self,'preview_pan',(0.,0.)) if zoom else (0.,0.)),k,lengths,joins
        total=sum(lengths)+sum(joins)
        where,k,f=board.locate(lengths,joins,(self.position if fraction is None else fraction)*total)
        return self.whole_frame_at(where,k,f,width,height),k,lengths,joins

    def timeline_frame(self,state,width,height,seconds=None,view_scale=1.,view_pan=(0.,0.)):
        """Whole video with elements on tracks: one moment (timeline_render); texts under an
        element of a higher track are drawn in it (the others: on the screen, titles_layer)."""
        import timeline_render
        world=self.preview_world(width,height)
        elements=[]
        for k in range(len(self.scenes)):
            # exp.169: its own length in `length` (it was `seconds`, which replaced the moment
            # shown: the texts were drawn as at the last element's length, the first one too
            # early and the later ones never).
            drawing,options,length,camera=self.preview_scene(k,width,height)
            camera=self.video_camera(k,camera,length)            # exp.119: the camera clips
            options=dict(options,**self.hand_video(k))           # exp.147: the Hand row
            elements.append(dict(drawing=drawing,options=options,camera=camera,uid=self.scenes[k].get('uid'),
                                 transition=self.scenes[k]['transition'],
                                 move_seconds=self.scenes[k]['transition_seconds']))
        hidden=self.hidden_elements()
        if hidden:
            from dataclasses import replace
            active=[(k,f) for k,f in state.active if k not in hidden]
            state=replace(state,active=active,finished=[k for k in state.finished if k not in hidden],
                          top=active[-1][0] if active else -1)
        under=self.titles_split(seconds)[1] if seconds is not None and view_scale<=1. else []
        return timeline_render.compose(world,self.timeline_layout(width,height),state,elements,width,height,
                                       titles=under,seconds=seconds,view_scale=view_scale,view_pan=view_pan)

    def whole_frame_at(self,where,k,f,width,height):
        """Whole video: element k at its own fraction f, or the move after element k."""
        import board
        from scenes import transition_frame
        if where=='scene':
            drawing,options,seconds,camera=self.preview_scene(k,width,height)
            camera=self.video_camera(k,camera,seconds)          # exp.119: the camera clips
            from artwork_compositor import composite_element
            under=self.scene_base(k,width,height,f,camera)
            return composite_element(under,drawing,f,dict(options,**self.hand_video(k)),camera)
        world=self.preview_world(width,height)
        if self.preview_scene(k,width,height)[1].get('layers')=='hand':
            from PySide6.QtGui import QImage
            blank=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); blank.fill(0)
            return blank
        kind=self.scenes[k]['transition']
        last=k==len(self.scenes)-1
        if kind in board.SCREEN_KINDS and not last:
            a=world.view(world.frames[k],width,height,upto=k+1)
            b=world.view(world.frames[k+1],width,height,upto=k+1)
            return transition_frame(a,b,kind,f)
        def cam(j):
            if not 0<=j<len(self.scenes): return None
            _,_,seconds,camera=self.preview_scene(j,width,height)
            return self.video_camera(j,camera,seconds)
        view=board.join_view(world.frames,k,kind,f,world.aspect,self.scenes[k]['transition_seconds'],
                             leaving=cam(k),arriving=cam(k+1))
        return world.view(view,width,height,upto=k+1)

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
        self.import_image_button.setEnabled(False)
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
        self.import_image_button.setEnabled(True)
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

    def update_ink_swatch(self):
        """Ink colour field: a swatch of the colour and its hex code."""
        from PySide6.QtGui import QPixmap,QIcon
        color=str(getattr(self,'letter_ink_color','#25364A') or '#25364A')
        swatch=QPixmap(18,18);swatch.fill(QColor(color))
        self.font_color_button.setIcon(QIcon(swatch))
        self.font_color_button.setText(color.upper())

    def choose_letter_color(self):
        color=QColorDialog.getColor(QColor(self.letter_ink_color),self,'Letter ink color')
        if not color.isValid():return
        self.letter_ink_color=color.name()
        self.update_ink_swatch()
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
        """Move up / down: every selected line one place (several at once)."""
        if not self.drawing:return
        rows=self.selected_rows() or ([self.order.currentRow()] if self.order.currentRow()>=0 else [])
        strokes=list(self.drawing.strokes)
        chosen=set(rows)
        for i in (rows if direction<0 else reversed(rows)):
            j=i+direction
            if not 0<=j<len(strokes) or j in chosen: continue
            strokes[i],strokes[j]=strokes[j],strokes[i]
            chosen.discard(i);chosen.add(j)
        if not chosen: return
        self.change_lines(strokes,keep={id(strokes[k]) for k in chosen},current=min(chosen))

    def open_line_order(self):
        """The Line order window; its order is applied as one undo step."""
        if not self.drawing or not self.drawing.strokes:
            self.status.setText('Add a picture first: there are no lines to order yet.');return None
        from line_order_dialog import LineOrderDialog
        dialog=LineOrderDialog(self)
        drawing=self.drawing
        def done(result):
            if result and drawing is self.drawing:
                paint=dialog.painting_order()
                circles=dialog.painting_circles()
                paint_changed=(paint!=getattr(drawing,'paint_part_order',None) or
                               circles!=getattr(drawing,'paint_circles',None) or getattr(dialog,'saved_changed',False))
                if paint_changed:
                    if paint: drawing.paint_part_order=paint
                    elif hasattr(drawing,'paint_part_order'): del drawing.paint_part_order
                    if circles: drawing.paint_circles=circles
                    elif hasattr(drawing,'paint_circles'): del drawing.paint_circles
                # A painting order is painted by Painter: use it, so the order is never
                # set and then silently ignored (exp.100).
                switched=False
                if (paint or circles) and getattr(dialog,'parts_changed',False) and \
                        self.reveal_mode.currentText()!=self.PAINTER_TEXT:
                    i=self.reveal_mode.findText(self.PAINTER_TEXT)
                    if i>=0:
                        self.reveal_mode.setCurrentIndex(i); switched=True
                lines=dialog.strokes
                if [id(s) for s in lines]!=[id(s) for s in drawing.strokes]:
                    keep={id(lines[i]) for i in dialog.line_selection if i<len(lines)}
                    self.change_lines(lines,keep=keep,current=min(dialog.line_selection) if dialog.line_selection else None,
                                      status='Order changed. Undo (Ctrl+Z) puts the lines back.')
                elif paint_changed:
                    self.project_changes.mark_changed();self.note_change()
                    self.status.setText('Painting order changed.');self.refresh()
                if switched:
                    self.status.setText('Painting order changed. This element now paints with Painter, '
                                        'which follows your order. Undo (Ctrl+Z) puts it back.')
            if getattr(dialog,'saved_changed',False):
                self.project_changes.mark_changed()     # saved orders are kept even after Cancel
            self.line_order_dialog=None
            dialog.deleteLater()
        dialog.finished.connect(done)
        self.line_order_dialog=dialog
        dialog.open()
        return dialog
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
        if hasattr(self,'builtin_tool') and name in ('hand','pencil','marker'):
            self.builtin_tool.blockSignals(True)
            self.builtin_tool.setCurrentIndex(('hand','pencil','marker').index(name))
            self.builtin_tool.blockSignals(False)
        _,tip,size=tools_kit.BUILTIN[name]
        for widget,value in ((self.ax,tip[0]),(self.ay,tip[1]),(self.handsize,size)):
            widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
        self.note_change()
        self.refresh()

    def update_paint_hand_label(self):
        import tools_kit
        choice=self.paint_hand.currentText()
        library=choice==tools_kit.PAINT_LIBRARY
        if hasattr(self,'paint_hand_form'):
            self.paint_hand_form.setRowVisible(self.paint_hand_choose,library)
            self.paint_hand_form.setRowVisible(self.paint_hand_name,library)
        else:
            self.paint_hand_choose.setVisible(library)
        # "Same as drawing hand" paints with the drawing hand at its own size,
        # so a separate size only exists for a different painting hand.
        self.paint_hand_size.setEnabled(True)
        if hasattr(self,'paint_hand_form'):
            self.paint_hand_form.setRowVisible(self.paint_hand_size,choice!=tools_kit.PAINT_SAME)
        if library:
            name=Path(self.paint_hand_path).stem if self.paint_hand_path else 'none chosen yet'
            missing=self.paint_hand_path and not Path(self.paint_hand_path).is_file()
            self.paint_hand_name.setText('Painting hand: '+name+(' (file missing: using the drawing hand)' if missing else ''))
        else:
            self.paint_hand_name.setText('')
        self.sync_hand_sides()

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

    # ------------------------------------------------------------ move-in hand
    def update_entrance_controls(self):
        """'Moves in' only matters when the element comes in with an effect."""
        self.update_applicable()

    def update_applicable(self):
        """Grey out what cannot apply to this element, so nothing looks clickable for nothing.

        * Comes in with an effect (Fade in, Slide in…): the hand does not draw, so Draw time
          becomes Move-in time and Pen movement does not apply; the painting settings apply
          only when "only the lines" move in and the colours are painted after.
        * No colours to paint: the painting settings do not apply.
        * Goes out Off: the out time and eraser settings do not apply; Fade/Pop/… out show
          no eraser, so only the out time applies."""
        if not hasattr(self,'entrance_part') or not hasattr(self,'timing_form'): return
        self.sync_entrance_switches()
        effect=self.entrance.currentIndex()!=0
        lines_only=self.entrance_part.currentIndex()==1
        image=self.is_image_artwork() if hasattr(self,'is_image_artwork') else False
        if image:
            colours=self.preserve_colors.isChecked() or self.image_animation.currentIndex()==1
            if self.image_animation.currentIndex()==2: colours=False          # Drawing only
        else:
            colours=self.use_color.isChecked() and self.use_color.isEnabled()
        painting=colours and (not effect or lines_only)
        def able(widget,on,why):
            if not hasattr(widget,'_tip'): widget._tip=widget.toolTip()
            widget.setEnabled(on)
            widget.setToolTip(widget._tip if on else f'Not used now: {why}')
        if not hasattr(self.duration,'_tip'): self.duration._tip='How long the hand takes to draw the lines.'
        paint_only=image and self.image_animation.currentIndex()==1
        able(self.duration,not effect and not paint_only,
             'Paint Only: no lines are drawn.' if paint_only and not effect else
             'Drawing is off: the element comes in with Move in (see Move-in time).')
        able(self.pen_ease,not effect,'Drawing is off: the element comes in with an effect, the hand does not draw it.')
        if hasattr(self,'move_time'):
            able(self.entrance,effect,'Drawing is on: the hand draws this element. Turn on Move in to choose an effect.')
            able(self.move_time,effect,'Drawing is on: Draw time is used.')
        able(self.entrance_part,effect and colours,
             'turn on Move in (and have colours) to pick what moves in.')
        why='there are no colours to paint.' if not colours else \
            'the whole picture moves in with its colours (choose "Only the lines" in Moves in to paint them).'
        for widget in (self.reveal_mode,self.color_fade,self.image_duration,self.brush_width,
                       self.stroke_spacing,self.color_hold):
            able(widget,painting,why)
        if hasattr(self,'painter_parts_buttons'):
            able(self.painter_parts_buttons,painting,why)
        able(self.camera,not effect or painting,'nothing is drawn or painted for the camera to follow.')
        erase=self.erase_mode.currentText()
        if hasattr(self,'erase_on') and self.erase_on.isChecked()!=(erase!='Off'):
            self.erase_on.blockSignals(True); self.erase_on.setChecked(erase!='Off'); self.erase_on.blockSignals(False)
            if hasattr(self,'section_out') and self.section_out.switch is not None: self.section_out.switch.update()
        if erase!='Off': self._last_erase=erase
        rubbing=erase in ('Zigzag (follows the shapes)','Along the lines')
        able(self.erase_time,erase!='Off','"Goes out" is Off.')
        able(self.erase_size,rubbing,'only an eraser that rubs (Zigzag or Along the lines) has a size.')
        able(self.eraser,rubbing,'only an eraser that rubs (Zigzag or Along the lines) is shown.')

    def sync_entrance_switches(self):
        """The Drawing and Move in switches show the stored "Comes in" (after a project,
        undo or element switch too): Drawing on = drawn by the hand."""
        if not hasattr(self,'draw_on'): return
        drawn=self.entrance.currentIndex()==0
        if not drawn: self._last_entrance=self.entrance.currentText()
        if hasattr(self,'move_time') and abs(self.move_time.value()-self.duration.value())>1e-9:
            self.move_time.blockSignals(True); self.move_time.setValue(self.duration.value())
            self.move_time.blockSignals(False)
        for box,on in ((self.draw_on,drawn),(self.move_in_on,not drawn)):
            if box.isChecked()!=on:
                box.blockSignals(True); box.setChecked(on); box.blockSignals(False)
        for section in ('section_drawing','section_move_in'):
            sec=getattr(self,section,None)
            if sec is not None and sec.switch is not None: sec.switch.update()

    def sync_hand_sides(self):
        """The Right | Left switches after a project, undo or element switch, and the
        painting hand's switch following the drawing hand when it is the same hand."""
        import tools_kit
        if not hasattr(self,'paint_left_handed_toggle'): return
        same=self.paint_hand.currentText()==tools_kit.PAINT_SAME
        if same and self.paint_left_handed.isChecked()!=self.left_handed.isChecked():
            self.paint_left_handed.blockSignals(True)
            self.paint_left_handed.setChecked(self.left_handed.isChecked())
            self.paint_left_handed.blockSignals(False)
        self.paint_left_handed_toggle.setEnabled(not same)
        self.left_handed_toggle.sync();self.paint_left_handed_toggle.sync()

    def update_move_hand_label(self):
        if not hasattr(self,'move_hand_name'): return
        path=getattr(self,'move_hand_path',None)
        if not path:
            self.move_hand_name.setText('Hand: built-in (placeholder)')
        elif not Path(path).is_file():
            self.move_hand_name.setText(f'Hand: {Path(path).stem} (file missing; using the built-in hand)')
        else:
            self.move_hand_name.setText('Hand: '+Path(path).stem)
        if hasattr(self,'move_in_hand_name'):
            self.move_in_hand_name.setText(self.move_hand_name.text().replace('Hand: ','')
                                           .replace('built-in (placeholder)','Built-in hand'))
        self.move_hand_builtin.setEnabled(bool(path))
        self.update_entrance_controls()
        self.sync_hand_sides()

    def choose_move_hand(self):
        name,_=QFileDialog.getOpenFileName(self,'Choose the move-in hand','','Pictures (*.png *.webp)')
        if name: self.set_move_hand(self.keep_in_library('hands',name))

    def set_move_hand(self,path):
        """The move-in hand (None: the built-in one). A new picture gets its grip found by itself."""
        import move_in
        if path:
            image=QImage(str(path))
            if image.isNull():
                QMessageBox.warning(self,'Move-in hand','Could not read this hand image.'); return
            import tools_kit
            gx,gy=tools_kit.tip_for_image(image)
        else:
            gx,gy=move_in.DEFAULT_GRIP
        self.move_hand_path=str(path) if path else None
        for box,value in ((self.move_hand_gx,gx),(self.move_hand_gy,gy)):
            box.blockSignals(True); box.setValue(float(value)); box.blockSignals(False)
        self.update_move_hand_label()
        self.note_change()
        self.refresh()
        self.show_hand_pictures()

    # ------------------------------------------------------------ AI parts (Painter)
    PAINTER_TEXT='Painter — real parts, strokes follow the shape'

    def update_painter_parts(self):
        """The Parts row shows only for Painter: which parts it paints, and the AI button."""
        if not hasattr(self,'painter_parts_buttons'): return
        # exp.184 (the user: preview it first, like the paint modes): Parts are chosen in the
        # Paint mode window, with a preview; the row here only says which ones are used.
        painter=self.reveal_mode.currentText()==self.PAINTER_TEXT
        self.paint_form.setRowVisible(self.painter_parts_note,False)
        self.paint_form.setRowVisible(self.painter_parts_buttons,False)
        found=getattr(self.drawing,'ai_parts_image',None) if self.drawing is not None else None
        count=getattr(self.drawing,'ai_parts_count',None) if found is not None else None
        self.painter_parts_note.setText(
            f'Parts: {count or "the"} real parts found by the AI' if found is not None
            else 'Parts: colour areas. "AI parts" lets the AI find the real objects instead.')
        self.colour_parts_button.setEnabled(found is not None)
        self.find_parts_button.setEnabled(self.drawing is not None and not getattr(self,'_finding_parts',False))

    def parts_picture(self):
        """The colour picture Painter paints (PIL RGBA), or None."""
        image=self.options().get('final_image')
        if image is None or image.isNull(): return None
        from adaptive_hand import pil_image
        return pil_image(image)

    def find_ai_parts(self,on_found=None,parent=None):
        """Segment Anything finds the picture's parts (downloads the model the first time).
        on_found(labels): exp.184, the Paint mode window previews them before they are used."""
        parent=parent or self
        import ai_engine, ai_parts, hashlib, threading
        if self.drawing is None: return
        picture=self.parts_picture()
        if picture is None:
            QMessageBox.information(parent,'Find real parts','This element has no colours to paint, so there are no parts to find.')
            return
        paths=ai_engine.Paths()
        if not ai_parts.engine_ready(paths):
            QMessageBox.information(parent,'Find real parts',
                'The AI engine is not installed yet. Set it up once from the AI panel '
                '(Create image with AI), then come back here.')
            return
        need=not ai_parts.model_ready(paths)
        if need and QMessageBox.question(parent,'Find real parts',
                f'The first time, StrokeScribe downloads Segment Anything by Meta '
                f'({ai_parts.download_size_gb():.1f} GB, licence {ai_parts.LICENSE}). '
                'After that it finds the parts of a picture in a few seconds on your graphics card.\n\n'
                'Download it now?')!=QMessageBox.StandardButton.Yes:
            return
        from PySide6.QtWidgets import QProgressDialog
        dialog=QProgressDialog('Finding the parts…','Cancel',0,0,parent)
        dialog.setWindowTitle('Find real parts');dialog.setMinimumDuration(0)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        state=dict(done=False,error=None,labels=None,progress=None,text='Finding the parts…',cancel=False)
        dialog.canceled.connect(lambda: state.__setitem__('cancel',True))
        drawing=self.drawing
        def work():
            try:
                if need:
                    def report(done,total,name):
                        state['progress']=(done,total);state['text']=f'Downloading Segment Anything… {done/1024**3:.2f} of {total/1024**3:.2f} GB'
                    ai_parts.download(paths,report,lambda: state['cancel'])
                state['progress']=None;state['text']='Finding the parts…'
                state['labels']=ai_parts.find_parts(paths,picture,cancelled=lambda: state['cancel'])
            except Exception as exc:
                state['error']=exc
            finally:
                state['done']=True
        self._finding_parts=True;self.update_painter_parts()
        threading.Thread(target=work,daemon=True).start()
        timer=QTimer(self);timer.setInterval(150)
        def poll():
            dialog.setLabelText(state['text'])
            if state['progress']:
                done,total=state['progress'];dialog.setMaximum(1000);dialog.setValue(round(done*1000/max(1,total)))
            else:
                dialog.setMaximum(0)
            if not state['done']: return
            timer.stop();dialog.reset();dialog.close();self._finding_parts=False
            if state['error'] is not None:
                if not isinstance(state['error'],(InterruptedError,ai_engine.Cancelled)) and not state['cancel']:
                    import applog;applog.error('Find real parts',state['error'])
                    QMessageBox.warning(parent,'Find real parts',str(state['error']))
                self.update_painter_parts();return
            labels=state['labels']
            if drawing is not self.drawing:          # the element changed meanwhile
                self.update_painter_parts();return
            if on_found is not None: on_found(labels)
            else: self.set_ai_parts(labels)
        timer.timeout.connect(poll);timer.start()
        self._parts_timer=timer

    def set_ai_parts(self,labels):
        """Keep the found parts on the element (saved with the project) and repaint."""
        import hashlib
        drawing=self.drawing
        if labels is None:
            for name in ('ai_parts_image','ai_parts_digest','ai_parts_count'):
                if hasattr(drawing,name): delattr(drawing,name)
        else:
            drawing.ai_parts_image=labels
            drawing.ai_parts_digest=hashlib.sha1(labels.tobytes()).hexdigest()
            drawing.ai_parts_count=int(labels.info.get('parts') or 0) or None
        if hasattr(self,'project_changes'): self.project_changes.mark_changed()
        self.note_change()
        self.update_painter_parts()
        self.refresh()

    def forget_ai_parts(self):
        if self.drawing is not None: self.set_ai_parts(None)

    def open_paint_mode_picker(self):
        """Paint mode: the bigger picker with groups, descriptions and a preview."""
        from paint_mode_dialog import PaintModeDialog
        combo=self.reveal_mode
        model=combo.model()
        def allowed(text):
            i=combo.findText(text)
            item=model.item(i) if i>=0 and hasattr(model,'item') else None
            return i>=0 and (item is None or item.isEnabled())
        dialog=PaintModeDialog(self,combo.currentText(),allowed,self.paint_look.currentText())
        def done(result):
            if result and dialog.chosen and allowed(dialog.chosen):
                combo.setCurrentIndex(combo.findText(dialog.chosen))
                self.paint_look.setCurrentText(dialog.look)       # exp.181: chosen in the picker
                if dialog.chosen==self.PAINTER_TEXT and dialog.parts_changed():
                    self.set_ai_parts(dialog.ai_labels if dialog.parts=='ai' else None)   # exp.184
            self.paint_mode_dialog=None
            dialog.deleteLater()
        dialog.finished.connect(done)
        self.paint_mode_dialog=dialog
        dialog.open()                      # window-modal, without blocking the program
        return dialog

    def update_sound_buttons(self):
        for key,(button,text) in self.sound_file_buttons.items():
            path=self.sound_files.get(key)
            button.setText(Path(path).stem if path else 'Add sound…')      # the row label names it
            remove=getattr(self,'sound_remove_buttons',{}).get(key)
            if remove is not None:
                remove.setVisible(bool(path))
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
            return self.timeline_layout().total
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
        return mode if mode in ('adaptive','zigzag','rows','columns','short_zigzag','painter') else 'adaptive'

    # Kept for a new element: the video's own settings (one for the whole project), your
    # hands and tools, the project's sound, and how pictures are turned into drawings.
    KEEP_FOR_NEW_ELEMENT=('showhand','left_handed','paint_left_handed','show_paint_hand','handsize','ax','ay',
                          'paint_hand','paint_hand_size','move_hand','move_hand_size','move_hand_gx','move_hand_gy',
                          'eraser','export_layers','export_done_sound','sound_preview','audio_volume','audio_offset',
                          'image_detail','image_style','image_animation_style','clean_faint')

    def fresh_element_settings(self):
        """exp.112: a new element starts from the default settings, not a copy of the element
        before it (its animation, timing, look, transform, move in, exit...)."""
        from projects import set_widget_value
        from scenes import GLOBAL_SETTINGS
        keep=set(GLOBAL_SETTINGS)|set(self.KEEP_FOR_NEW_ELEMENT)
        for name,value in getattr(self,'_fresh_settings',{}).items():
            if name in keep: continue
            widget=getattr(self,name,None)
            if widget is None: continue
            widget.blockSignals(True)
            try: set_widget_value(widget,value)
            finally: widget.blockSignals(False)
        for name in ('sync_entrance_switches','update_applicable','camera_mode_changed'):
            try: getattr(self,name)()
            except Exception: pass

    def settings_state(self):
        from projects import widget_value
        state={name:widget_value(getattr(self,name)) for name in self.PROJECT_SETTINGS}
        state['audio_path']=self.audio_path
        state['paint_hand_path']=self.paint_hand_path
        state.update(self.sound_files)
        state['paint_hand_tip']=self.paint_hand_tip
        state['move_hand_path']=getattr(self,'move_hand_path',None)
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
            # The hold clip shows the colour hold plus the pause after the element (and, since
            # exp.176/181, the time the hand takes to go back, which is not a setting here).
            seconds=max(0.,seconds-getattr(self.stage_timeline,'hold_extra',0.))
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

    def options(self,overrides=None):
        from export_job import options_from_settings
        image_source=self.is_image_artwork()
        settings=self.settings_state()
        if overrides: settings.update(overrides)
        source=self.image_result.image if image_source and self.image_result else None
        if source is not None and getattr(self,'_look_fast',False) and not self.all_scenes():
            source=self._look_small(source,self.PREVIEW_WIDTH)       # exp.181: while a slider moves, a smaller copy
        options=options_from_settings(
            settings,self.drawing,
            color_image=None if image_source else self.final_image,hand=self.hand,
            image_source=source,
            image_mode=image_source)
        if not image_source and getattr(self.drawing,'svg_has_fill',False) and self.use_color.isChecked() and not self.color_path:
            from svg_appearance import render_appearance
            import picture_look
            options['final_image']=picture_look.adjusted(
                render_appearance(self.drawing,max(options['width'],options['height'])),settings)
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
                self.hand.cacheKey() if self.hand is not None else None,len(self.scenes))

    def schedule_refresh(self,*args):
        """Redraw soon, at most every 40 ms (for controls that are dragged)."""
        if not hasattr(self,'_soon_timer'):
            self._soon_timer=QTimer(self); self._soon_timer.setSingleShot(True)
            self._soon_timer.setInterval(40); self._soon_timer.timeout.connect(self.refresh)
        if getattr(self,'_suspend_refresh',False): return
        if not self._soon_timer.isActive(): self._soon_timer.start()

    def clear_frames(self):
        """Something changed: work out the view again. Ready-made frames stay in the
        segment cache; only segments whose fingerprint changed are drawn again."""
        self._memo={}               # whole-video lengths and the edited element's options
        self._prerender_next=0
        if hasattr(self,'prerender_timer'): self.prerender_timer.stop()

    # ------------------------------------------------- segment fingerprints
    def _token(self,obj):
        """A number for this exact object while it is kept (ids are reused, tokens not)."""
        if obj is None: return None
        entry=self._fp_tokens.get(id(obj))
        if entry is not None and entry[0] is obj: return entry[1]
        if len(self._fp_tokens)>400:
            alive={id(s['state']) for s in self.scenes if s.get('state') is not None}
            alive|={id(self.drawing),id(getattr(self,'image_result',None))}
            self._fp_tokens={k:v for k,v in self._fp_tokens.items() if k in alive}
        self._fp_counter+=1
        self._fp_tokens[id(obj)]=(obj,self._fp_counter)
        return self._fp_counter

    def edited_fingerprint(self):
        """Everything that changes how the element being edited looks."""
        memo=self.__dict__.setdefault('_memo',{})
        if 'edited_fp' in memo: return memo['edited_fp']
        d=self.drawing
        strokes=tuple((len(s.points),s.points[0] if s.points else None,s.points[-1] if s.points else None,
                       getattr(s,'pace',1.),getattr(s,'pause',0.),bool(getattr(s,'reversed',False)),
                       getattr(s,'color',None),getattr(s,'width',None))
                      for s in (getattr(d,'strokes',()) or ()))
        fp=('edit',self.edited_key(),self._token(d),hash(strokes),
            self.final_image.cacheKey() if getattr(self,'final_image',None) is not None else None,
            self._token(getattr(self,'image_result',None)),
            self.hand.cacheKey() if self.hand is not None else None,
            getattr(d,'pen_ease',None),
            # How the colours are painted: the painting order (Line order → Painting)
            # and the AI parts. Without them, playback reused frames painted the old way.
            tuple(getattr(d,'paint_part_order',None) or ()),getattr(d,'ai_parts_digest',None),
            repr(getattr(d,'paint_circles',None) or ()))
        memo['edited_fp']=fp
        return fp

    # Ready frames are kept under a fingerprint of what they show. Since exp.103 an
    # element's part of it is its "revision": a random name saved with the project
    # that changes only when the element really changes. The same element therefore
    # has the same fingerprint while it is edited and while it is not, after switching
    # elements, after "This element" / "Whole video", and in the next session (so
    # "Keep the render after closing" works). Before, it used numbers that only lived
    # for one session and changed when an element was opened or left: the render
    # turned red again for no reason.
    @staticmethod
    def new_rev():
        import uuid
        return uuid.uuid4().hex[:16]

    def scene_rev(self,k):
        scene=self.scenes[k]
        if not scene.get('uid'): scene['uid']=self.new_rev()
        if not scene.get('rev'): scene['rev']=self.new_rev()
        return scene['uid'],scene['rev']

    def current_rev(self):
        """The edited element's revision: a new one whenever what it shows changes."""
        uid,rev=self.scene_rev(self.scene_index)
        fp=self.edited_fingerprint()
        seen=getattr(self,'_rev_fp',None)
        if seen is None:
            self._rev_fp=fp                   # just opened: the revision it was saved with
        elif seen!=fp:
            self._rev_fp=fp
            rev=self.scenes[self.scene_index]['rev']=self.new_rev()
        return uid,rev

    def hand_digest(self):
        """The drawing hand by its pixels (stays the same from session to session)."""
        hand=self.hand
        if hand is None or hand.isNull(): return None
        cached=getattr(self,'_hand_digest',None)
        if cached and cached[0]==hand.cacheKey(): return cached[1]
        import hashlib
        from PySide6.QtGui import QImage
        image=hand.convertToFormat(QImage.Format.Format_ARGB32)
        digest=hashlib.sha1(bytes(image.constBits())[:image.sizeInBytes()]).hexdigest()[:16]
        self._hand_digest=(hand.cacheKey(),digest)
        return digest

    def element_fingerprint(self,k):
        uid,rev=self.current_rev() if k==self.scene_index else self.scene_rev(k)
        return ('el',uid,rev,self.hand_digest(),self.preview_background.currentText(),
                repr(getattr(self,'background_color',None)),self.hand_rest_settings())

    def hand_rest_settings(self):
        """exp.143: the hand waiting in a corner, for every element of the video."""
        if not hasattr(self,'hand_rest'): return {}
        return dict(hand_rest=self.hand_rest.isChecked(),hand_rest_corner=self.hand_rest_corner.currentText(),
                    hand_rest_travel=self.hand_rest_travel.value(),
                    hand_under=self.hand_under.isChecked() if hasattr(self,'hand_under') else False)

    def hand_video(self,k):
        """exp.147: render options for the Hand row: its clips (the hand slides out of the
        picture and back) and where element k starts in the whole video."""
        import camera_clips
        sig=camera_clips.hand_signature(list(getattr(self,'cameras',()))+self.eraser_hand_clips())
        if not sig: return {}
        start=0.
        if k is not None:
            try:
                start=self.timeline_layout().items[k].start if self.all_scenes() else (self.element_start() if len(self.scenes)>1 else 0.)
            except Exception:
                start=0.
        return dict(hand_away=sig,hand_video_start=start)

    def eraser_hand_clips(self):
        """exp.186: while an Eraser clip works on the page being shown, the waiting hand goes down."""
        import eraser_clips, timeline_render
        items=eraser_clips.clips(getattr(self,'overlays',()))
        if not items or not self.all_scenes(): return []
        try:
            lay=self.timeline_layout()
            return eraser_clips.hand_leaves(items,[dict(uid=s.get('uid')) for s in self.scenes],
                                            self.board_frames(),lambda sec: timeline_render.page_of(lay,sec))
        except Exception:
            return []

    def hand_marks(self):
        """exp.147: for the Hand row: each element's (start, glide in, drawing, glide back)."""
        if not self.all_scenes() or not getattr(self,'hand_rest',None) or not self.hand_rest.isChecked():
            return []
        from frame_render import travel_plan
        marks=[]
        try:
            lay=self.timeline_layout(); hidden=self.hidden_elements()
            for it in lay.items:
                if it.k in hidden: continue
                drawing,opts,_,_=self.preview_scene(it.k,960,540)
                plan=travel_plan(drawing,opts)
                if plan is not None:
                    marks.append((it.start,plan[0],plan[1]-plan[5],plan[2],it.k))
        except Exception:
            return []
        return marks

    def edit_hand_glide(self,k):
        """exp.163 (the user): click an element's bar on the Hand row: how long the hand takes to
        go from its corner to the drawing, and to go back."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QDoubleSpinBox
        if not 0<=k<len(self.scenes): return
        glide=tuple(self.scenes[k].get('glide') or (0.,0.))+('Smooth','Smooth')
        settings={'hand_glide_in':glide[0],'hand_glide_out':glide[1]}
        from frame_render import GLIDE_STYLES
        from PySide6.QtWidgets import QComboBox
        def style(value):
            box=QComboBox(); box.addItems(list(GLIDE_STYLES))
            box.setCurrentText(value if value in GLIDE_STYLES else 'Smooth'); return box
        default=float(self.hand_rest_travel.value())
        dialog=QDialog(self); dialog.setWindowTitle(f'Hand: element {k+1}')
        form=QFormLayout(dialog)
        def number(value):
            box=QDoubleSpinBox(); box.setRange(.1,10.); box.setSingleStep(.1); box.setDecimals(1); box.setSuffix(' s')
            box.setValue(float(value or 0) or default); return box
        go=number(settings.get('hand_glide_in')); back=number(settings.get('hand_glide_out'))
        how_in=style(glide[2]); how_out=style(glide[3])
        tip=('Smooth: starts and ends gently. Steady: the same speed all the way. Quick start: fast, then '
             'slows down. Slow start: slow, then fast. Overshoot: goes a little past and settles. Curve: '
             'along an arc. Swoop: fast along an arc.')
        form.addRow(help_label('To the drawing','How long the hand takes to go from its corner to the first line.'),go)
        form.addRow(help_label('How',tip),how_in)
        form.addRow(help_label('Back','How long the hand takes to go back to its corner after drawing.'),back)
        form.addRow(help_label('How ',tip),how_out)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        self.record_structure('hand glide')
        before=next((it for it in self.timeline_layout().items if it.k==k),None)
        self.scenes[k]['glide']=(round(go.value(),2),round(back.value(),2),how_in.currentText(),how_out.currentText())
        self.project_changes.mark_changed()
        self.__dict__.pop('_memo',None); self._scene_cache={}
        if before is not None:
            after=next((it for it in self.timeline_layout().items if it.k==k),None)
            if after is not None:
                self.push_after(before.end,after.length-before.length,skip=k)
        self.hand_rest_changed()
        self.sync_camera_timeline()

    def shift_camera_move(self,k,shift):
        """exp.167 (the user): a move between pages dragged along the timeline: the element it
        goes to and everything after it (elements, cameras, texts) move by the same time."""
        lay=self.timeline_layout()
        target=next((it for it in lay.items if it.k==k+1),None)
        if target is None or abs(shift)<1e-3: return
        shift=max(-target.start,float(shift))
        if abs(shift)<1e-3: return
        self.record_structure('move camera')
        old=target.start
        if self.scenes[k+1].get('start') is None:
            self.scenes[k+1]['start']=round(old+shift,3)
        self.push_after(old,shift,skip=k+1 if self.scenes[k+1].get('start') is not None and
                        abs(float(self.scenes[k+1]['start'])-(old+shift))<1e-3 else None)
        self.project_changes.mark_changed()
        self.fill_scenes(); self.sync_camera_timeline(); self.refresh()

    def push_after(self,when,delta,skip=None):
        """exp.166 (the user): an element that takes longer (its hand going to the drawing or
        back) moves everything after it later by the same time: the elements placed after it,
        the cameras (and the moves between pages, which follow the elements) and the texts."""
        if abs(delta)<1e-4: return
        eps=1e-3
        moved=0
        # exp.168: an element that follows the one before it (no start of its own) moves too
        # when it starts after `when` and the one before it stays (it gets its own start).
        starts={}
        try:
            starts={it.k:it.start for it in self.timeline_layout().items}
        except Exception:
            pass
        for j,scene in enumerate(self.scenes):
            if j==skip or scene.get('start') is not None or j not in starts: continue
            before_stays=j==0 or starts.get(j-1,0.)<when-eps
            if starts[j]>=when-eps and before_stays:
                scene['start']=round(max(0.,starts[j]+delta),3); scene['_pushed']=True; moved+=1
        for j,scene in enumerate(self.scenes):
            if j==skip or scene.get('start') is None: continue
            if scene.pop('_pushed',False): continue
            if float(scene['start'])>=when-eps:
                scene['start']=round(max(0.,float(scene['start'])+delta),3); moved+=1
        for clip in getattr(self,'cameras',[]) or []:
            if float(clip.get('start',0))>=when-eps:
                clip['start']=round(max(0.,float(clip['start'])+delta),2); moved+=1
        for item in getattr(self,'overlays',[]) or []:
            if float(item.get('start',0) or 0)>=when-eps:
                item['start']=round(max(0.,float(item.get('start',0) or 0)+delta),2); moved+=1
        self.__dict__.pop('_memo',None)
        if moved:
            self.status.setText(f'Everything after it moved {"later" if delta>0 else "earlier"} by {abs(delta):.1f} s.')

    def edit_hand_clip(self,cid):
        """exp.147: the hand leaves the picture: when, how fast, how long, which side."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QComboBox, QDoubleSpinBox
        import camera_clips
        clip=self.find_camera(cid)
        if clip is None: return
        hide=clip.get('kind')==camera_clips.HIDE        # exp.148: the hand fades away
        dialog=QDialog(self); dialog.setWindowTitle('Hide the hand' if hide else 'Hand leaves')
        form=QFormLayout(dialog)
        def number(value,low,high):
            box=QDoubleSpinBox(); box.setRange(low,high); box.setSingleStep(.1); box.setDecimals(1)
            box.setSuffix(' s'); box.setValue(float(value)); return box
        a,b=float(clip.get('in_s',1.2)),float(clip.get('out_s',1.2))
        start=number(clip['start'],0,3600)
        go=number(a,.1,30); away=number(max(0.,float(clip['duration'])-a-b),0,600); back=number(b,.1,30)
        side=QComboBox(); side.addItems(list(camera_clips.SIDES)); side.setCurrentText(clip.get('side') or 'Right')
        form.addRow(help_label('Starts','When it starts (seconds of the video).'),start)
        form.addRow(help_label('Fading out' if hide else 'Going out','How long it takes to go.'),go)
        form.addRow(help_label('Hidden' if hide else 'Away','How long it stays away.'),away)
        form.addRow(help_label('Fading in' if hide else 'Coming back','How long it takes to come back.'),back)
        if not hide:
            form.addRow(help_label('Side','Where it goes out.'),side)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        remove=buttons.addButton('Delete',QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        wants={'delete':False}
        remove.clicked.connect(lambda: (wants.update(delete=True),dialog.accept()))
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        if wants['delete']:
            return self.camera_clip_action(cid,'delete')
        self.record_structure('hand clip')
        clip['start']=round(start.value(),2)
        clip['in_s'],clip['out_s']=round(go.value(),2),round(back.value(),2)
        clip['duration']=round(go.value()+away.value()+back.value(),2)
        clip['side']=side.currentText()
        camera_clips.fit(clip)
        self.project_changes.mark_changed()
        self.fill_camera_panel(); self.sync_camera_timeline(); self.refresh()

    def hand_rest_changed(self,*args):
        self._scene_cache={}; self._base_cache=OrderedDict()
        if getattr(self,'_restoring',False) or getattr(self,'_entering_scene',False) or not self.drawing:
            return
        self.clear_frames(); self.refresh()

    def rest_hand_layer(self,width,height,seconds):
        """exp.143: the hand in its corner at `seconds` (None when an element's hand is
        drawing or travelling, or when the hand does not wait in a corner)."""
        if not getattr(self,'hand_rest',None) or not self.hand_rest.isChecked() or self.board_mode() or not self.drawing:
            return None
        from frame_render import hand_window, paint_rest_hand, rest_out
        out=0.
        if self.all_scenes():
            lay=self.timeline_layout(); hidden=self.hidden_elements()
            options=None; others=[]
            for it in lay.items:
                if it.k in hidden: continue
                drawing,opts,_,_=self.preview_scene(it.k,960,540)        # its timing (as the timeline)
                window=hand_window(drawing,opts)
                if window is None:
                    others.append((drawing,opts,it.start)); continue     # exp.153: slides out for it
                if options is None or it.start<=seconds: options=opts
                if it.start-1e-6<=seconds<it.start+window[0]-1e-6:
                    return None                     # this element's own hand
            if options is None: return None
            out=rest_out(others,seconds)
            if out>=1.: return None
        else:
            drawing,options,_,_=self.preview_scene(self.scene_index,960,540)
            window=hand_window(drawing,options)
            if window is None: return None
            if self.position*window[1]<window[0]-1e-6: return None
        layer=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied); layer.fill(0)
        place=self.page_place_at(width,height,seconds) if self.all_scenes() else None     # exp.161: on the page
        return paint_rest_hand(layer,dict(options,layers='all',_rest_out=out,**self.hand_video(None)),seconds,place)

    def page_place_at(self,width,height,seconds):
        """exp.161: where the page is on the screen at `seconds` (camera zooms included)."""
        try:
            lay=self.timeline_layout(width,height)
            if lay.sequential and not self.zoomed_out(): return None
            import timeline_render
            from timeline_model import state_at
            world=self.preview_world(width,height)
            elements=[]
            for k in range(len(self.scenes)):
                drawing,options,secs,camera=self.preview_scene(k,width,height)
                elements.append(dict(drawing=drawing,options=options,camera=self.video_camera(k,camera,secs),
                                     transition=self.scenes[k]['transition'],
                                     move_seconds=self.scenes[k]['transition_seconds']))
            zoom=self.zoomed_out()
            return timeline_render.page_place(world,lay,state_at(lay,max(0.,float(seconds))),elements,width,height,
                                              self.preview_zoom_out if zoom else 1.,
                                              getattr(self,'preview_pan',(0.,0.)) if zoom else (0.,0.))
        except Exception as exc:
            import applog; applog.error('Where the page is (the waiting hand)',exc)
            return None

    def segment_fingerprint(self,where,k):
        """The fingerprint of one segment of the current view (see preview_cache)."""
        view=self._view
        size=(view.get('width'),view.get('height'))
        board=repr([s.get('board') for s in self.scenes])
        if not view['all']:
            base=None
            if view.get('page'):
                base=(tuple(self.element_fingerprint(i) for i in range(self.scene_index)),board)
            return ('one',self.element_fingerprint(self.scene_index),base,size)
        cams=self.cameras_signature(*self.segment_span(where,k))     # exp.119/125: the Camera track
        if where=='scene':
            base=None
            if self.drawn_over(k):
                base=(tuple(self.element_fingerprint(i) for i in range(k)),board)
            return ('scene',self.element_fingerprint(k),base,size,cams)
        s=self.scenes[k]
        return ('join',k,s['transition'],s['transition_seconds'],
                tuple(self.element_fingerprint(i) for i in range(min(k+2,len(self.scenes)))),board,size,cams)

    def segment_at(self,index):
        """(fingerprint, frame inside the segment, frames in the segment, where, k) for a
        frame number of the current view."""
        view=self._view
        count=max(1,round(view['length']*self.PREVIEW_FPS))
        if not view['all']:
            return self.segment_fingerprint('one',self.scene_index),index,count,'one',self.scene_index
        lay=self.timeline_layout()
        if not lay.sequential:
            # Elements on tracks: frames are kept per stretch of time in which nothing starts
            # or ends; the stretch's fingerprint says who is drawn there and since when.
            import math
            from timeline_model import interval_at, state_at, describe
            seconds=max(0,min(count,index))/count*view['length']
            a,b=interval_at(lay,seconds)
            first=math.ceil(a/view['length']*count-1e-9)
            last=max(first,math.ceil(b/view['length']*count-1e-9)-1) if b<view['length']-1e-9 else count
            state=state_at(lay,(first/count)*view['length'])
            involved=sorted({k for k,_ in state.active}|set(state.finished)|{state.current})
            import overlays as _ov
            low=self.titles_split((a+b)/2)[1]
            under=repr([o for o in low if float(o.get('start',0))<b and (_ov.shown_until(o)>a or o.get('kind')=='eraser')])   # exp.186: an eraser stays done
            fp=('tl',describe(lay,state,a),tuple(self.element_fingerprint(i) for i in involved),under,
                self.cameras_signature(a,b),
                tuple(sorted(self.hidden_elements())),
                tuple((s['transition'],s['transition_seconds']) for s in self.scenes),
                repr([s.get('board') for s in self.scenes]),(view.get('width'),view.get('height')))
            return fp,index-first,last-first+1,'tl',first
        import board
        seconds=max(0,min(count,index))/count*view['length']
        where,k,f=board.locate(view['lengths'],view['joins'],seconds)
        seconds_in=view['lengths'][k] if where=='scene' else view['joins'][k]
        frames=max(1,round(seconds_in*self.PREVIEW_FPS))
        local=max(0,min(frames,round(f*frames)))
        return self.segment_fingerprint(where,k),local,frames,where,k

    def render_segment(self,where,k,local,frames,width):
        """One frame of one segment, at its own time (local / frames)."""
        f=local/frames
        if where=='one':
            return self.render_view(f,width)
        if where=='tl':
            from timeline_model import state_at
            count=max(1,round(self._view['length']*self.PREVIEW_FPS))
            seconds=(k+local)/count*self._view['length']
            height=round(width*self._view['ratio'])
            return self.timeline_frame(state_at(self.timeline_layout(),seconds),width,height,seconds)
        height=round(width*self._view['ratio'])
        return self.whole_frame_at(where,k,f,width,height)

    def refresh(self,*args):
        """Show the frame at the playhead. Any change rebuilds the view; moving the
        playhead (scrub, play) only draws a frame, from the ready-made ones if it can."""
        playhead=getattr(self,'_playhead_only',False); self._playhead_only=False
        if self._preparing or getattr(self,'_suspend_refresh',False):
            return
        look=getattr(self,'_look_preview',False)
        if getattr(self,'_plan_deferred',False) and not look:
            playhead=False                # Play / scrub after a look change: plan the brushes now
        if self.drawing and self.board_mode():
            self._view=None; self.clear_frames()
            self.show_board(); return
        view=getattr(self,'_view',None)
        if not playhead or view is None or view['token']!=self._view_token() or not self.drawing:
            try:
                if not self.build_view(): return
            finally:
                self._look_preview=False
            view=self._view
            if getattr(self,'_plan_deferred',False) and look:
                self.position=self.finished_position(view)
        self._look_preview=False
        try:
            frame=self.preview_frame(self.position,playing=self.playing or getattr(self,'_scrub_fast',False))
        except Exception as exc:
            # An invalid/expensive brush configuration must not throw out of
            # the Qt signal handler and terminate the application.
            import applog; applog.error('Preview could not be updated',exc)
            self.status.setText('Preview could not be updated: '+str(exc)[:220])
            return
        self.canvas.frame=frame
        self.sync_titles_timeline()
        self.sync_camera_timeline()
        try:
            self.canvas.titles_frame=self.titles_layer(frame.width(),frame.height(),self.shown_seconds())
        except Exception as exc:
            import applog; applog.error('Texts on top',exc); self.canvas.titles_frame=None
        try:
            self.canvas.rest_frame=self.rest_hand_layer(frame.width(),frame.height(),self.shown_seconds())
        except Exception as exc:
            import applog; applog.error('Hand in its corner',exc); self.canvas.rest_frame=None
        self.canvas.art_frame=None; self.canvas.hand_frame=None
        self.canvas.blend_mode='Normal'
        self.canvas.artwork_opacity=100
        if not view['all'] and not view.get('page') and not self.playing:
            # Paused: the blend mode shown exactly (two extra layers). While playing, the
            # ready-made frame alone (exp.101: drawing both layers on every tick made Play
            # slow even after Pre-render).
            opts=view['options']
            mode=opts.get('blend_mode','Normal')
            opacity=opts.get('artwork_opacity',100)
            if mode!='Normal' or opacity!=100:
                from frame_render import compose_frame
                preview_opts=dict(opts,width=frame.width(),height=frame.height())
                camera=self.preview_camera(preview_opts)
                self.canvas.art_frame=compose_frame(self.drawing,self.position,
                            dict(preview_opts,layers='art',ghost=0),camera)
                self.canvas.hand_frame=compose_frame(self.drawing,self.position,
                            dict(preview_opts,layers='hand',ghost=0,background=False),camera)
                self.canvas.blend_mode=mode
                self.canvas.artwork_opacity=opacity
        if view['all']: self.canvas.highlight=[]
        self.canvas.update()
        self.stage_timeline.progress=max(0.,min(1.,self.position)); self.stage_timeline.update()
        if not view['all'] and self.order.selectedItems(): self.update_highlight()
        length=view['length']
        self.clock.setText(timecode(self.position*length))
        self.clock_total.setText(timecode(length))
        if not self.playing and not getattr(self,'_plan_deferred',False): self.start_prerender()

    def finished_position(self,view):
        """Where the playhead shows the finished element (painted, before it goes out)."""
        parts=dict(self.stage_parts(view.get('options') or self.options()))
        whole=sum(parts.values())
        if whole<=0: return 1.
        done=parts.get('move',parts.get('draw',0))+parts.get('paint',0)
        at=done+parts.get('hold',0)*.5
        return max(0.,min(1.,at/whole, (whole-parts.get('erase',0))/whole))

    def look_changed(self,slider=False):
        """Ink on the page / Colour / Light changed: the finished picture, no brush planning."""
        self._look_preview=True
        if slider:
            # exp.181 (the user: very laggy while changing colours): while the slider moves the
            # look is worked out on a smaller copy of the picture (the preview is small anyway);
            # when it stops, once more at full size.
            self._look_fast=True
            self.schedule_refresh()
            if not hasattr(self,'_look_settle'):
                self._look_settle=QTimer(self); self._look_settle.setSingleShot(True)
                self._look_settle.timeout.connect(self._look_settled)
            self._look_settle.start(450)
        else:
            self._look_fast=False
            self.refresh()

    def _look_settled(self):
        self._look_fast=False
        self._look_preview=True
        self.refresh()

    def _look_small(self,image,limit=1280):
        """A copy of the picture at most `limit` pixels across (kept while it is the same)."""
        if max(image.width(),image.height())<=limit: return image
        key=image.cacheKey()
        cached=getattr(self,'_look_small_cache',None)
        if cached and cached[0]==key: return cached[1]
        small=image.scaled(limit,limit,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        self._look_small_cache=(key,small)
        return small

    def build_view(self):
        """Options and timeline for the current state (after any change)."""
        self._last_change=time.perf_counter()    # exp.181: pre-render waits while you edit
        self.clear_frames(); self._view=None
        self.sync_workspace()
        if not self.drawing:
            self.canvas.frame=None;self.canvas.highlight=[];self.canvas.titles_frame=None;self.canvas.update()
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
            self.show_hand_pictures(options)                # the Hand tab pictures, also here
            total=self.timeline_layout(width,height).total
            self.schedule_render_bar()
            self._view=dict(all=True,length=total,ratio=ratio,token=self._view_token(),
                            lengths=list(lengths),joins=list(joins),width=width,height=height)
            return True
        self.stage_timeline.set_scenes(None,current=self.scene_index)
        self.sync_titles_timeline(force=True)
        self.stage_timeline.set_audio(self.timeline_audio())
        paint_only=self.is_image_artwork() and self.image_animation.currentIndex()==1
        self.stage_timeline.editable={'paint','hold','erase'} if paint_only \
            else {'draw','paint','hold','erase'}
        # exp.181 (the user: in This element the glasses changed in "Hold"): the parts at their
        # real times, with the hand's glide in first (it was left out, so Paint looked over
        # while the hand was still painting).
        parts=dict(self.real_parts(self.scene_index,self.timeline_length(),last_stroke=False))
        self.stage_timeline.lead=parts.pop('glide',0.)
        self.stage_timeline.hold_extra=max(0.,parts.get('hold',0.)-dict(self.stage_parts(options)).get('hold',0.))
        moving='move' in parts
        self.stage_timeline.update_state(parts['move' if moving else 'draw'],parts['paint'],parts['hold'],
            self.position,parts['erase'],first='Move in' if moving else 'Draw')
        options.pop('fps')
        # The artwork is scaled after rasterization. Compensating the hand
        # before that transform keeps its FINAL size independent of Artwork
        # Size, while its pen-tip coordinates move with the artwork.
        options['hand_scale']/=options['artwork_scale']
        options['ghost']=.22            # Hand only: still show faintly what is being written
        # Pictures of earlier scenes in this frame stay on the board under it.
        page=self.drawn_over(self.scene_index) and options.get('layers')!='hand'
        if page: options['background']=False
        self.schedule_render_bar()
        self._view=dict(all=False,options=options,page=page,ratio=ratio,length=self.timeline_length(),
                        token=self._view_token(),width=self.PREVIEW_WIDTH,
                        height=round(self.PREVIEW_WIDTH*ratio))
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
            # The chosen move-in hand, also while its switch is off (exp.101: an uploaded
            # hand did not show here).
            import move_in
            move=move_in.move_hand({'move_hand':True,'move_hand_path':getattr(self,'move_hand_path',None),
                                    'move_hand_gx':self.move_hand_gx.value(),'move_hand_gy':self.move_hand_gy.value(),
                                    'left_handed':self.left_handed.isChecked()})[0] \
                if hasattr(self,'move_hand_gx') else options.get('move_hand')
            for key,image in (('draw',draw),('paint',paint),('move',move)):
                label=pictures.get(key)
                if label is None: continue
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
        if view['page']:
            from artwork_compositor import composite_element
            under=self.scene_base(self.scene_index,width,height,fraction,camera)
            if options.get('blend_mode','Normal')!='Normal' or options.get('artwork_opacity',100)!=100:
                return composite_element(under,self.drawing,fraction,options,camera)
            from scenes import stack
            return stack(under,compose_frame(self.drawing,fraction,options,camera))
        return compose_frame(self.drawing,fraction,options,camera)

    def shown_seconds(self):
        """exp.126: the time of the frame on the screen. Playing (or scrubbing fast), that is
        the nearest video frame, not the exact playhead: the texts on top must be drawn at
        the same moment as the picture under them, or they shake against it in a zoom."""
        exact=self.video_seconds()
        view=getattr(self,'_view',None)
        if not (self.playing or getattr(self,'_scrub_fast',False)) or not view or self.zoomed_out():
            return exact
        try:
            index,count=self.frame_index(self.position)
            return exact+(index/count-self.position)*view['length']
        except Exception:
            return exact

    def frame_index(self,fraction):
        count=max(1,round(self._view['length']*self.PREVIEW_FPS))
        return max(0,min(count,round(fraction*count))),count

    def preview_frame(self,fraction,playing=False):
        """Paused: the exact frame. Playing: the nearest video frame, ready-made when possible,
        else drawn smaller if the computer cannot keep up."""
        if self.zoomed_out():                     # exp.121: not the video's frames
            return self.render_view(fraction,self.PREVIEW_WIDTH if not playing else 640)
        if not playing:
            return self.render_view(fraction,self.PREVIEW_WIDTH)
        index,count=self.frame_index(fraction)
        segment,local,frames,where,k=self.segment_at(index)
        cached=self.segment_cache.get(segment,local,self.PREVIEW_WIDTH)
        stats=getattr(self,'_play_stats',None)
        if stats is not None: stats['ready' if cached is not None else 'drawn']+=1
        if cached is not None:
            return cached
        # exp.126: always the full size. Smaller frames when the computer could not keep up
        # made the picture and the texts change sharpness from one frame to the next (the
        # first title 'palpitated', zoom-ins wobbled); now a slow frame is simply late.
        frame=self.render_segment(where,k,local,frames,self.PREVIEW_WIDTH)
        self.segment_cache.put(segment,local,self.PREVIEW_WIDTH,frame)
        self.schedule_render_bar()
        return frame

    def keep_frame(self,index,frame):
        segment,local,_,_,_=self.segment_at(index)
        self.segment_cache.put(segment,local,self.PREVIEW_WIDTH,frame,disk=self._prerender_all)

    def start_prerender(self):
        """When the preview is idle, make the next frames ready so Play is smooth."""
        if not hasattr(self,'prerender_timer'):
            self.prerender_timer=QTimer(self); self.prerender_timer.setSingleShot(True)
            self.prerender_timer.timeout.connect(self._prerender_tick)
        if not self._prerender_all:
            self._prerender_next=0          # idle: start again from the playhead
        self.prerender_timer.start(1 if self._prerender_all else 450)

    def _prerender_tick(self):
        """exp.181 (the user: very laggy while changing the picture's colours): the frames made
        in the background are drawn on the same thread as the window, so while you are still
        changing things they wait."""
        if not self._prerender_all and time.perf_counter()-getattr(self,'_last_change',0.)<1.2:
            self.prerender_timer.start(400); return
        self.prerender_step()

    def prerender_step(self):
        view=getattr(self,'_view',None)
        if (view is None or not self.isVisible() or self.playing or self.busy or self._preparing or not self.drawing
                or getattr(self,'_plan_deferred',False)
                or (self.builder and self.builder.isRunning()) or (self.worker and self.worker.isRunning())
                or view['token']!=self._view_token()):
            return
        if QApplication.mouseButtons()!=Qt.MouseButton.NoButton:
            # The user is dragging something: wait. A button "held" for more than 5 s
            # without any change is a stale state (it happens after a double-click that
            # opens a window), so pre-render goes on instead of waiting forever.
            self._held_checks=getattr(self,'_held_checks',0)+1
            if self._held_checks<25:
                self.prerender_timer.start(200); return
        else:
            self._held_checks=0
        # exp.181 (the user: very laggy while changing the picture's colours): the frames made
        # in the background are drawn on the same thread as the window, so while you are still
        # changing things it waits, and between frames it leaves the window time to answer.
        index,count=self.frame_index(self.position)
        if not self._prerender_all and self.segment_cache.memory_full(
                self.PREVIEW_WIDTH*round(self.PREVIEW_WIDTH*view['ratio'])*4):
            return                                       # idle pre-render stays in memory
        # From the playhead to the end, then from the start (Pre-render: from the start).
        total=count+1
        target=None
        while self._prerender_next<total:
            step=self._prerender_next
            i=step if self._prerender_all else (index+step)%total
            segment,local,frames,where,k=self.segment_at(i)
            if not self.segment_cache.has(segment,local,self.PREVIEW_WIDTH):
                target=(i,segment,local,frames,where,k); break
            self._prerender_next+=1
        if target is None:
            if self._prerender_all:
                self._prerender_all=False
                self.update_prerender_button(done=True)
            return
        i,segment,local,frames,where,k=target
        try:
            frame=self.render_segment(where,k,local,frames,self.PREVIEW_WIDTH)
        except Exception as exc:
            # exp.101: an error here used to stop pre-render silently ("Rendering frame 1"
            # for ever). Say what happened, skip the frame and go on.
            import applog
            failures=getattr(self,'_prerender_failures',0)+1
            self._prerender_failures=failures
            if failures<=3: applog.error(f'Pre-render: frame {i+1} could not be made',exc)
            label=f'element {k+1}' if where=='scene' else (f'the move after element {k+1}' if where=='join' else 'this element')
            self.status.setText(f'Pre-render skipped a frame of {label}: {str(exc)[:160]}')
            dialog=getattr(self,'prerender_dialog',None)
            if dialog is not None and hasattr(dialog,'show_problem'):
                dialog.show_problem(f'Some frames of {label} could not be made: {str(exc)[:200]}')
            self._prerender_next+=1
            if self._prerender_all and failures>200:
                self._prerender_all=False
                self.update_prerender_button()
                self.status.setText(f'Pre-render stopped: frames of {label} cannot be made ({str(exc)[:160]}).')
                return
            self.prerender_timer.start(1)
            return
        from prerender_dialog import keep_render
        # Kept on disk too when the render is to be kept after closing (exp.103), not only
        # with the Pre-render button.
        self.segment_cache.put(segment,local,self.PREVIEW_WIDTH,frame,disk=self._prerender_all or keep_render())
        if self._prerender_all:
            self.update_prerender_button()
        else:
            self.schedule_render_bar()
        self.prerender_timer.start(1 if self._prerender_all else 40)

    def ready_frames(self):
        """(frames ready, frames in the video) of the preview (for tests and the status)."""
        if getattr(self,'_view',None) is None: return 0,0
        count=self.frame_index(1.)[1]
        ready=0
        for i in range(count+1):
            segment,local,_,_,_=self.segment_at(i)
            if self.segment_cache.has(segment,local,self.PREVIEW_WIDTH): ready+=1
        return ready,count+1

    def prerender_whole(self):
        """Pre-render: make every frame of the current preview ready (kept on disk too).
        Click again to stop. Only segments that changed are drawn again later."""
        if self._prerender_all:
            self._prerender_all=False
            self.update_prerender_button()
            return
        if not self.drawing or self.board_mode(): return
        self.playing=False
        if getattr(self,'_plan_deferred',False):
            self._look_preview=False; self.refresh()          # plan the brushes first (with its card)
            if getattr(self,'_plan_deferred',False): return
        if getattr(self,'_view',None) is None and not self.build_view(): return
        self._prerender_all=True; self._prerender_next=0; self._prerender_failures=0
        from prerender_dialog import PrerenderDialog
        dialog=PrerenderDialog(self)
        def closed(result):
            if self._prerender_all:                  # Cancel (or closed): stop where it is
                self._prerender_all=False
                self.update_prerender_button()
                self.status.setText('Pre-render stopped. The frames made so far stay ready (green on the timeline).')
            self.prerender_dialog=None
            dialog.deleteLater()
        dialog.finished.connect(closed)
        self.prerender_dialog=dialog
        dialog.open()
        self.update_prerender_button()
        self.start_prerender()

    def update_prerender_button(self,done=False):
        self.schedule_render_bar()
        dialog=getattr(self,'prerender_dialog',None)
        button=getattr(self,'prerender_button',None)
        if button is None: return
        if self._prerender_all:
            total=self.frame_index(1.)[1]+1 if getattr(self,'_view',None) else 1
            percent=min(99,round(100*self._prerender_next/max(1,total)))
            button.setText(f'Stop pre-render ({percent}%)')
            if dialog is not None: dialog.show_progress(self._prerender_next,total)
        else:
            button.setText('Pre-render')
            if done:
                self.status.setText('Pre-render finished: the preview plays from ready-made frames.')
                if dialog is not None: dialog.accept()

    # ------------------------------------------------ render bar over the timeline
    def schedule_render_bar(self):
        """Red where preview frames are not ready, green where they are (like Filmora)."""
        if not hasattr(self,'render_bar_timer'):
            self.render_bar_timer=QTimer(self);self.render_bar_timer.setSingleShot(True)
            self.render_bar_timer.setInterval(250)
            self.render_bar_timer.timeout.connect(self.update_render_bar)
        if not self.render_bar_timer.isActive(): self.render_bar_timer.start()

    def render_runs(self):
        """[(first frame, last frame, ready)] of the current preview, and the frame count."""
        if getattr(self,'_view',None) is None: return [],0
        count=self.frame_index(1.)[1]+1
        runs=[]
        i=0
        while i<count:
            # exp.120: one fingerprint per segment, not per frame (the bar was slow to draw).
            segment,local,frames,_,_=self.segment_at(i)
            n=max(1,min(count-i,frames-local))
            for j in range(n):
                ready=self.segment_cache.has(segment,local+j,self.PREVIEW_WIDTH)
                if runs and runs[-1][2]==ready: runs[-1][1]=i+j
                else: runs.append([i+j,i+j,ready])
            i+=n
        return [tuple(r) for r in runs],count

    def update_render_bar(self):
        timeline=getattr(self,'stage_timeline',None)
        if timeline is None or not hasattr(timeline,'set_render_state'): return
        try:
            runs,count=self.render_runs()
        except Exception:
            runs,count=[],0
        timeline.set_render_state(runs,count,self.PREVIEW_FPS)

    def scrub(self,value):
        self.position=value/1000
        if self.playing and self.preview_sound is not None:
            self.sync_preview_sound()     # user moved the playhead while playing
        # exp.120: while the playhead is dragged, ready-made frames are shown (like Play);
        # the exact frame is drawn when the mouse stops.
        tl=getattr(self,'stage_timeline',None)
        dragging=self.slider.isSliderDown() or (tl is not None and getattr(tl,'_drag',None)==('seek',))
        if dragging and not self.playing:
            self._scrub_fast=True
            if not hasattr(self,'_scrub_settle'):
                self._scrub_settle=QTimer(self); self._scrub_settle.setSingleShot(True)
                self._scrub_settle.timeout.connect(self._scrub_done)
            self._scrub_settle.start(160)
        self._playhead_only=True
        self.refresh()

    def _scrub_done(self):
        if not getattr(self,'_scrub_fast',False): return
        self._scrub_fast=False
        if not self.playing and not getattr(self,'_closed',False):
            self._playhead_only=True; self.refresh()
    def toggle(self):
        if not self.drawing or self.busy: return
        if self.board_mode(): self.preview_scope.setCurrentIndex(1)
        if self.position>=1: self.slider.setValue(0)
        self.playing=not self.playing; self.last=time.perf_counter(); self.sync_workspace()
        if self.playing: self.start_play_stats()
        else: self.log_play_stats()
        self.keep_split('Play pressed')
        self.sync_preview_sound()

    # Play statistics in the log (exp.103): how many frames came ready-made and how long
    # each step took, so a lagging playback can be explained from the user's log.
    def start_play_stats(self):
        self._play_stats=dict(ticks=0,ready=0,drawn=0,ms=0.,worst=0.,late=0,last=time.perf_counter(),
                              start=self.position)

    def log_play_stats(self):
        stats=getattr(self,'_play_stats',None)
        self._play_stats=None
        if not stats or stats['ticks']<10: return
        import applog
        view=getattr(self,'_view',None) or {}
        applog.info('Play (%s): %d steps, frames ready-made %d, drawn while playing %d; '
                    'per step %.1f ms on average, slowest %.0f ms; %d steps came late (over 50 ms apart); '
                    'memory for frames %.0f MB'
                    % ('whole video' if view.get('all') else 'this element',stats['ticks'],stats['ready'],
                       stats['drawn'],stats['ms']/stats['ticks'],stats['worst'],stats['late'],
                       self.segment_cache.memory_budget/1024**2))

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
    def remember_split(self):
        """exp.175: the preview / timeline split the user dragged to."""
        self._user_split=list(self.vertical_splitter.sizes())

    def keep_split(self,why=''):
        """exp.175 (the user: the preview shrank every time Play was pressed): put the split
        back where the user left it when something else moved it, and say in the log what
        moved it, so the cause can be found."""
        want=getattr(self,'_user_split',None)
        split=getattr(self,'vertical_splitter',None)
        if not want or split is None: return
        now=list(split.sizes())
        if now==want or sum(now)!=sum(want): return
        try:
            import applog
            top,bottom=split.widget(0),split.widget(1)
            applog.info('Preview size changed by itself (%s): %s -> %s; smallest the preview area '
                        'allows %d, smallest the timeline area allows %d (timeline %d..%d)' % (
                            why,want,now,top.minimumSizeHint().height(),bottom.minimumSizeHint().height(),
                            self.stage_timeline.minimumHeight(),self.stage_timeline.maximumHeight()))
        except Exception:
            pass
        split.setSizes(want)
        if list(split.sizes())!=want and not getattr(self,'_split_logged',False):
            self._split_logged=True
            try:
                import applog; applog.info('Preview size: could not put it back, now %s' % list(split.sizes()))
            except Exception:
                pass

    def tick(self):
        if not self.playing or not self.drawing or self.busy: return
        view=getattr(self,'_view',None)
        length=view['length'] if view is not None and view['token']==self._view_token() else self.timeline_length()
        now=time.perf_counter(); self.position=min(1,self.position+(now-self.last)/max(1e-3,length)); self.last=now
        self.slider.blockSignals(True); self.slider.setValue(round(self.position*1000)); self.slider.blockSignals(False)
        stats=getattr(self,'_play_stats',None)
        began=time.perf_counter()
        self._playhead_only=True; self.refresh()
        self.keep_split('playing')
        if stats is not None:
            spent=(time.perf_counter()-began)*1000
            stats['ticks']+=1; stats['ms']+=spent; stats['worst']=max(stats['worst'],spent)
            if (began-stats['last'])*1000>50: stats['late']+=1
            stats['last']=began
        if self.position>=1:
            self.playing=False; self.sync_workspace()
            self.log_play_stats()
            if self.preview_sound is not None: self.preview_sound.stop()
    def save(self):
        if not self.drawing or (self.builder and self.builder.isRunning()) or (self.worker and self.worker.isRunning()): return
        parent=QFileDialog.getExistingDirectory(self,'Choose destination; a new sequence folder will be created')
        if not parent: return
        import copy
        folder=Path(parent)/datetime.now().strftime('StrokeScribe_%Y%m%d_%H%M%S_%f')
        options=self.options()
        options['overlays']=self.titles_for_element()      # this element alone: its time (exp.116)
        if getattr(self,'cameras',None) and len(self.scenes)<2:      # exp.119: the Camera track
            import camera_clips
            options['video_camera']=(0.,camera_clips.signature(self.cameras),tuple(self.camera_moves()))
        if len(self.scenes)>1 and self.export_all_scenes.isChecked():
            self._leave_scene()
            scene_list=[dict(state=copy.deepcopy(s['state']),transition=s['transition'],
                             transition_seconds=s['transition_seconds'],board=s.get('board'),
                             start=s.get('start'),track=s.get('track') or 0,
                             hidden=bool(self.track_flag(s,'hidden')),muted=bool(self.track_flag(s,'muted')))
                        for s in self.scenes]
            self.scenes[self.scene_index]['state']=None       # still edited here
            self.worker=SceneExporter(scene_list,folder,self.settings_state(),self.hand,copy.deepcopy(self.visible_titles()),
                                      copy.deepcopy(getattr(self,'cameras',[])))
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
            if (getattr(self,'close_to_home',False) and not getattr(self,'_quitting',False)
                    and not getattr(self,'_restart_preconfirmed',False) and not self.home_visible()):
                # exp.109: X in a project goes back to Home (the project stays open behind it);
                # X on Home, or File > Exit, closes StrokeScribe.
                event.ignore()
                self.show_home()
                return
            if not getattr(self, '_restart_preconfirmed', False) and not self.confirm_leave_project('close StrokeScribe'):
                event.ignore()
                return
            if self.ai_engine is not None:
                self.ai_engine.stop()        # never leave the AI engine running
            # Only a successful close stops autosaving; a rejected close must
            # leave the recovery timer active for the still-open project.
            self._closed=True
            self.autosave_timer.stop()
            try:
                from prerender_dialog import keep_render
                if not keep_render(): self.segment_cache.clear_disk()   # no render left on disk
            except Exception:
                pass
            if not getattr(self,'_keep_autosave',False):
                import autosave; autosave.clear()
            event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setStyle('Fusion'); window=Window()
    if len(sys.argv)>1:
        try: window.set_drawing(import_svg(sys.argv[1]))
        except Exception as e: QMessageBox.warning(window,'Cannot import',str(e))
    window.showMaximized(); sys.exit(app.exec())
