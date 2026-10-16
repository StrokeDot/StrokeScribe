import sys, time
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
REVEAL_MODES = ('brush', 'adaptive', 'zigzag')

def timecode(seconds):
    """00:04.25 style time for the monitor."""
    seconds=max(0.,float(seconds))
    minutes,rest=divmod(seconds,60)
    return f'{int(minutes):02d}:{rest:05.2f}'


class Canvas(QWidget):
    """Program monitor: the frame on its preview background, plus a loading card."""
    def __init__(self):
        super().__init__(); self.frame=None; self.background=0; self.setMinimumSize(550,330)
        self.busy_text=None; self.busy_percent=None; self.busy_detail=''
        self._spin=0
        self._spinner=QTimer(self); self._spinner.setInterval(40)
        self._spinner.timeout.connect(self._advance)
        self.on_click=None          # on_click(x, y, add) in frame pixels
        self.highlight=[]           # selected lines: polylines in frame pixels
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    def mousePressEvent(self,event):
        if self.frame is None or self.on_click is None or self.busy_text is not None:
            return super().mousePressEvent(event)
        x,y,size=self.frame_rect()
        pos=event.position()
        fx=(pos.x()-x)*self.frame.width()/max(1,size.width())
        fy=(pos.y()-y)*self.frame.height()/max(1,size.height())
        if 0<=fx<=self.frame.width() and 0<=fy<=self.frame.height():
            mods=event.modifiers()
            self.on_click(fx,fy,bool(mods&(Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)))
        self.setFocus()
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
            p.save(); p.setClipRect(x,y,size.width(),size.height())
            if self.background>=3:
                from backgrounds import TEXTURES, texture_qimage
                p.drawImage(x,y,texture_qimage(TEXTURES[self.background-3],size.width(),size.height()))
            elif self.background:
                p.fillRect(x,y,size.width(),size.height(),QColor('#ffffff' if self.background==1 else c['preview_dark']))
            else:
                for a in range(x,x+size.width(),20):
                    for b in range(y,y+size.height(),20):
                        p.fillRect(a,b,20,20,QColor(c['checker_a'] if ((a-x)//20+(b-y)//20)%2==0 else c['checker_b']))
            p.drawImage(x,y,self.frame.scaled(size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
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
            p.drawRoundedRect(card,10,10)
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
                 mp4=False,mp4_background='white',sound_volume=None):
        super().__init__()
        self.sound_volume=sound_volume
        self.drawing=drawing; self.folder=Path(folder); self.options=options
        self.mov=mov; self.webm=webm; self.webm_quality=webm_quality
        self.keep_png=keep_png; self.mp4=mp4; self.mp4_background=mp4_background
    def run(self):
        try:
            from export_job import run_export
            self.done.emit(run_export(
                self.drawing,self.folder,self.options,self.mov,self.webm,self.webm_quality,
                self.keep_png,self.mp4,self.mp4_background,self.sound_volume,
                progress=self.progress.emit,interrupted=self.isInterruptionRequested))
        except Exception as e: self.failed.emit(str(e))

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
        self.history=History()
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
        # Rapid brush-width changes should not synchronously rebuild the entire
        # paint plan for every spinbox/wheel event on the GUI thread.
        self.brush_preview_timer=QTimer(self)
        self.brush_preview_timer.setSingleShot(True)
        self.brush_preview_timer.setInterval(180)
        self.brush_preview_timer.timeout.connect(self.refresh)
        from studio_workspace import build_workspace
        build_workspace(self,Canvas,BRAND_ICON)
        self.canvas.on_click=self.click_preview
        self.watch_settings()
        self.update_sound_buttons()
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
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.analysis_timer=QTimer(self)
        self.analysis_timer.setInterval(1000)
        self.analysis_timer.timeout.connect(self.update_analysis_elapsed)
        self.reset_history()

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
        if mode in ('adaptive','zigzag'):
            self.drawing.paint_method=mode
        elif not image_source:
            return
        from adaptive_hand import plan_ready, plan_for
        bw,sp=options.get('brush_width',.14),options.get('stroke_spacing',.55)
        if plan_ready(self.drawing,image,bw,sp):
            return
        self._preparing=True
        try:
            self.show_busy_now('Preparing brush route',
                               'Planning how the hand paints the colours…')
            plan_for(self.drawing,image,bw,sp)
        finally:
            self._preparing=False
            self.clear_busy()

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

    # ------------------------------------------------ undo / redo (everything)
    def snapshot(self):
        return {'settings':self.settings_state(),
                'strokes':tuple(self.drawing.strokes) if self.drawing else ()}

    def reset_history(self):
        if hasattr(self,'history_timer'): self.history_timer.stop()
        self.history.reset(self.snapshot())
        self.update_history_controls()

    def note_change(self,*args):
        """A setting changed: remember it once the user pauses (one undo step per edit)."""
        if self._restoring or not hasattr(self,'history_timer'): return
        self.history_timer.start()

    def commit_history(self):
        if self._restoring: return
        self.history_timer.stop()
        self.history.record(self.snapshot())
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
        try:
            settings=snapshot['settings']
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
            self.preserve_colors.setEnabled(self.image_animation.currentIndex()!=1)
            if self.drawing is not None and snapshot['strokes']:
                selected=set(id(s) for s in self.selected_strokes())
                self.drawing.strokes=list(snapshot['strokes'])
                self.fill_order(keep=selected)
        finally:
            self._restoring=False
        self.update_history_controls()
        self.refresh()

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

    def click_preview(self,x,y,add=False):
        if self.all_scenes(): return          # lines are edited in "This scene" preview
        index=self.line_at(x,y)
        if index is None:
            if not add: self.order.clearSelection()
            return
        item=self.order.item(index)
        if add:
            item.setSelected(not item.isSelected())
        else:
            self.order.clearSelection(); item.setSelected(True)
        self.order.setCurrentRow(index,QItemSelectionModel.SelectionFlag.NoUpdate)
        self.order.scrollToItem(item)
        self.show_line_tools()
        self.status.setText(f'Selected: {self.drawing.strokes[index].name}  •  Delete, Reverse, pace and pause '
                            'are under LINES & ORDER on the left; drag in the list to reorder.')

    def show_line_tools(self):
        """Scroll the Source panel so the line list and its buttons are visible."""
        from PySide6.QtWidgets import QScrollArea
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
        image_source=bool(self.source_type.currentIndex())
        self.load_color_button.setEnabled(not image_source)
        self.use_color.setEnabled(not image_source and self.final_image is not None)
        # Image sources paint by brush plan only (Adaptive or Zigzag).
        brush_item=self.reveal_mode.model().item(0)
        if brush_item is not None:
            brush_item.setEnabled(not image_source)
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
        self.export.setEnabled(self.drawing is not None and not busy)
        self.quick_export.setEnabled(self.drawing is not None and not busy)
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
        self.playing=False
        self.drawing=drawing
        self.fill_order()
        self.note.setText('\n'.join(drawing.warnings) or 'Ready. Press Play to draw from the beginning.')
        self.position=0 if getattr(drawing,'source_kind',None)=='image' else 1
        self.slider.setValue(round(self.position*1000))
        self.update_project_title(self.project_title)
        self.refresh()
        self.reset_history()
        if getattr(self,'scenes',None) and not getattr(self,'_entering_scene',False):
            self.scenes[self.scene_index]['thumb']=None      # new artwork: new thumbnail
            if hasattr(self,'scene_list'): QTimer.singleShot(0,self.fill_scenes)
    def change_source(self,index):
        self.playing=False
        if index:
            self.svg_state=(self.drawing,self.final_image,self.use_color.isChecked())
            self.image_controls.show(); self.import_button.setText('Import image…')
            if self.image_result: self.set_drawing(self.image_result.drawing)
            else:
                self.drawing=None; self.order.clear(); self.canvas.frame=None; self.canvas.highlight=[]; self.canvas.update()
                self.note.setText('Import a PNG, JPEG, WebP or BMP to begin.')
        else:
            self.image_controls.hide(); self.import_button.setText('Import SVG…')
            if self.svg_state:
                drawing,self.final_image,checked=self.svg_state
                self.use_color.setChecked(checked); self.set_drawing(drawing)
        self.export.setEnabled(self.drawing is not None)
        self.quick_export.setEnabled(self.drawing is not None)
        self.refresh()
    # ------------------------------------------------------------ projects
    PROJECT_SETTINGS=('duration','speed','thickness','artwork_size','reveal_mode','color_fade',
                      'image_duration','image_animation','brush_width','stroke_spacing','color_hold',
                      'use_color','preserve_colors','showhand','show_paint_hand','handsize','ax','ay',
                      'res','fps','webm','webm_quality','mov','mp4','mp4_background','keep_png',
                      'sound_on','sound_volume','sound_preview','preview_background','image_detail',
                      'image_style','image_animation_style','clean_faint',
                      'erase_mode','erase_time','erase_size','eraser',
                      'camera','audio_volume','audio_offset','pen_ease','paint_hand','paint_hand_size','fast_export','export_layers')

    def project_state(self):
        """Everything needed to reopen this project: the edited scene plus all scenes."""
        from scenes import scenes_to_project
        self.store_scene(thumbnail=False)
        return scenes_to_project(self.scene_state(),self.scenes,self.scene_index)

    def scene_state(self):
        """Everything needed to reopen the scene being edited."""
        from projects import drawing_to_dict, qimage_to_b64, widget_value
        from tools_kit import hand_to_project
        image_source=bool(self.source_type.currentIndex())
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
            state['color_png']=qimage_to_b64(self.final_image)
        if self.paint_hand_path and Path(self.paint_hand_path).is_file():
            import base64
            state['paint_hand_png']=base64.b64encode(Path(self.paint_hand_path).read_bytes()).decode('ascii')
        return state

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
            path=projects.save(path,self.project_state())
        except Exception as exc:
            QMessageBox.warning(self,'Save project',str(exc)); return None
        self.project_path=str(path)
        self.status.setText('Project saved: '+str(path))
        self.setWindowTitle(f'{Path(path).stem}  •  {DISPLAY_NAME}')
        return path

    def open_project(self,path=None):
        if (self.builder and self.builder.isRunning()) or (self.worker and self.worker.isRunning()):
            QMessageBox.information(self,'Open project','Please wait for the current job to finish.'); return False
        import projects
        if path is None:
            path,_=QFileDialog.getOpenFileName(self,'Open project','','StrokeScribe project (*.strokescribe)')
            if not path: return False
        try:
            data=projects.load(path)
            self.apply_project(data)
        except Exception as exc:
            QMessageBox.warning(self,'Open project',str(exc)); return False
        self.project_path=str(path)
        self.setWindowTitle(f'{Path(path).stem}  •  {DISPLAY_NAME}')
        self.status.setText('Opened project: '+str(path))
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
        drawing=drawing_from_dict(data['drawing'])
        settings=data.get('settings',{})
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
        self.letter_bg_color=letter.get('background')
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
            self.image_result=Reconstruction(drawing,image,regions,'line_art',detail,info.get('filename','image'))
            self.image_path=info.get('path') or None
            self.image_guide=info.get('guide') or None
            self.source_type.blockSignals(True); self.source_type.setCurrentIndex(1); self.source_type.blockSignals(False)
            self.image_controls.show(); self.import_button.setText('Import image…')
            self.color_note.setText(self.image_result.filename+' • original colors')
        else:
            self.source_type.blockSignals(True); self.source_type.setCurrentIndex(0); self.source_type.blockSignals(False)
            self.image_controls.hide(); self.import_button.setText('Import SVG…')
            self.final_image=qimage_from_b64(data.get('color_png'))
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

    # ------------------------------------------------------------ scenes
    def scene_label(self,k):
        scene=self.scenes[k]
        if scene.get('name'): return scene['name']
        state=scene.get('state')
        title=self.project_title if state is None else state.get('title')
        return title or f'Scene {k+1}'

    def store_scene(self,thumbnail=True):
        """Keep the edited scene's state (and a fresh thumbnail) in the scene list."""
        if not self.drawing: return
        scene=self.scenes[self.scene_index]
        scene['name']=scene.get('name') or None
        if thumbnail:
            try:
                from scenes import thumbnail as make_thumb
                scene['thumb']=make_thumb(self.drawing,self.options())
            except Exception:
                scene['thumb']=None

    def fill_scenes(self):
        """Rebuild the scene strip."""
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtGui import QIcon, QPixmap
        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        for k,scene in enumerate(self.scenes):
            if k==self.scene_index and self.drawing is not None and scene.get('thumb') is None:
                self.store_scene()
            item=QListWidgetItem(f'{k+1} · {self.scene_label(k)}'[:22])
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
        self.scene_transition.setEnabled(not last)
        self.scene_transition_time.setEnabled(not last and scene['transition']!='Cut')
        self.preview_scope.setEnabled(many)
        if not many and self.preview_scope.currentIndex():
            self.preview_scope.blockSignals(True); self.preview_scope.setCurrentIndex(0); self.preview_scope.blockSignals(False)
        self.export_all_scenes.setEnabled(many)
        self.export_all_scenes.setText(f'Export all {len(self.scenes)} scenes as one video' if many
                                       else 'Export all scenes as one video')

    def _leave_scene(self):
        """Save the edited scene into the list before editing another one."""
        self.store_scene()
        self.scenes[self.scene_index]['state']=self.scene_state()
        self._scene_cache.pop(id(self.scenes[self.scene_index]['state']),None)

    def _enter_scene(self,k):
        state=self.scenes[k]['state']
        self._entering_scene=True                  # loading a scene is not new artwork
        try:
            self.apply_scene_state(state)
        except Exception as exc:
            QMessageBox.warning(self,'Scene',f'Scene {k+1} could not be opened: {exc}')
            self.fill_scenes(); return
        finally:
            self._entering_scene=False
        self.scene_index=k
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
        self.status.setText(f'Editing scene {row+1} of {len(self.scenes)}: {self.scene_label(row)}')

    def add_scene(self):
        """A new scene after the current one (starts as a copy; import its own artwork)."""
        if not self.drawing or (self.builder and self.builder.isRunning()): return
        import copy
        self.playing=False
        self._leave_scene()
        current=self.scenes[self.scene_index]
        new=dict(state=copy.deepcopy(current['state']),transition=current['transition'],
                 transition_seconds=current['transition_seconds'],name=f'Scene {len(self.scenes)+1}',
                 thumb=current.get('thumb'))
        self.scenes.insert(self.scene_index+1,new)
        self._enter_scene(self.scene_index+1)
        self.status.setText(f'Scene {self.scene_index+1} added as a copy. Import an SVG or image for it '
                            '(Import, Library or Create image); its settings are its own.')

    def delete_scene(self):
        if len(self.scenes)<2: return
        answer=QMessageBox.question(self,'Delete scene',
            f'Delete scene {self.scene_index+1} ({self.scene_label(self.scene_index)})?')
        if answer!=QMessageBox.StandardButton.Yes: return
        self.playing=False
        removed=self.scene_index
        del self.scenes[removed]
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
        self.scene_transition_time.setEnabled(scene['transition']!='Cut'
                                              and self.scene_index<len(self.scenes)-1)
        self.refresh()

    def all_scenes(self):
        return self.preview_scope.currentIndex()==1 and len(self.scenes)>1

    def preview_scope_changed(self):
        self.playing=False
        if self.preview_sound is not None: self.preview_sound.stop()
        if self.all_scenes():
            self.status.setText('Previewing all scenes (no sound in this preview; the export has it). '
                                'Lines can be clicked again in "This scene" preview.')
            self.order.clearSelection()
        self.refresh()

    def preview_scene(self,k,width,height):
        """(drawing, options, seconds, camera) of scene k for the preview, at preview size."""
        from scenes import job_from_state, seconds_of
        if k==self.scene_index:
            options=self.options(); options.pop('fps',None)
            options['hand_scale']/=options['artwork_scale']
            options['width'],options['height']=width,height
            options['ghost']=.22
            return self.drawing,options,seconds_of(self.drawing,options),self.preview_camera(options)
        state=self.scenes[k]['state']
        key=(id(state),width,height)
        cached=self._scene_cache.get(id(state))
        if cached is None or cached[0]!=key:
            drawing,options,_=job_from_state(state,self.hand)
            options.pop('fps',None); options.pop('audio',None)
            options['hand_scale']/=options['artwork_scale']
            options['width'],options['height']=width,height
            options['ghost']=.22
            camera=None
            if options.get('camera_zoom',1.)>1.0001:
                from frame_render import camera_for
                camera=camera_for(drawing,options,options['camera_zoom'],rate=20.)
            if options.get('final_image') is not None and options.get('reveal_mode') in ('adaptive','zigzag'):
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

    def scene_timeline(self,width=960,height=540):
        """Lengths of all scenes and the moves between them (seconds)."""
        from scenes import transition_seconds
        lengths=[self.preview_scene(k,width,height)[2] for k in range(len(self.scenes))]
        joins=[0. if k==len(self.scenes)-1 else
               transition_seconds(s['transition'],s['transition_seconds']) for k,s in enumerate(self.scenes)]
        return lengths,joins

    def all_scenes_frame(self,width,height):
        """Preview frame of the whole video at the playhead."""
        from frame_render import compose_frame
        from scenes import locate, transition_frame
        lengths,joins=self.scene_timeline(width,height)
        total=sum(lengths)+sum(joins)
        where,k,f=locate(lengths,joins,self.position*total)
        def frame(n,fraction):
            drawing,options,_,camera=self.preview_scene(n,width,height)
            return compose_frame(drawing,fraction,options,camera)
        if where=='join':
            return transition_frame(frame(k,1.),frame(k+1,0.),self.scenes[k]['transition'],f),k,lengths,joins
        return frame(k,f),k,lengths,joins

    def open_batch_export(self):
        from batch_export import BatchExportDialog
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'Batch export','Please wait for the current export to finish.'); return
        BatchExportDialog(self,self.settings_state(),self.hand,play_done_sound).exec()

    # ------------------------------------------------------------ AI images
    def open_create_image(self):
        from create_image_dialog import CreateImageDialog
        import ai_engine
        if self.ai_engine is None:
            self.ai_engine=ai_engine.Engine()
        current=self.image_path if self.source_type.currentIndex() else None
        dialog=CreateImageDialog(self,current,self.use_ai_result,self.ai_engine)
        dialog.exec()

    def use_ai_result(self,kind,path,original=None):
        """Line art: trace it over `original`; image: import it as the image source."""
        self.source_type.setCurrentIndex(1)
        if kind=='lineart' and original:
            self.build_image(original,line_guide=path)
        else:
            self.build_image(path)

    def use_own_line_drawing(self):
        """Trace a line drawing you already have (black lines on white) over the image."""
        if not self.image_path:
            QMessageBox.information(self,'Line drawing','Import the colour image first.'); return
        name,_=QFileDialog.getOpenFileName(self,'Choose the line drawing of this image','',
                                           'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if name:
            self.build_image(self.image_path,line_guide=name)

    def rebuild_image(self):
        if self.image_path: self.build_image(self.image_path)

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

    def build_image(self,path,line_guide=None):
        if self.builder and self.builder.isRunning(): return
        self.playing=False
        if path!=self.image_path or line_guide is not None:
            self.image_guide=line_guide
        self.image_path=path
        self.builder=ImageBuilder(path,self.image_detail.currentText().lower(),
                                  self.brush_width.value(),self.stroke_spacing.value(),
                                  clean_faint=self.clean_faint.isChecked(),
                                  style=('clean','detailed')[self.image_style.currentIndex()],
                                  animation=('artist','standard')[self.image_animation_style.currentIndex()],
                                  paint_method=self.image_paint_method(),
                                  line_guide=self.image_guide)
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
        self.status.setText('Image analysis failed: '+str(error)[:140])
        QMessageBox.warning(self,'Image reconstruction',error)

    def image_ready(self,result):
        self.image_result=result
        self.update_project_title(result.filename)
        self.set_drawing(result.drawing)
        self.color_note.setText(result.filename+' • original colors; adaptive brush reveal')

    def image_finished(self):
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
        self.analysis_stage=''
    def keep_in_library(self,category,path):
        """Copy an imported file into the library (if enabled) and return the path to use."""
        import library
        if not library.load_settings().get('keep_imports',True):
            return path
        try:
            return str(library.Library().add(category,path).path)
        except Exception as exc:
            self.status.setText('Could not keep a library copy: '+str(exc)[:150])
            return path

    def load(self):
        if self.source_type.currentIndex():
            name,_=QFileDialog.getOpenFileName(self,'Import image','','Images (*.png *.jpg *.jpeg *.webp *.bmp)')
            if name: self.build_image(self.keep_in_library('images',name))
            return
        name,_=QFileDialog.getOpenFileName(self,'Import SVG','','SVG (*.svg)')
        if name:
            name=self.keep_in_library('images',name)
            try:
                self.show_busy_now('Loading drawing',Path(name).name)
                try:
                    drawing=import_svg(name)
                finally:
                    self.clear_busy()
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

    def use_library_item(self,category,item):
        if category=='audio':
            self.set_audio(str(item.path)); return
        if category=='hands':
            image=QImage(str(item.path))
            if image.isNull():
                QMessageBox.warning(self,'Hand','Could not read this hand image.'); return
            self.set_hand(image,item.name,str(item.path),item.tip)
            return
        path=str(item.path)
        if path.lower().endswith('.svg'):
            self.source_type.setCurrentIndex(0)
            try:
                drawing=import_svg(path)
            except Exception as exc:
                QMessageBox.warning(self,'Cannot import',str(exc)); return
            self.update_project_title(item.name)
            self.set_drawing(drawing)
        else:
            self.source_type.setCurrentIndex(1)
            self.build_image(path)

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
            button.setText(f'{text}: {Path(path).stem[:22]}' if path else f'{text}: built-in sound — choose recording…')

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
        from frame_render import timeline_seconds
        if self.all_scenes():
            lengths,joins=self.scene_timeline()
            return sum(lengths)+sum(joins)
        return timeline_seconds(self.drawing,self.options())
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

    def image_paint_method(self):
        mode=REVEAL_MODES[self.reveal_mode.currentIndex()]
        return mode if mode in ('adaptive','zigzag') else 'adaptive'

    def settings_state(self):
        from projects import widget_value
        state={name:widget_value(getattr(self,name)) for name in self.PROJECT_SETTINGS}
        state['audio_path']=self.audio_path
        state['paint_hand_path']=self.paint_hand_path
        state.update(self.sound_files)
        state['paint_hand_tip']=self.paint_hand_tip
        return state

    # ------------------------------------------------- voiceover, timing
    def load_audio(self):
        import audio_track
        name,_=QFileDialog.getOpenFileName(self,'Load voiceover or music','',
            'Audio ('+' '.join('*'+t for t in audio_track.AUDIO_TYPES)+')')
        if name: self.set_audio(self.keep_in_library('audio',name))

    def remove_audio(self):
        self.set_audio(None)

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
        image=bool(self.source_type.currentIndex())
        paint_only=image and self.image_animation.currentIndex()==1
        painting=options['final_image'] is not None
        return dict(draw=0. if paint_only else options['duration'],
                    paint=options['fade_duration'] if painting else 0.,
                    hold=options['hold_duration'] if painting else 0.,
                    erase=options['erase']['seconds'] if options.get('erase') else 0.)

    def apply_timing(self,times):
        image=bool(self.source_type.currentIndex())
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
        image=bool(self.source_type.currentIndex())
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
             repr({k:v for k,v in options.items() if isinstance(v,(int,float,str,tuple))}),
             repr(options.get('erase') and {k:v for k,v in options['erase'].items() if k!='image'}),
             options.get('final_image') is not None)
        if key!=self._camera_key:
            from frame_render import camera_for
            self._camera_path=camera_for(self.drawing,options,zoom,rate=20.)
            self._camera_key=key
        return self._camera_path

    def options(self):
        from export_job import options_from_settings
        image_source=bool(self.source_type.currentIndex())
        return options_from_settings(
            self.settings_state(),self.drawing,
            color_image=None if image_source else self.final_image,hand=self.hand,
            image_source=self.image_result.image if image_source and self.image_result else None,
            image_mode=image_source)

    def refresh(self,*args):
        if self._preparing:
            return
        self.sync_workspace()
        if not self.drawing:
            self.stage_timeline.update_state(0,0,0,0)
            self.clock.setText(timecode(0)); self.clock_total.setText(timecode(0))
            return
        options=self.options()
        if not (self.builder and self.builder.isRunning()):
            self.ensure_brush_plan(options)
        if self.all_scenes():
            self.refresh_all_scenes(options); return
        self.stage_timeline.set_scenes(None)
        erase=options.get('erase')
        self.stage_timeline.update_state(options['duration'],
            options['fade_duration'] if options['final_image'] is not None else 0,
            options['hold_duration'] if options['final_image'] is not None else 0,
            self.position,erase['seconds'] if erase else 0)
        options.pop('fps')
        size=options['artwork_scale']
        # The artwork is scaled after rasterization. Compensating the hand
        # before that transform keeps its FINAL size independent of Artwork
        # Size, while its pen-tip coordinates move with the artwork.
        options['hand_scale']/=size
        ratio=options['height']/options['width']
        options['width']=960; options['height']=round(960*ratio)
        options['ghost']=.22            # Hand only: still show faintly what is being written
        try:
            # Same frame composition as the export (hand layer, artwork size).
            from frame_render import compose_frame
            self.canvas.frame=compose_frame(self.drawing,self.position,options,self.preview_camera(options))
            self.canvas.update()
        except Exception as exc:
            # An invalid/expensive brush configuration must not throw out of
            # the Qt signal handler and terminate the application.
            self.status.setText('Preview could not be updated: '+str(exc)[:220])
            return
        if self.order.selectedItems(): self.update_highlight()
        length=self.timeline_length()
        self.clock.setText(timecode(self.position*length))
        self.clock_total.setText(timecode(length))
    def refresh_all_scenes(self,options):
        ratio=options['height']/options['width']
        width,height=960,round(960*ratio)
        try:
            frame,k,lengths,joins=self.all_scenes_frame(width,height)
        except Exception as exc:
            self.status.setText('Preview could not be updated: '+str(exc)[:220]); return
        self.canvas.frame=frame; self.canvas.highlight=[]; self.canvas.update()
        segments=[]
        for n,(length,join) in enumerate(zip(lengths,joins)):
            segments.append((f'{n+1} · {self.scene_label(n)}',length,'scene'))
            if join>0: segments.append((self.scenes[n]['transition'],join,'join'))
        self.stage_timeline.set_scenes(segments,current=self.scene_index)
        self.stage_timeline.update_state(sum(lengths)+sum(joins),0,0,self.position)
        total=sum(lengths)+sum(joins)
        self.clock.setText(timecode(self.position*total))
        self.clock_total.setText(timecode(total))
    def scrub(self,value):
        self.position=value/1000
        if self.playing and self.preview_sound is not None:
            self.sync_preview_sound()     # user moved the playhead while playing
        self.refresh()
    def toggle(self):
        if not self.drawing or self.busy: return
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
        self.slider.setValue(0); self.playing=True; self.last=time.perf_counter(); self.sync_workspace()
        self.sync_preview_sound()
    def tick(self):
        if not self.playing or not self.drawing or self.busy: return
        now=time.perf_counter(); self.position=min(1,self.position+(now-self.last)/self.timeline_length()); self.last=now
        self.slider.blockSignals(True); self.slider.setValue(round(self.position*1000)); self.slider.blockSignals(False); self.refresh()
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
                             transition_seconds=s['transition_seconds']) for s in self.scenes]
            self.scenes[self.scene_index]['state']=None       # still edited here
            self.worker=SceneExporter(scene_list,folder,self.settings_state(),self.hand)
        else:
            self.worker=None
        if self.worker is None: self.worker=Exporter(copy.deepcopy(self.drawing),folder,options,
                             self.mov.isChecked(),self.webm.isChecked(),
                             self.webm_quality.value(),self.keep_png.isChecked(),
                             mp4=self.mp4.isChecked(),
                             mp4_background=self.mp4_background.currentText().lower(),
                             sound_volume=self.sound_volume.value()/100 if self.sound_on.isChecked() else None)
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
            if self.ai_engine is not None:
                self.ai_engine.stop()        # never leave the AI engine running
            event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setStyle('Fusion'); window=Window()
    if len(sys.argv)>1:
        try: window.set_drawing(import_svg(sys.argv[1]))
        except Exception as e: QMessageBox.warning(window,'Cannot import',str(e))
    window.show(); sys.exit(app.exec())
