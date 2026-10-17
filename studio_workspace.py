"""Original StrokeScribe Studio workspace.

An editor-style layout (source/paths, central monitor, inspector and timeline).
Only the UI is reorganized: rendering and export algorithms stay in their
existing modules. No third-party product assets or lookalike trade dress.
"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QObject, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QScrollArea, QSplitter, QVBoxLayout,
    QHBoxLayout, QFormLayout, QPushButton, QLabel, QComboBox, QCheckBox,
    QSpinBox, QListWidget, QPlainTextEdit, QSlider, QTabWidget,
    QProgressBar, QSizePolicy, QAbstractSpinBox, QAbstractScrollArea,
)
from version import APP_VERSION, DISPLAY_NAME


# Colours and the stylesheet live in theme.py (Dark default, Light optional).
from theme import stylesheet as theme_stylesheet, colors as theme_colors


def label(text, kind='section'):
    w=QLabel(text)
    w.setObjectName(kind)
    return w


def caption(text):
    w=QLabel(text)
    w.setObjectName('note')
    w.setWordWrap(True)
    return w


def scroll_view(content):
    scroll=QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


def form_layout():
    form=QFormLayout()
    form.setContentsMargins(0,8,0,8)
    form.setSpacing(9)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    return form


class StageTimeline(QFrame):
    """Interactive time overview, like an editor's track.

    Row 1: Draw / Paint / Hold / Erase clips (drag a clip's right edge to make
    it longer or shorter). Row 2: the voiceover / music clip with its
    waveform (drop an audio file here; drag the clip to move it in time;
    right-click to remove).
    """
    stage_dragged=Signal(str,float)     # stage key, new seconds (while dragging)
    stage_drag_done=Signal()
    audio_moved=Signal(float)           # new start time of the audio clip (seconds)
    audio_dropped=Signal(str)           # an audio file dropped on the timeline
    audio_remove=Signal()
    overlay_selected=Signal(str)        # an overlay clip was clicked ('' = none)
    overlay_changed=Signal(str,float,float,int)   # id, start, duration, track (while dragging)
    overlay_done=Signal(str)            # drag finished
    overlay_edit=Signal(str)            # double-click: open its settings
    overlay_action=Signal(str,str)      # id, 'edit' / 'duplicate' / 'delete'
    overlay_dropped=Signal(str,float)   # a picture file dropped on the overlay tracks, at seconds

    STAGE_KEYS=('draw','paint','hold','erase')
    EDGE=6.                             # pixels: grab distance for a clip edge

    def __init__(self, slider, parent=None):
        super().__init__(parent)
        self.slider=slider
        self.draw_seconds=4.
        self.paint_seconds=0.
        self.hold_seconds=0.
        self.erase_seconds=0.
        self.progress=0.
        self.setMinimumHeight(104)
        self.setMaximumHeight(140)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.locked=False          # True while a drawing is being prepared
        self.scene_segments=None   # all-scenes preview: [(label, seconds, 'scene'|'join')]
        self.current_scene=0
        self.audio=None            # {'start', 'seconds', 'name', 'envelope'} or None
        self.editable=set(self.STAGE_KEYS)   # stages whose length can be dragged
        self.overlays=[]           # overlay clips of the scene (dicts, see overlays.py)
        self.selected_overlay=None
        self._drag=None
        self._frozen=None          # time scale kept still while a clip edge is dragged
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip('Click to move the playhead. Drag the right edge of a clip to change its length. '
                        'Drop a sound or music file on the lower row; drag it to move it.')
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def update_state(self, draw, paint, hold, progress, erase=0.):
        self.draw_seconds=max(0.,float(draw))
        self.paint_seconds=max(0.,float(paint))
        self.hold_seconds=max(0.,float(hold))
        self.erase_seconds=max(0.,float(erase))
        self.progress=max(0.,min(1.,float(progress)))
        self.update()

    def set_scenes(self, segments, current=0):
        """Show scene blocks instead of Draw/Paint/Hold/Erase (None: back to stages)."""
        self.scene_segments=list(segments) if segments else None
        self.current_scene=current
        self.update()

    def set_audio(self, audio):
        self.audio=dict(audio) if audio else None
        self.update()

    CLIP_H=34.; LANE_H=22.; AUDIO_H=26.

    def tracks(self):
        if self.scene_segments: return 0
        return (max(int(o.get('track',0)) for o in self.overlays)+1) if self.overlays else 0

    def set_overlays(self, items, selected=None):
        self.overlays=list(items or ())
        self.selected_overlay=selected
        need=int(22+6+self.CLIP_H+4+(self.LANE_H+3)*max(1,self.tracks())+self.AUDIO_H+10)
        self.setMinimumHeight(max(104,need)); self.setMaximumHeight(max(140,need+20))
        self.update()

    LEFT=12.
    RIGHT=12.

    # ------------------------------------------------------------ geometry
    def total(self):
        return self.draw_seconds+self.paint_seconds+self.hold_seconds+self.erase_seconds

    def _rows(self):
        ruler_h=22.; top=ruler_h+6.
        clips=QRectF(self.LEFT,top,self._width(),self.CLIP_H)
        y=clips.bottom()+4
        n=self.tracks()
        lane_top=y
        y+=(self.LANE_H+3)*n if n else 0
        audio=QRectF(self.LEFT,y,self._width(),max(18.,min(self.AUDIO_H+10,self.height()-y-4)))
        return ruler_h,clips,audio

    def _lane(self, track):
        _,clips,_=self._rows()
        return QRectF(self.LEFT,clips.bottom()+4+(self.LANE_H+3)*track,self._width(),self.LANE_H)

    def _overlay_rect(self, item):
        lane=self._lane(int(item.get('track',0)))
        x0=self._x(float(item.get('start',0))); x1=self._x(float(item.get('start',0))+float(item.get('duration',3)))
        return QRectF(x0,lane.top(),max(8.,x1-x0),lane.height())

    def _overlay_at(self, pos):
        if self.scene_segments or self.locked: return None,None
        for item in reversed(self.overlays):
            r=self._overlay_rect(item)
            if r.adjusted(-3,0,3,0).contains(pos):
                if abs(pos.x()-r.right())<=self.EDGE: return item,'end'
                if abs(pos.x()-r.left())<=self.EDGE and r.width()>3*self.EDGE: return item,'start'
                return item,'move'
        return None,None

    def _width(self):
        return max(1.,self.width()-self.LEFT-self.RIGHT)

    def _view_total(self):
        return self._frozen or self.total()

    def _x(self, seconds):
        total=self._view_total()
        return self.LEFT+self._width()*(seconds/total if total>0 else 0)

    def _edges(self):
        """[(stage key, x of its right edge, seconds before it)] of the visible stage clips."""
        out=[]; t=0.
        for key,secs in zip(self.STAGE_KEYS,(self.draw_seconds,self.paint_seconds,self.hold_seconds,self.erase_seconds)):
            if secs<=0: continue
            out.append((key,self._x(t+secs),t)); t+=secs
        return out

    def _edge_at(self, pos):
        if self.scene_segments or self.locked: return None
        _,clips,_=self._rows()
        if not (clips.top()-2<=pos.y()<=clips.bottom()+2): return None
        for key,x,_ in self._edges():
            if key in self.editable and abs(pos.x()-x)<=self.EDGE:
                return key
        return None

    def _audio_rect(self):
        if not self.audio or self.scene_segments: return None
        _,_,lane=self._rows()
        total=self.total()
        if total<=0: return None
        x0=self._x(min(total,self.audio['start']))
        x1=self._x(min(total,self.audio['start']+self.audio['seconds']))
        return QRectF(x0,lane.top(),max(6.,x1-x0),lane.height())

    # ------------------------------------------------------------ painting
    def paintEvent(self, event):
        c=theme_colors()
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left=self.LEFT; width=self._width()
        ruler_h,clips,lane=self._rows()
        total=self._view_total()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c['track']))
        p.drawRoundedRect(clips,9,9)
        small=QFont(self.font());small.setPointSizeF(8.)
        p.setFont(small)
        if total<=0:
            p.setPen(QColor(c['dim']))
            p.drawText(clips,Qt.AlignmentFlag.AlignCenter,'Import artwork to begin')
            p.end()
            return
        # Ruler: major ticks with time labels, minor ticks between them.
        steps=[.1,.2,.25,.5,1,2,5,10,15,30,60]
        major=next((t for t in steps if width*t/total>=70),steps[-1])
        minor=major/5
        n=int(total/minor+1e-6)
        for i in range(n+1):
            t=i*minor
            x=left+width*t/total
            is_major=abs(t/major-round(t/major))<1e-6
            p.setPen(QPen(QColor(c['ruler'] if is_major else c['border_strong']),1))
            p.drawLine(QPointF(x,ruler_h-(9 if is_major else 4)),QPointF(x,ruler_h))
            if is_major and x<left+width-24:
                p.setPen(QColor(c['muted']))
                p.drawText(QRectF(x+3,1,60,14),Qt.AlignmentFlag.AlignLeft,
                           f'{t:.0f}s' if major>=1 else f'{t:.1f}s')
        p.setPen(QPen(QColor(c['border']),1))
        p.drawLine(QPointF(left,ruler_h+.5),QPointF(left+width,ruler_h+.5))
        # Clips for each phase, like clips on an editor track.
        stages=[('Draw',self.draw_seconds,c['draw']),
                ('Paint',self.paint_seconds,c['paint']),
                ('Hold',self.hold_seconds,c['hold']),
                ('Out',self.erase_seconds,c.get('erase','#D9667E'))]
        if self.scene_segments:
            palette=[c['draw'],c['paint'],c['hold'],c.get('erase','#D9667E')]
            stages=[]; k=0
            for name,secs,kind in self.scene_segments:
                if kind=='join':
                    stages.append((name,secs,c['border_strong']))
                else:
                    stages.append((name,secs,palette[k%len(palette)])); k+=1
        x=left
        p.save(); p.setClipRect(QRectF(left,0,width,self.height()))
        label_font=QFont(self.font());label_font.setPointSizeF(8.5);label_font.setBold(True)
        for name,secs,color in stages:
            if secs<=0:
                continue
            part=width*secs/total
            rect=QRectF(x+1.5,clips.top()+3,max(1.,part-3),clips.height()-6)
            fill=QColor(color);fill.setAlpha(215)
            p.setPen(QPen(QColor(color).lighter(125),1))
            p.setBrush(fill)
            p.drawRoundedRect(rect,7,7)
            if not self.scene_segments and {'out':'erase'}.get(name.lower(),name.lower()) in self.editable and part>=14:
                # Grip on the right edge: drag it to change the length.
                p.setPen(QPen(QColor(255,255,255,150),1.4))
                gx=rect.right()-4
                p.drawLine(QPointF(gx,rect.center().y()-6),QPointF(gx,rect.center().y()+6))
                p.drawLine(QPointF(gx-3,rect.center().y()-6),QPointF(gx-3,rect.center().y()+6))
            if part>=46:
                p.setPen(QColor(c['clip_text']))
                p.setFont(label_font)
                text=f'{name}  {secs:.1f}s' if part>=96 else name
                p.drawText(rect.adjusted(9,0,-10,0),
                    Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft, text)
                p.setFont(small)
            x+=part
        p.restore()
        # Overlay tracks: pictures and titles on top of the drawing.
        if not self.scene_segments and self.overlays:
            for track in range(self.tracks()):
                row=self._lane(track)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['track'])); p.drawRoundedRect(row,7,7)
            p.save(); p.setClipRect(QRectF(left,0,width,self.height()))
            colour=QColor(c.get('accent_b','#4C42DE'))
            for item in self.overlays:
                r=self._overlay_rect(item).adjusted(1,2,-1,-2)
                chosen=item.get('id')==self.selected_overlay
                fill=QColor(colour if item.get('kind')!='text' else QColor(c.get('erase','#E06A86')))
                fill.setAlpha(235 if chosen else 185)
                p.setPen(QPen(QColor('white') if chosen else fill.lighter(130),2 if chosen else 1)); p.setBrush(fill)
                p.drawRoundedRect(r,6,6)
                if r.width()>30:
                    p.setPen(QColor('white')); p.setFont(small)
                    icon='T ' if item.get('kind')=='text' else '▣ '
                    p.drawText(r.adjusted(7,0,-6,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,
                               icon+str(item.get('name') or '')[:40])
            p.restore()
        # Audio lane.
        if not self.scene_segments:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['track']))
            p.drawRoundedRect(lane,8,8)
            rect=self._audio_rect()
            if rect is None:
                p.setPen(QColor(c['dim']))
                p.drawText(lane,Qt.AlignmentFlag.AlignCenter,'♪  Drop a voiceover or music file here')
            else:
                accent=QColor(c['accent'])
                fill=QColor(accent);fill.setAlpha(70)
                p.setPen(QPen(accent,1)); p.setBrush(fill)
                p.save(); p.setClipRect(lane)
                p.drawRoundedRect(rect,6,6)
                env=self.audio.get('envelope') or []
                if env:
                    mid=rect.center().y(); half=rect.height()*.42
                    p.setPen(QPen(accent.lighter(130),1))
                    span=max(1e-6,self.audio['seconds'])
                    px_per_sec=width/total
                    for i,level in enumerate(env):
                        t=i/len(env)*span
                        xx=rect.left()+t*px_per_sec
                        if xx>lane.right(): break
                        h=max(.5,level*half)
                        p.drawLine(QPointF(xx,mid-h),QPointF(xx,mid+h))
                p.setPen(QColor(c['text']))
                p.drawText(rect.adjusted(6,0,-4,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,
                           '♪ '+self.audio.get('name',''))
                p.restore()
        # Playhead: a line through the track with a marker on the ruler.
        play_x=left+width*self.progress
        accent=QColor(c['accent'])
        p.setPen(QPen(accent,2))
        p.drawLine(QPointF(play_x,ruler_h-2),QPointF(play_x,lane.bottom()))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(accent)
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(play_x-6,ruler_h-13),QPointF(play_x+6,ruler_h-13),
                                 QPointF(play_x+6,ruler_h-6),QPointF(play_x,ruler_h),
                                 QPointF(play_x-6,ruler_h-6)]))
        p.end()

    def set_locked(self, locked):
        self.locked=bool(locked)
        self.setCursor(Qt.CursorShape.BusyCursor if self.locked else Qt.CursorShape.PointingHandCursor)
        self.update()

    # ------------------------------------------------------------ mouse
    def _seek(self, x):
        fraction=max(0.,min(1.,(x-self.LEFT)/self._width()))
        self.slider.setValue(round(1000*fraction))

    def mousePressEvent(self,event):
        if self.locked:
            event.accept(); return
        pos=event.position()
        if event.button()==Qt.MouseButton.RightButton:
            item,_=self._overlay_at(pos)
            if item is not None:
                from PySide6.QtWidgets import QMenu
                oid=item.get('id')
                self.selected_overlay=oid; self.overlay_selected.emit(oid); self.update()
                menu=QMenu(self)
                menu.addAction('Settings…',lambda: self.overlay_action.emit(oid,'edit'))
                menu.addAction('Duplicate',lambda: self.overlay_action.emit(oid,'duplicate'))
                menu.addSeparator()
                menu.addAction('Delete',lambda: self.overlay_action.emit(oid,'delete'))
                menu.exec(event.globalPosition().toPoint())
                event.accept(); return
            rect=self._audio_rect()
            if rect is not None and rect.contains(pos):
                from PySide6.QtWidgets import QMenu
                menu=QMenu(self)
                menu.addAction('Remove the audio track',self.audio_remove.emit)
                menu.exec(event.globalPosition().toPoint())
            event.accept(); return
        if event.button()!=Qt.MouseButton.LeftButton or self.total()<=0:
            return super().mousePressEvent(event)
        item,part=self._overlay_at(pos)
        if item is not None:
            self.selected_overlay=item.get('id'); self.overlay_selected.emit(item.get('id'))
            self._frozen=self.total()
            self._drag=('overlay',item,part,pos.x(),pos.y(),float(item.get('start',0)),
                        float(item.get('duration',3)),int(item.get('track',0)),self._width()/self.total())
            self.update(); event.accept(); return
        key=self._edge_at(pos)
        if key:
            start=next(t for k,_,t in self._edges() if k==key)
            self._frozen=self.total()
            self._drag=('edge',key,start,self._width()/self.total())
            event.accept(); return
        rect=self._audio_rect()
        if rect is not None and rect.contains(pos):
            self._drag=('audio',pos.x(),self.audio['start'],self._width()/self.total())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept(); return
        self._drag=('seek',)
        self._seek(pos.x())
        event.accept()

    def mouseMoveEvent(self,event):
        if self.locked:
            event.accept(); return
        pos=event.position()
        if self._drag and event.buttons() & Qt.MouseButton.LeftButton:
            kind=self._drag[0]
            if kind=='overlay':
                _,item,part,x0,y0,start0,length0,track0,px_per_sec=self._drag
                shift=(pos.x()-x0)/px_per_sec
                total=self._frozen or self.total()
                start,length,track=start0,length0,track0
                if part=='move':
                    start=max(0.,min(total-.1,start0+shift))
                    track=max(0,min(5,track0+int(round((pos.y()-y0)/(self.LANE_H+3)))))
                elif part=='end':
                    length=max(.2,min(total-start0,length0+shift))
                else:
                    start=max(0.,min(start0+length0-.2,start0+shift)); length=start0+length0-start
                self.overlay_changed.emit(item.get('id'),round(start,2),round(length,2),track)
                self.setToolTip(f'{item.get("name","")}: {start:.1f} s → {start+length:.1f} s')
                event.accept(); return
            if kind=='edge':
                _,key,start,px_per_sec=self._drag
                seconds=max(.1,(pos.x()-self.LEFT)/px_per_sec-start)
                self.stage_dragged.emit(key,round(seconds,2))
                self.setToolTip(f'{key.title()}: {seconds:.1f} s')
            elif kind=='audio':
                _,x0,start0,px_per_sec=self._drag
                self.audio_moved.emit(round(max(0.,start0+(pos.x()-x0)/px_per_sec),2))
            else:
                self._seek(pos.x())
            event.accept(); return
        # Hover: show what can be grabbed.
        item,part=self._overlay_at(pos)
        if item is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor if part in ('start','end') else Qt.CursorShape.OpenHandCursor)
            return super().mouseMoveEvent(event)
        if self._edge_at(pos):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            rect=self._audio_rect()
            self.setCursor(Qt.CursorShape.OpenHandCursor if rect is not None and rect.contains(pos)
                           else Qt.CursorShape.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self,event):
        item,_=self._overlay_at(event.position())
        if item is not None:
            self.overlay_edit.emit(item.get('id')); event.accept(); return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self,event):
        if self._drag and self._drag[0]=='overlay':
            self._frozen=None
            self.overlay_done.emit(self._drag[1].get('id'))
        if self._drag and self._drag[0]=='edge':
            self._frozen=None
            self.stage_drag_done.emit()
        self._drag=None
        self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ drop audio
    AUDIO_TYPES=('.mp3','.wav','.m4a','.aac','.ogg','.flac','.opus','.wma')
    PICTURE_TYPES=('.png','.jpg','.jpeg','.webp','.bmp','.svg')

    def _audio_url(self, event, types=None):
        for url in event.mimeData().urls() if event.mimeData().hasUrls() else []:
            if url.isLocalFile() and url.toLocalFile().lower().endswith(types or self.AUDIO_TYPES):
                return url.toLocalFile()
        return None

    def dragEnterEvent(self, event):
        if self._audio_url(event) or (not self.scene_segments and self._audio_url(event,self.PICTURE_TYPES)):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path=self._audio_url(event)
        if path:
            self.audio_dropped.emit(path)
            event.acceptProposedAction(); return
        picture=self._audio_url(event,self.PICTURE_TYPES)
        if picture and not self.scene_segments:
            x=event.position().x()
            seconds=max(0.,min(self.total(),(x-self.LEFT)/self._width()*self.total()))
            self.overlay_dropped.emit(picture,round(seconds,2))
            event.acceptProposedAction()

    def keyPressEvent(self,event):
        if self.locked:
            event.accept(); return
        if event.key() in (Qt.Key.Key_Delete,Qt.Key.Key_Backspace) and self.selected_overlay:
            self.overlay_action.emit(self.selected_overlay,'delete'); return
        if event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right):
            self.slider.setValue(self.slider.value()+(-10 if event.key()==Qt.Key.Key_Left else 10))
        elif event.key()==Qt.Key.Key_Home:
            self.slider.setValue(0)
        elif event.key()==Qt.Key.Key_End:
            self.slider.setValue(1000)
        else:
            super().keyPressEvent(event)


def spin_box_style(assets, name='dark'):
    """Kept for compatibility: the full themed stylesheet (includes spin boxes)."""
    return theme_stylesheet(name, assets)


_ICONS={}


def transport_icon(kind, color, size=18):
    """Crisp drawn transport icons (emoji glyphs vary by system font)."""
    from PySide6.QtGui import QPolygonF, QPainterPath
    key=(kind,color,size)
    if key in _ICONS:
        return _ICONS[key]
    scale=2
    pix=QPixmap(size*scale,size*scale);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale,scale)
    col=QColor(color)
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(col)
    s=float(size)
    if kind=='play':
        p.drawPolygon(QPolygonF([QPointF(s*.32,s*.2),QPointF(s*.32,s*.8),QPointF(s*.8,s*.5)]))
    elif kind=='pause':
        p.drawRoundedRect(QRectF(s*.27,s*.2,s*.16,s*.6),1.5,1.5)
        p.drawRoundedRect(QRectF(s*.57,s*.2,s*.16,s*.6),1.5,1.5)
    elif kind=='start':
        p.drawRoundedRect(QRectF(s*.2,s*.24,s*.1,s*.52),1,1)
        p.drawPolygon(QPolygonF([QPointF(s*.78,s*.24),QPointF(s*.78,s*.76),QPointF(s*.34,s*.5)]))
    elif kind=='end':
        p.drawRoundedRect(QRectF(s*.7,s*.24,s*.1,s*.52),1,1)
        p.drawPolygon(QPolygonF([QPointF(s*.22,s*.24),QPointF(s*.22,s*.76),QPointF(s*.66,s*.5)]))
    elif kind in ('sound','mute'):
        p.drawPolygon(QPolygonF([QPointF(s*.14,s*.38),QPointF(s*.3,s*.38),QPointF(s*.5,s*.2),
                                 QPointF(s*.5,s*.8),QPointF(s*.3,s*.62),QPointF(s*.14,s*.62)]))
        pen=QPen(col,s*.08);pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen);p.setBrush(Qt.BrushStyle.NoBrush)
        if kind=='sound':
            p.drawArc(QRectF(s*.42,s*.32,s*.24,s*.36),-50*16,100*16)
            p.drawArc(QRectF(s*.42,s*.18,s*.4,s*.64),-50*16,100*16)
        else:
            p.drawLine(QPointF(s*.6,s*.36),QPointF(s*.86,s*.64))
            p.drawLine(QPointF(s*.86,s*.36),QPointF(s*.6,s*.64))
    elif kind=='restart':
        pen=QPen(col,s*.11);pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen);p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(s*.22,s*.22,s*.56,s*.56),100*16,280*16)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(col)
        p.drawPolygon(QPolygonF([QPointF(s*.38,s*.08),QPointF(s*.58,s*.24),QPointF(s*.36,s*.36)]))
    p.end()
    icon=QIcon(pix)
    _ICONS[key]=icon
    return icon


def wordmark_html():
    """'StrokeScribe' with the logo's purple; the first half follows the theme."""
    c=theme_colors()
    return (f'<span style="color:{c["wordmark"]}">Stroke</span>'
            f'<span style="color:{c["brand"]}">Scribe</span>')


def brand_icon(path):
    """Window / taskbar icon in every size, made from the large logo (sharp everywhere)."""
    master=QPixmap(str(path))
    icon=QIcon()
    if master.isNull():
        return icon
    for size in (16,20,24,32,40,48,64,96,128,256):
        icon.addPixmap(master.scaled(size,size,Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
    return icon


def crisp_pixmap(path, size, widget=None):
    """The logo at `size` points, drawn with the screen's real pixels (no blur on 125–200 % screens)."""
    from PySide6.QtGui import QGuiApplication
    ratio=widget.devicePixelRatioF() if widget is not None else (QGuiApplication.primaryScreen().devicePixelRatio()
                                                                 if QGuiApplication.primaryScreen() else 1.)
    ratio=max(1.,float(ratio))
    pix=QPixmap(str(path)).scaled(round(size*ratio),round(size*ratio),Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
    pix.setDevicePixelRatio(ratio)
    return pix


def fit_to_width(content, stacked=False):
    """Let a scrolling panel shrink to its column instead of being cut off."""
    from PySide6.QtWidgets import QAbstractSpinBox
    for button in content.findChildren(QPushButton):
        # Expanding fills the column; the explicit minimum lets it shrink
        # below its text width rather than push the panel wider.
        policy=button.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        button.setSizePolicy(policy);button.setMinimumWidth(60)
    for box in content.findChildren(QComboBox):
        box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        box.setMinimumContentsLength(6)
        policy=box.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        box.setSizePolicy(policy)
    for box in content.findChildren(QAbstractSpinBox):
        box.setMinimumWidth(84)
        policy=box.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        box.setSizePolicy(policy)
    for edit in content.findChildren(QPlainTextEdit):
        policy=edit.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        edit.setSizePolicy(policy)
    for form in content.findChildren(QFormLayout):
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows if stacked
                              else QFormLayout.RowWrapPolicy.WrapLongRows)


def panel(object_name, title, hint=None):
    """An editor panel: a title strip on top and a body below it."""
    frame=QFrame();frame.setObjectName(object_name)
    outer=QVBoxLayout(frame);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
    header=QFrame();header.setObjectName('panelHeader')
    header_l=QHBoxLayout(header);header_l.setContentsMargins(12,7,10,7);header_l.setSpacing(8)
    title_label=label(title,'panelTitle')
    header_l.addWidget(title_label)
    if hint:
        header_l.addWidget(label(hint,'panelHint'))
    header_l.addStretch(1)
    outer.addWidget(header)
    frame.title_label=title_label
    return frame,outer,header_l


class LineList(QListWidget):
    """Line list that reports when lines were dragged to a new place."""
    dropped=Signal()
    def dropEvent(self,event):
        super().dropEvent(event)
        self.dropped.emit()


# Inspector tabs, in order.
TABS = {'animation': 0, 'hand': 1, 'sound': 2, 'export': 3}


class WheelGuard(QObject):
    """The mouse wheel scrolls the panel, not the list or number box under the mouse:
    a list or number box reacts to the wheel only after you clicked it (it has focus)."""

    def eventFilter(self, obj, event):
        if event.type()==QEvent.Type.Wheel and isinstance(obj,(QComboBox,QAbstractSpinBox)) and not obj.hasFocus():
            area=obj.parentWidget()
            while area is not None and not isinstance(area,QAbstractScrollArea):
                area=area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(),event)
            return True
        return False


def calm_wheel(root):
    """Lists and number boxes get focus only by clicking (not by the wheel)."""
    for widget in root.findChildren(QComboBox)+root.findChildren(QAbstractSpinBox):
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


def build_workspace(w, Canvas, BRAND_ICON):
    """Construct UI fields expected by Window methods without altering logic."""
    w.setWindowTitle(f'{DISPLAY_NAME}  •  Studio')
    w.resize(1490,890)
    w.setMinimumSize(1040,690)
    w.theme_assets=Path(BRAND_ICON).parent
    import theme
    theme.set_current(theme.load_saved())
    w.setStyleSheet(theme_stylesheet(theme.current(),w.theme_assets))
    root=QWidget();root.setObjectName('root')
    w.setCentralWidget(root)
    outer=QVBoxLayout(root)
    outer.setContentsMargins(10,8,10,10)
    outer.setSpacing(10)

    # Original compact StrokeScribe branding, drawn using native Qt widgets.
    # The three brand dots are decoration, NOT fake OS close/minimize buttons.
    bar=QFrame(); bar.setObjectName('topBar')
    bar_l=QHBoxLayout(bar); bar_l.setContentsMargins(12,7,10,7)
    bar_l.setSpacing(8)
    if BRAND_ICON.is_file():
        icon=brand_icon(BRAND_ICON)
        w.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)
        logo=QLabel(); logo.setObjectName('brandLogo')
        logo.setPixmap(crisp_pixmap(BRAND_ICON,30,w))
        w.brand_logo=logo
        bar_l.addWidget(logo)
    title=QHBoxLayout();title.setSpacing(10)
    w.brand_wordmark=QLabel(wordmark_html())
    w.brand_wordmark.setObjectName('brandWordmark')
    w.brand_wordmark.setFont(QFont('Segoe UI',15,QFont.Weight.Bold))
    title.addWidget(w.brand_wordmark)
    w.brand_version=label(f'Prototype v{APP_VERSION}','subtitle')
    title.addWidget(w.brand_version)
    w.brand_version.hide()           # the version button already shows it
    bar_l.addLayout(title)
    bar_l.addStretch(1)
    from PySide6.QtWidgets import QToolButton, QMenu
    w.project_menu=QToolButton()
    w.project_menu.setObjectName('subtle')
    w.project_menu.setText('▣  Sample drawing  ▾')
    w.project_menu.setToolTip('Current artwork. Choose Import SVG or Import Image to replace it.')
    w.project_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    projects=QMenu(w.project_menu)
    projects.addAction('Open project…',lambda: w.open_project())
    projects.addAction('Save project',lambda: w.save_project())
    projects.addAction('Save project as…',lambda: w.save_project(save_as=True))
    projects.addSeparator()
    projects.addAction('Import SVG artwork…',w.open_svg_source)
    projects.addAction('Import PNG / JPG artwork…',w.open_image_source)
    projects.addSeparator()
    projects.addAction('Batch export…',lambda: w.open_batch_export())
    projects.addSeparator()
    projects.addAction('Update StrokeScribe…',lambda: w.open_updates())
    w.project_menu.setMenu(projects)
    bar_l.addWidget(w.project_menu)
    w.output_summary=label('1920 × 1080  •  30 fps','micro')
    bar_l.addWidget(w.output_summary)
    w.undo_button=QPushButton('↶')
    w.undo_button.setToolTip('Undo (Ctrl+Z): settings and line changes')
    w.undo_button.setObjectName('subtle')
    w.undo_button.setEnabled(False)
    w.undo_button.clicked.connect(w.undo_stroke_order)
    bar_l.addWidget(w.undo_button)
    w.redo_button=QPushButton('↷')
    w.redo_button.setToolTip('Redo (Ctrl+Y)')
    w.redo_button.setObjectName('subtle')
    w.redo_button.setEnabled(False)
    w.redo_button.clicked.connect(w.redo_stroke_order)
    bar_l.addWidget(w.redo_button)
    w.help_button=QPushButton('?')
    w.help_button.setToolTip('Quick help')
    w.help_button.setObjectName('subtle')
    w.help_button.clicked.connect(w.show_quick_help)
    bar_l.addWidget(w.help_button)
    w.settings_button=QPushButton('⚙')
    w.settings_button.setToolTip('Setup & system check: quality level, what is installed and where')
    w.settings_button.setObjectName('subtle')
    w.settings_button.clicked.connect(w.open_setup)
    bar_l.addWidget(w.settings_button)
    w.library_button=QPushButton('▤  Library')
    w.library_button.setToolTip('Your saved images and hands. Copies are kept in a folder you choose.')
    w.library_button.clicked.connect(lambda checked=False: w.open_library('images'))
    bar_l.addWidget(w.library_button)
    w.create_image_button=QPushButton('✦  Create image')
    w.create_image_button.setToolTip('AI line art for your image, new images from text, or edits '
                                     '(local models; runs on your graphics card).')
    w.create_image_button.clicked.connect(lambda checked=False: w.open_create_image())
    bar_l.addWidget(w.create_image_button)
    w.update_button=QPushButton('⬆ Update')
    w.update_button.setObjectName('primary')
    w.update_button.setToolTip('A new StrokeScribe version is ready. Click to update (no unzipping, no Setup).')
    w.update_button.clicked.connect(lambda checked=False: w.open_updates())
    w.update_button.hide()
    bar_l.addWidget(w.update_button)
    w.theme_button=QPushButton()
    w.theme_button.setObjectName('subtle')
    w.theme_button.clicked.connect(lambda checked=False: w.toggle_theme())
    bar_l.addWidget(w.theme_button)
    w.version_button=QPushButton(f'v{APP_VERSION}')
    w.version_button.setObjectName('subtle')
    w.version_button.clicked.connect(w.show_version_info)
    w.version_button.setToolTip('About / build version')
    bar_l.addWidget(w.version_button)
    quick_export=QPushButton('Export Animation')
    quick_export.setObjectName('primary')
    quick_export.clicked.connect(w.open_export)
    bar_l.addWidget(quick_export)
    w.quick_export=quick_export
    outer.addWidget(bar)
    # Update banner (like a chat app): appears only when a new version is ready.
    w.update_banner=QFrame();w.update_banner.setObjectName('updateBanner')
    ub=QHBoxLayout(w.update_banner);ub.setContentsMargins(14,7,10,7);ub.setSpacing(8)
    w.update_banner_text=QLabel('');w.update_banner_text.setObjectName('bannerText')
    w.update_banner_text.setWordWrap(True)
    ub.addWidget(w.update_banner_text,1)
    w.banner_news=QPushButton("What's new");w.banner_news.setObjectName('subtle')
    w.banner_news.clicked.connect(lambda checked=False: w.show_whats_new())
    ub.addWidget(w.banner_news)
    w.banner_update=QPushButton('Update now');w.banner_update.setObjectName('primary')
    w.banner_update.clicked.connect(lambda checked=False: w.banner_update_clicked())
    ub.addWidget(w.banner_update)
    w.banner_later=QPushButton('Later');w.banner_later.setObjectName('subtle')
    w.banner_later.clicked.connect(lambda checked=False: w.update_banner.hide())
    ub.addWidget(w.banner_later)
    w.update_banner.hide()
    outer.addWidget(w.update_banner)

    split=QSplitter(Qt.Orientation.Horizontal)
    split.setObjectName('workspaceSplit')
    w.workspace_splitter=split
    split.setChildrenCollapsible(False)
    # Panels above, timeline below, with a divider you can drag (like an editor).
    w.vertical_splitter=QSplitter(Qt.Orientation.Vertical)
    w.vertical_splitter.setObjectName('timelineSplit')
    w.vertical_splitter.setChildrenCollapsible(False)
    w.vertical_splitter.addWidget(split)
    outer.addWidget(w.vertical_splitter,1)

    # Source and stroke order (left).
    asset_panel,asset_outer,_=panel('assetPanel','Source','Artwork & paths')
    asset_panel.setMinimumWidth(235)
    asset=QWidget();asset.setObjectName('panelBody')
    asset_l=QVBoxLayout(asset);asset_l.setContentsMargins(12,10,12,12)
    asset_l.setSpacing(9)
    asset_l.addWidget(caption('Import artwork or generate single-line lettering.'))
    w.source_type=QComboBox(); w.source_type.addItems(['SVG source','Image source'])
    asset_l.addWidget(w.source_type)
    w.import_button=QPushButton('Import SVG…')
    w.import_button.setObjectName('primary')
    w.import_button.clicked.connect(w.load)
    asset_l.addWidget(w.import_button)
    w.image_controls=QWidget()
    image_form=form_layout();w.image_controls.setLayout(image_form);w.image_source_form=image_form
    image_form.addRow(caption('Line art: clean, artist-style pen strokes from any image, '
                              'drawn by a small built-in line model. Original colors are painted afterwards.'))
    w.image_animation_style=QComboBox()
    w.image_animation_style.addItems(['Artist (layered)','Standard'])
    w.image_animation_style.setToolTip('Artist: light guide shapes first, then the main lines area by area '
                                       '(densest detail last, drawn more slowly), then dark accents, '
                                       'like a real pencil drawing. Standard: one pass of lines.')
    image_form.addRow('Animation',w.image_animation_style)
    w.image_style=QComboBox();w.image_style.addItems(['Clean drawing','Detailed (all lines)'])
    w.image_style.setToolTip('Clean drawing: fewer, longer, smooth strokes like an artist\'s drawing; '
                             'shading is revealed by the colour painting. Detailed: every line found.')
    image_form.addRow('Drawing style',w.image_style)
    w.image_detail=QComboBox();w.image_detail.addItems(['Low','Medium','High','Max'])
    w.image_detail.setCurrentIndex(1)
    w.image_detail.setToolTip('How many inner lines are drawn. Medium is recommended; Max draws the most detail and takes a little longer.')
    image_form.addRow('Detail',w.image_detail)
    w.clean_faint=QCheckBox('Clean the background (fake transparency, leftovers)')
    w.clean_faint.setToolTip('Removes nearly invisible pixels (under 25% visible) left by background removal, '
                             'so neither the drawing nor the hand goes there.')
    image_form.addRow(w.clean_faint)
    w.preserve_colors=QCheckBox('Preserve original colors')
    w.preserve_colors.setChecked(True)
    image_form.addRow(w.preserve_colors)
    w.image_duration=w.number(.2,120,8,.5)
    # Painting timing belongs in the Animation inspector.
    w.image_duration.setParent(w.image_controls)
    w.rebuild_button=QPushButton('Apply image settings')
    w.rebuild_button.clicked.connect(w.rebuild_image)
    image_form.addRow(w.rebuild_button)
    w.ai_lineart_button=QPushButton('✦  AI line art for this image…')
    w.ai_lineart_button.setToolTip('An AI model redraws the image as clean line art; StrokeScribe '
                                   'traces those lines and paints your original colours.')
    w.ai_lineart_button.clicked.connect(lambda checked=False: w.open_create_image())
    image_form.addRow(w.ai_lineart_button)
    w.own_lines_button=QPushButton('Use my own line drawing…')
    w.own_lines_button.setToolTip('Already have a black line drawing of this image (for example from '
                                  'ChatGPT)? StrokeScribe lines it up with the image and traces it.')
    w.own_lines_button.clicked.connect(lambda checked=False: w.use_own_line_drawing())
    image_form.addRow(w.own_lines_button)
    w.export_svg_button=QPushButton('Export drawing as SVG…')
    w.export_svg_button.setToolTip('Save the strokes as an editable SVG plus the matching colour PNG. '
                                   'Fix any line in Inkscape, then import with SVG source.')
    w.export_svg_button.clicked.connect(lambda checked=False: w.export_svg())
    image_form.addRow(w.export_svg_button)
    w.image_controls.hide()
    asset_l.addWidget(w.image_controls)
    asset_l.addWidget(label('TEXT / HANDWRITING'))
    w.text=QPlainTextEdit('Hello world!')
    w.text.setMaximumHeight(74)
    asset_l.addWidget(w.text)
    from font_library import STARTER_FONTS
    w.font_select=QComboBox()
    w.font_select.setEditable(True)
    w.font_select.addItem('Built-in single-line pen')
    from font_library import FONT_GROUPS
    for group,families in FONT_GROUPS.items():
        w.font_select.insertSeparator(w.font_select.count())
        for family in families:
            w.font_select.addItem(family)
            w.font_select.setItemData(w.font_select.count()-1,f'{group} • free Google Font (open license, '
                                      'commercial use allowed). Downloaded when you choose it.',Qt.ItemDataRole.ToolTipRole)
    w.font_select.setToolTip('Select an open-licensed Google Fonts family. Download before use, or import your own TTF/OTF.')
    asset_l.addWidget(w.font_select)
    w.font_size=w.number(24,128,68,4)
    font_size_form=form_layout()
    w.font_size.setToolTip('How finely the letters are traced into pen lines. Higher: smoother letters '
                           '(more small lines, slower to prepare). Lower: simpler letters. It does NOT change '
                           'how big the text is: use Artwork size (Animation tab) for that.')
    font_size_form.addRow('Letter detail',w.font_size)
    asset_l.addLayout(font_size_form)
    style_form=form_layout()
    w.font_color_button=QPushButton('Letter color: #25364A')
    w.font_color_button.setToolTip('Choose the ink color of handwritten text. Applies to current lettering and future lettering.')
    w.font_color_button.clicked.connect(w.choose_letter_color)
    style_form.addRow('Ink color',w.font_color_button)
    w.font_bg_mode=QComboBox()
    w.font_bg_mode.addItems(['Transparent (default)','White','Black','Custom color…'])
    w.font_bg_mode.setToolTip('Background of lettering exports and preview, independent of the checkerboard preview setting.')
    w.font_bg_mode.currentIndexChanged.connect(w.select_letter_background)
    style_form.addRow('Lettering background',w.font_bg_mode)
    w.font_bg_mode.hide(); style_form.labelForField(w.font_bg_mode).hide()   # one Background for all (top)
    asset_l.addLayout(style_form)
    w.generate_text=QPushButton('Animate lettering')
    w.generate_text.clicked.connect(w.letter)
    asset_l.addWidget(w.generate_text)
    w.download_font=QPushButton('Download selected font')
    w.download_font.clicked.connect(w.install_selected_font)
    asset_l.addWidget(w.download_font)
    from font_library import STARTER_FONTS as _ALL_FONTS
    w.download_starters=QPushButton(f'Download all {len(_ALL_FONTS)} fonts')
    w.download_starters.setToolTip('Download every font in the list at once (about 10–40 MB; already '
                                   'downloaded fonts are skipped). Or choose one and use it: it downloads by itself.')
    w.download_starters.clicked.connect(w.install_starter_fonts)
    asset_l.addWidget(w.download_starters)
    w.import_font_button=QPushButton('Import TTF / OTF…')
    w.import_font_button.clicked.connect(w.import_local_font)
    asset_l.addWidget(w.import_font_button)
    browse_fonts=QPushButton('Browse Google Fonts ↗')
    browse_fonts.setObjectName('subtle')
    browse_fonts.clicked.connect(w.browse_google_fonts)
    asset_l.addWidget(browse_fonts)
    w.font_note=caption('Built-in pen works offline. Google Fonts are downloaded only when requested; license files are saved too.')
    asset_l.addWidget(w.font_note)
    asset_l.addWidget(label('LINES & ORDER'))
    asset_l.addWidget(caption('Click a line on the preview (Ctrl+click for more) or in the list. '
                              'Drag in the list to change the drawing order.'))
    w.order=LineList()
    w.order.dropped.connect(lambda: w.order_dragged())
    w.order.setMinimumHeight(155)
    w.order.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
    w.order.setDragDropMode(QListWidget.DragDropMode.InternalMove)
    w.order.setDefaultDropAction(Qt.DropAction.MoveAction)
    w.order.itemSelectionChanged.connect(lambda: w.lines_selected())
    asset_l.addWidget(w.order,1)
    reorder=QHBoxLayout()
    for text,direction in [('Move up',-1),('Move down',1)]:
        button=QPushButton(text)
        button.clicked.connect(lambda checked=False,d=direction:w.move(d))
        reorder.addWidget(button)
    asset_l.addLayout(reorder)
    edit_row=QHBoxLayout()
    w.reverse_button=QPushButton('Reverse')
    w.reverse_button.setToolTip('Draw the selected line(s) from the other end.')
    w.reverse_button.clicked.connect(lambda checked=False: w.reverse_lines())
    edit_row.addWidget(w.reverse_button)
    w.delete_button=QPushButton('Delete')
    w.delete_button.setToolTip('Remove the selected line(s) from the animation (Delete key). Undo brings them back.')
    w.delete_button.clicked.connect(lambda checked=False: w.delete_lines())
    edit_row.addWidget(w.delete_button)
    asset_l.addLayout(edit_row)
    lt=form_layout()
    from stroke_timing import PACES
    w.line_pace=QComboBox()
    w.line_pace.addItems([name for name,_ in PACES])
    w.line_pace.setCurrentText('Normal')
    w.line_pace.setToolTip('Slow down detailed areas or speed through simple lines.')
    w.line_pace.activated.connect(lambda index: w.set_line_pace())
    lt.addRow('Line pace',w.line_pace)
    w.line_pause=w.number(0,10,0,.25)
    w.line_pause.setToolTip('The pen rests at the end of the line before going on.')
    w.line_pause.valueChanged.connect(lambda value: w.set_line_pause())
    lt.addRow('Pause after (s)',w.line_pause)
    asset_l.addLayout(lt)
    for widget in (w.reverse_button,w.delete_button,w.line_pace,w.line_pause):
        widget.setEnabled(False)
    w.note=caption('Ready.')
    asset_l.addWidget(w.note)
    asset_outer.addWidget(scroll_view(asset),1)
    split.addWidget(asset_panel)

    # Large, dedicated visual monitor (center).
    monitor,monitor_outer,top=panel('monitorPanel','Program','Preview monitor')
    monitor.setMinimumWidth(390)
    body=QWidget();body.setObjectName('panelBody')
    monitor_l=QVBoxLayout(body);monitor_l.setContentsMargins(10,10,10,8)
    monitor_l.setSpacing(8)
    monitor_outer.addWidget(body,1)
    from backgrounds import BACKGROUND_ITEMS
    w.preview_background=QComboBox()
    w.preview_background.addItems(list(BACKGROUND_ITEMS))
    w.preview_background.setToolTip('Background of the whole video — drawings, images and lettering, the '
                                    'preview and every export. Transparent: MOV, WebM and PNG keep '
                                    'transparency (MP4 is then white).')
    w.preview_background.setAccessibleName('Background')
    top.addWidget(label('Background','panelHint'))
    top.addWidget(w.preview_background)
    well=QFrame();well.setObjectName('monitorWell')
    well_l=QVBoxLayout(well);well_l.setContentsMargins(1,1,1,1)
    w.canvas=Canvas()
    w.canvas.setMinimumSize(360,250)
    well_l.addWidget(w.canvas)
    monitor_l.addWidget(well,1)
    # Transport under the picture, as in a video editor's program monitor.
    transport=QFrame();transport.setObjectName('transport')
    tr=QHBoxLayout(transport);tr.setContentsMargins(4,0,4,0);tr.setSpacing(6)
    w.clock=label('0.00 / 0.00 s','timeCode')
    w.clock.setMinimumWidth(104)
    tr.addWidget(w.clock)
    tr.addStretch(1)
    w.to_start=QPushButton();w.to_start.setObjectName('transportButton')
    w.to_start.setToolTip('Go to start (Home)')
    w.to_start.clicked.connect(lambda checked=False: w.slider.setValue(0))
    tr.addWidget(w.to_start)
    w.restart_button=QPushButton();w.restart_button.setObjectName('transportButton')
    w.restart_button.setToolTip('Restart and play')
    w.restart_button.clicked.connect(w.restart)
    tr.addWidget(w.restart_button)
    w.play=QPushButton();w.play.setObjectName('playButton')
    w.play.setToolTip('Play / pause (Space)')
    w.play.clicked.connect(w.toggle)
    tr.addWidget(w.play)
    w.to_end=QPushButton();w.to_end.setObjectName('transportButton')
    w.to_end.setToolTip('Go to end (End)')
    w.to_end.clicked.connect(lambda checked=False: w.slider.setValue(1000))
    tr.addWidget(w.to_end)
    w.mute_button=QPushButton();w.mute_button.setObjectName('transportButton')
    w.mute_button.setToolTip('Sound on / off: pencil, brush and eraser sounds, in the preview and the exported video')
    w.mute_button.clicked.connect(lambda checked=False: w.sound_on.setChecked(not w.sound_on.isChecked()))
    tr.addWidget(w.mute_button)
    tr.addStretch(1)
    w.clock_total=label('','timeTotal')
    w.clock_total.setMinimumWidth(104)
    w.clock_total.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
    tr.addWidget(w.clock_total)
    monitor_l.addWidget(transport)
    w.preview_background.activated.connect(lambda index: w.background_chosen(index))
    w.preview_background.currentIndexChanged.connect(lambda index: w.show_background())
    w.preview_background.currentIndexChanged.connect(
        lambda index: 0<index<=6 and w.mp4_background.setCurrentIndex(index-1 if index<=2 else index))
    split.addWidget(monitor)

    # Inspector settings grouped by task (right).
    inspector,inspector_l,_=panel('inspectorPanel','Inspector')
    inspector.setMinimumWidth(270)
    tabs=QTabWidget()
    tabs.setDocumentMode(True)
    w.inspector_tabs=tabs
    inspector_l.addWidget(tabs,1)

    animation=QWidget()
    animation_l=QVBoxLayout(animation);animation_l.setContentsMargins(9,12,9,8)
    animation_l.setSpacing(10)
    animation_l.addWidget(label('DRAWING'))
    a=form_layout();animation_l.addLayout(a)
    w.duration=w.number(.2,120,4,.1);a.addRow('Draw time (s)',w.duration)
    w.speed=w.number(.1,5,1,.1);a.addRow('Playback speed',w.speed)
    w.thickness=w.number(.1,10,1,.1);a.addRow('Line width',w.thickness)
    w.artwork_size=w.number(25,200,100,5)
    w.artwork_size.setSuffix('%')
    w.artwork_size.setToolTip('Scale only the artwork, not the hand. The hand size stays controlled by Hand Size. Above 100% may crop the artwork.')
    a.addRow('Artwork size',w.artwork_size)
    # Position on the page: drag the picture on the preview, or type it here.
    w.picture_x=w.number(-100,100,0,1); w.picture_x.setSuffix('%')
    w.picture_y=w.number(-100,100,0,1); w.picture_y.setSuffix('%')
    for box,side in ((w.picture_x,'right (minus: left)'),(w.picture_y,'down (minus: up)')):
        box.setToolTip(f'Move the picture {side}, in % of the video size. '
                       'Easier: drag the picture on the preview.')
    w.picture_center=QPushButton('Center'); w.picture_center.setObjectName('subtle')
    w.picture_center.setToolTip('Put the picture back in the middle.')
    w.picture_center.clicked.connect(lambda checked=False: (w.picture_x.setValue(0), w.picture_y.setValue(0)))
    position=QHBoxLayout(); position.setSpacing(6)
    position.addWidget(w.picture_x,1); position.addWidget(w.picture_y,1); position.addWidget(w.picture_center)
    a.addRow('Position X / Y',position)
    w.pen_ease=QComboBox()
    w.pen_ease.addItems(['Constant speed','Natural (ease in and out)'])
    w.pen_ease.setToolTip('Natural: every line starts and ends a little slower, like a real hand.')
    a.addRow('Pen movement',w.pen_ease)
    from frame_render import ENTRANCES
    w.entrance=QComboBox(); w.entrance.addItems(list(ENTRANCES))
    w.entrance.setToolTip('How this element appears: drawn by the hand, or with an effect (no hand) '
                          'during its animation time.')
    a.addRow('Comes in',w.entrance)
    w.pause_after=w.number(0,60,0,.5)
    w.pause_after.setToolTip('Seconds the finished element stays on screen before it goes out or the '
                             'camera moves on (works with or without colours).')
    a.addRow('Pause after (s)',w.pause_after)
    w.camera=QComboBox()
    w.camera.addItems(['Off','Gentle zoom','Close-up zoom'])
    w.camera.setToolTip('Camera follow: the view zooms in and glides after the pen, then pulls back '
                        'to show the whole picture at the end.')
    a.addRow('Camera follow',w.camera)
    w.auto_timing_button=QPushButton('Auto timing')
    w.auto_timing_button.setToolTip('Pick draw, paint and hold times from how much there is to draw '
                                    'and paint (or from the voiceover length, if one is loaded).')
    w.auto_timing_button.clicked.connect(lambda checked=False: w.auto_timing())
    a.addRow(w.auto_timing_button)
    animation_l.addWidget(label('COLOR & PAINTING'))
    w.load_color_button=QPushButton('Load matching colored PNG…')
    w.load_color_button.clicked.connect(w.load_color)
    animation_l.addWidget(w.load_color_button)
    w.clean_color=QCheckBox('Clean the PNG\'s background')
    w.clean_color.setChecked(True)
    w.clean_color.setToolTip('Makes the transparency complete: a painted checkerboard ("fake transparency") '
                             'or a plain sheet behind the artwork, and faint leftovers, become transparent. '
                             'Parts inside the artwork are kept.')
    w.clean_color.toggled.connect(lambda checked: w.reload_color())
    animation_l.addWidget(w.clean_color)
    w.use_color=QCheckBox('Reveal original artwork after drawing')
    w.use_color.setEnabled(False)
    animation_l.addWidget(w.use_color)
    w.color_note=caption('No original PNG loaded')
    animation_l.addWidget(w.color_note)
    a2=form_layout();animation_l.addLayout(a2)
    w.reveal_mode=QComboBox()
    w.reveal_mode.addItems(['Brush painting','Adaptive Hand Painting','Zigzag sweep'])
    w.reveal_mode.setCurrentIndex(1)
    w.reveal_mode.setItemData(2,'The hand follows one route along the object, scribbling colour '
                              'back and forth across it (wider on broad parts).',Qt.ItemDataRole.ToolTipRole)
    a2.addRow('Paint mode',w.reveal_mode)
    w.image_paint_hint=caption('Image sources paint with Adaptive Hand Painting or Zigzag sweep. Original PNG colors are preserved.')
    a2.addRow(w.image_paint_hint)
    w.color_fade=w.number(0,20,.4,.1);a2.addRow('SVG paint time (s)',w.color_fade)
    a2.addRow('Image paint time (s)',w.image_duration)
    w.paint_form=a2
    w.image_animation=QComboBox()
    w.image_animation.addItems(['Draw, then Paint','Paint Only'])
    w.image_animation.setToolTip(
        'Draw, then Paint: draw temporary lines and replace them while painting. '
        'Paint Only: skip all visible line drawing and paint colors directly. '
        'Both use the same AI path analysis and brush coverage; there is no separate erasing phase.')
    a2.addRow('Image animation',w.image_animation)
    w.image_animation.currentIndexChanged.connect(w.change_image_animation)
    w.brush_width=w.number(.02,.5,.14,.02);a2.addRow('Brush width',w.brush_width)
    w.stroke_spacing=w.number(.2,.9,.55,.05)
    w.stroke_spacing.setToolTip('Lower values add more overlap between brush strokes.')
    a2.addRow('Stroke spacing',w.stroke_spacing)
    w.color_hold=w.number(0,30,.6,.1);a2.addRow('Hold (s)',w.color_hold)
    animation_l.addWidget(label('GOES OUT AT THE END'))
    a3=form_layout();animation_l.addLayout(a3)
    from eraser import MODES as _EXITS
    w.erase_mode=QComboBox()
    w.erase_mode.addItems(list(_EXITS))
    w.erase_mode.setToolTip('At the end the element goes away: an eraser rubs it out (Zigzag: back and forth '
                            'over the picture; Along the lines: last line first), or it fades, pops, '
                            'zooms, spins or moves out.')
    a3.addRow('Goes out',w.erase_mode)
    w.erase_time=w.number(.3,30,3,.5);a3.addRow('Out time (s)',w.erase_time)
    w.erase_size=QSpinBox();w.erase_size.setRange(2,30);w.erase_size.setValue(8);w.erase_size.setSuffix('%')
    w.erase_size.setToolTip('Width of the rubbing area, as a share of the video width.')
    a3.addRow('Eraser size',w.erase_size)
    w.eraser=QComboBox();w.eraser.addItems(['Built-in eraser','Pen hand'])
    w.eraser.setToolTip('What is shown rubbing: the built-in eraser, or the same hand as for drawing.')
    a3.addRow('Eraser shown',w.eraser)
    animation_l.addStretch(1)
    tabs.addTab(scroll_view(animation),'Animation')

    hand=QWidget();hand_l=QVBoxLayout(hand)
    hand_l.setContentsMargins(9,12,9,8);hand_l.setSpacing(12)
    hand_l.addWidget(label('HAND & PEN'))
    load_hand=QPushButton('Load transparent hand PNG…')
    load_hand.clicked.connect(w.loadhand)
    hand_l.addWidget(load_hand)
    hands_library=QPushButton('Hands library…')
    hands_library.clicked.connect(lambda checked=False: w.open_library('hands'))
    hand_l.addWidget(hands_library)
    builtin_row=QHBoxLayout()
    for text,name,tip in (('Built-in hand','hand','Hand holding a pen (default).'),
                          ('Pencil','pencil','A pencil on its own, no hand.'),
                          ('Marker','marker','A marker on its own, no hand.')):
        button=QPushButton(text); button.setToolTip(tip)
        button.clicked.connect(lambda checked=False,n=name: w.use_builtin_tool(n))
        builtin_row.addWidget(button)
    hand_l.addLayout(builtin_row)
    w.hand_name=caption('Hand: none')
    hand_l.addWidget(w.hand_name)
    w.showhand=QCheckBox('Show hand while drawing')
    w.showhand.setChecked(True);hand_l.addWidget(w.showhand)
    w.left_handed=QCheckBox('Left-handed (the hand comes from the left)')
    w.left_handed.setToolTip('Mirrors the drawing hand, the painting brush and the eraser, for left-handers.')
    hand_l.addWidget(w.left_handed)
    hand_l.addWidget(caption('New hands get their pen tip found automatically. '
                             'Adjust it here if lines do not start exactly at the pen.'))
    tip_row=QHBoxLayout()
    w.find_tip_button=QPushButton('Find pen tip')
    w.find_tip_button.setToolTip('Look for the pen tip in the hand image automatically.')
    w.find_tip_button.clicked.connect(lambda checked=False: w.find_pen_tip())
    tip_row.addWidget(w.find_tip_button)
    w.pick_tip_button=QPushButton('Click to set…')
    w.pick_tip_button.setToolTip('Show the hand and click exactly on the pen tip.')
    w.pick_tip_button.clicked.connect(lambda checked=False: w.pick_pen_tip())
    tip_row.addWidget(w.pick_tip_button)
    hand_l.addLayout(tip_row)
    h=form_layout();hand_l.addLayout(h)
    w.handsize=w.number(.02,.8,.75,.01);h.addRow('Hand scale',w.handsize)
    # Defaults calibrated for the built-in hand (assets/default_hand.png).
    w.ax=w.number(0,1,.08,.005);w.ax.setDecimals(3);h.addRow('Pen tip X',w.ax)
    w.ay=w.number(0,1,.13,.005);w.ay.setDecimals(3);h.addRow('Pen tip Y',w.ay)
    hand_l.addWidget(label('PAINTING HAND'))
    hand_l.addWidget(caption('When painting starts, the hand can switch to a brush.'))
    w.show_paint_hand=QCheckBox('Show hand while painting')
    w.show_paint_hand.setChecked(True);hand_l.addWidget(w.show_paint_hand)
    from tools_kit import PAINT_CHOICES
    ph=form_layout();hand_l.addLayout(ph)
    w.paint_hand=QComboBox()
    w.paint_hand.addItems(list(PAINT_CHOICES))
    w.paint_hand.setToolTip('Keep the drawing hand, switch to the built-in paint brush, '
                            'or use a hand from your Hands library while painting.')
    ph.addRow('Painting hand',w.paint_hand)
    w.paint_hand_size=w.number(5,90,30,1);w.paint_hand_size.setDecimals(0)
    w.paint_hand_size.setToolTip('Width of the painting hand, as a share of the video width.')
    ph.addRow('Painting hand size (%)',w.paint_hand_size)
    w.paint_hand_choose=QPushButton('Choose painting hand…')
    w.paint_hand_choose.clicked.connect(lambda checked=False: w.choose_paint_hand())
    hand_l.addWidget(w.paint_hand_choose)
    w.paint_hand_name=caption('')
    hand_l.addWidget(w.paint_hand_name)
    hand_l.addStretch(1)
    tabs.addTab(scroll_view(hand),'Hand')

    output=QWidget();output_l=QVBoxLayout(output)
    output_l.setContentsMargins(9,12,9,8);output_l.setSpacing(10)
    output_l.addWidget(label('VIDEO OUTPUT'))
    e=form_layout();output_l.addLayout(e)
    w.res=QComboBox()
    w.res.addItems(['1920 × 1080','2048 × 1080','2560 × 1440'])
    e.addRow('Resolution',w.res)
    w.fps=QSpinBox();w.fps.setRange(1,60);w.fps.setValue(30)
    e.addRow('Frame rate',w.fps)
    output_l.addWidget(label('FORMATS'))
    w.webm=QCheckBox('Compact WebM (VP9 + alpha)')
    w.webm.setToolTip('Filmora import of third-party WebM transparency must be tested.')
    output_l.addWidget(w.webm)
    w.webm_quality=QSpinBox()
    w.webm_quality.setRange(18,42);w.webm_quality.setValue(28)
    w.webm_quality.setToolTip('Lower means higher quality and generally larger files.')
    w.webm_quality.setMinimumWidth(110)
    e2=form_layout();e2.addRow('WebM quality',w.webm_quality)
    output_l.addLayout(e2)
    output_l.addWidget(caption('WebM quality: 18 = best, largest file  •  42 = smallest file.'))
    w.mov=QCheckBox('ProRes 4444 MOV (larger)')
    output_l.addWidget(w.mov)
    w.mp4=QCheckBox('Standard MP4 (H.264, solid background)')
    w.mp4.setToolTip('Plays everywhere. MP4 has no transparency, so the animation sits on the chosen background.')
    output_l.addWidget(w.mp4)
    w.mp4_background=QComboBox()
    w.mp4_background.addItems(['White','Dark','Black','Whiteboard','Paper','Chalkboard','Cork'])
    w.mp4_background.setToolTip('Background of the MP4: a colour or a texture (matches the preview backgrounds).')
    e3=form_layout();e3.addRow('MP4 background',w.mp4_background)
    output_l.addLayout(e3)
    # One Background for everything now (top of the preview); kept for older projects.
    w.mp4_background.hide(); e3.labelForField(w.mp4_background).hide()
    w.background_note=label('Background: chosen above the preview (the same for the whole video).','note')
    w.background_note.setWordWrap(True)
    output_l.addWidget(w.background_note)
    from frame_render import LAYERS
    w.export_layers=QComboBox();w.export_layers.addItems(list(LAYERS))
    w.export_layers.setToolTip('Hand only: just the moving hand on a transparent background, to lay over '
                               'your own text or picture in Filmora. The preview shows the drawing faintly.')
    w.export_layers.currentIndexChanged.connect(w.refresh)
    el=form_layout();el.addRow('Export',w.export_layers)
    output_l.addLayout(el)
    w.export_all_scenes=QCheckBox('Export all elements as one video')
    w.export_all_scenes.setChecked(True)
    w.export_all_scenes.setToolTip('With several scenes: one video with every scene and the moves between them. '
                                   'Off: only the scene you are editing.')
    output_l.addWidget(w.export_all_scenes)
    w.fast_export=QCheckBox('Use all CPU cores (faster export)')
    w.fast_export.setChecked(True)
    w.fast_export.setToolTip('Longer exports are rendered on several processor cores at once. '
                             'Turn off if the computer must stay responsive during an export.')
    output_l.addWidget(w.fast_export)
    w.export_done_sound=QCheckBox('Play a sound when the export is finished')
    w.export_done_sound.setChecked(True)
    w.export_done_sound.setToolTip("Windows' notification sound, so you know the video is ready.")
    output_l.addWidget(w.export_done_sound)
    w.keep_png=QCheckBox('Keep generated PNG frames')
    w.keep_png.setChecked(False)
    w.keep_png.setToolTip('If video encoding succeeds, frame PNGs can be removed.')
    output_l.addWidget(w.keep_png)
    output_l.addWidget(caption('If no video format is selected, all transparent PNG frames are kept.'))
    w.export=QPushButton('Export animation…')
    w.export.setObjectName('primary');w.export.clicked.connect(w.save)
    output_l.addWidget(w.export)
    w.batch_button=QPushButton('Batch export…')
    w.batch_button.setToolTip('Export many images, SVGs or projects in one go.')
    w.batch_button.clicked.connect(lambda checked=False: w.open_batch_export())
    output_l.addWidget(w.batch_button)
    w.cancel=QPushButton('Cancel export')
    w.cancel.setEnabled(False);w.cancel.clicked.connect(w.cancel_export)
    output_l.addWidget(w.cancel)
    output_l.addWidget(caption('Export progress appears below the timeline.'))
    output_l.addStretch(1)
    tabs.addTab(scroll_view(output),'Export')
    # Sound tab: drawing sounds and the voiceover / music track.
    sound=QWidget();sound_l=QVBoxLayout(sound)
    sound_l.setContentsMargins(9,12,9,8);sound_l.setSpacing(10)
    sound_l.addWidget(label('SOUND'))
    w.sound_on=QCheckBox('Pencil and brush sounds')
    w.sound_on.setChecked(False)
    w.sound_on.setToolTip('A pencil sound while the pen draws (silent during pen lifts), a brush sound '
                          'while painting and an eraser sound while erasing, matched to the animation.')
    sound_l.addWidget(w.sound_on)
    sound_l.addWidget(caption('Add your own sounds: a few seconds of a pencil on paper (and a brush or an '
                               'eraser if you like). They play only while the pen moves. No sound is added '
                               'until you choose one.'))
    create_sound=QPushButton('✦ Create a sound with AI…')
    create_sound.setToolTip('Describe a sound (pencil on paper, brush, eraser) and let a free AI model '
                            'make it on your PC.')
    create_sound.clicked.connect(lambda checked=False: w.open_create_image('sound'))
    sound_l.addWidget(create_sound)
    w.sound_file_buttons={}
    for key,text in (('sound_pencil_file','Pencil'),('sound_brush_file','Brush'),('sound_eraser_file','Eraser')):
        row=QHBoxLayout()
        button=QPushButton(f'{text} sound…')
        button.setToolTip(f'Choose a recording (MP3, WAV, M4A…) for the {text.lower()}.')
        button.clicked.connect(lambda checked=False,k=key: w.choose_sound_file(k))
        row.addWidget(button,1)
        reset=QPushButton('Remove')
        reset.setToolTip(f'No {text.lower()} sound.')
        reset.clicked.connect(lambda checked=False,k=key: w.set_sound_file(k,None))
        row.addWidget(reset)
        sound_l.addLayout(row)
        w.sound_file_buttons[key]=(button,text)
    w.sound_volume=QSpinBox();w.sound_volume.setRange(0,100);w.sound_volume.setValue(80)
    w.sound_volume.setSuffix('%')
    e4=form_layout();e4.addRow('Sound volume',w.sound_volume)
    sound_l.addLayout(e4)
    w.sound_preview=QCheckBox('Hear the sound when playing the preview')
    w.sound_preview.setChecked(True)
    sound_l.addWidget(w.sound_preview)
    sound_l.addWidget(caption('Included in MP4, WebM and MOV. PNG exports also get soundtrack.wav.'))
    sound_l.addWidget(label('VOICEOVER / MUSIC'))
    audio_row=QHBoxLayout()
    w.load_audio_button=QPushButton('Load audio…')
    w.load_audio_button.setToolTip('Add a voiceover or music track (MP3, WAV, M4A, OGG, FLAC…).')
    w.load_audio_button.clicked.connect(lambda checked=False: w.load_audio())
    audio_row.addWidget(w.load_audio_button)
    audio_library=QPushButton('Library…')
    audio_library.clicked.connect(lambda checked=False: w.open_library('audio'))
    audio_row.addWidget(audio_library)
    w.remove_audio_button=QPushButton('Remove')
    w.remove_audio_button.setEnabled(False)
    w.remove_audio_button.clicked.connect(lambda checked=False: w.remove_audio())
    audio_row.addWidget(w.remove_audio_button)
    sound_l.addLayout(audio_row)
    w.audio_note=caption('No audio track')
    sound_l.addWidget(w.audio_note)
    e5=form_layout()
    w.audio_volume=QSpinBox();w.audio_volume.setRange(0,200);w.audio_volume.setValue(100)
    w.audio_volume.setSuffix('%');e5.addRow('Track volume',w.audio_volume)
    w.audio_offset=w.number(0,600,0,.1)
    w.audio_offset.setToolTip('Seconds into the video when the track starts.')
    e5.addRow('Starts at (s)',w.audio_offset)
    sound_l.addLayout(e5)
    w.fit_audio_button=QPushButton('Fit animation to audio')
    w.fit_audio_button.setEnabled(False)
    w.fit_audio_button.setToolTip('Stretch draw, paint, hold and erase times so the video ends when the track ends.')
    w.fit_audio_button.clicked.connect(lambda checked=False: w.fit_to_audio())
    sound_l.addWidget(w.fit_audio_button)
    sound_l.addStretch(1)
    tabs.insertTab(TABS['sound'],scroll_view(sound),'Sound')      # before Export
    split.addWidget(inspector)
    split.setStretchFactor(0,0)
    split.setStretchFactor(1,1)
    split.setStretchFactor(2,0)
    split.setSizes([290,850,330])

    # Time-based workflow remains visible whichever Inspector tab is open.
    timeline,timeline_outer,timeline_head=panel('timelinePanel','Timeline','Click or drag to scrub')
    # Overlays (pictures and titles on top of the scene, on their own tracks).
    w.add_picture_overlay=QPushButton('+ Picture'); w.add_picture_overlay.setObjectName('subtle')
    w.add_picture_overlay.setToolTip('Put a picture on top of this scene (PNG, JPG or SVG), with an entrance '
                                     'effect. It appears at the playhead; drag its clip to change when.')
    w.add_picture_overlay.clicked.connect(lambda checked=False: w.add_overlay_picture())
    timeline_head.addWidget(w.add_picture_overlay)
    w.add_text_overlay=QPushButton('+ Text'); w.add_text_overlay.setObjectName('subtle')
    w.add_text_overlay.setToolTip('Put a title or label on top of this scene, with an entrance effect.')
    w.add_text_overlay.clicked.connect(lambda checked=False: w.add_overlay_text())
    timeline_head.addWidget(w.add_text_overlay)
    w.timeline_status=label('','panelHint')
    timeline_head.addWidget(w.timeline_status)
    body=QWidget();body.setObjectName('panelBody')
    line_l=QVBoxLayout(body)
    line_l.setContentsMargins(6,4,6,6);line_l.setSpacing(4)
    timeline_outer.addWidget(body)
    # Scenes: several drawings in one video, joined by camera moves.
    from scenes import TRANSITIONS
    from PySide6.QtCore import QSize
    scene_row=QHBoxLayout();scene_row.setSpacing(6)
    scene_row.addWidget(label('ELEMENTS'))
    w.scene_list=QListWidget()
    w.scene_list.setObjectName('sceneStrip')
    w.scene_list.setFlow(QListWidget.Flow.LeftToRight)
    w.scene_list.setWrapping(False)
    w.scene_list.setViewMode(QListWidget.ViewMode.IconMode)
    w.scene_list.setMovement(QListWidget.Movement.Static)
    w.scene_list.setIconSize(QSize(72,40))
    w.scene_list.setGridSize(QSize(132,78))
    w.scene_list.setFixedHeight(86)
    w.scene_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    w.scene_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.scene_list.setToolTip('The elements of your video, in order (like VideoScribe). Click one to work on it; '
                            'double-click (or Edit…) for its settings: how it comes in, its times, colours, '
                            'how it goes out and the move to the next one.')
    w.scene_list.currentRowChanged.connect(lambda row: w.select_scene(row))
    w.scene_list.itemDoubleClicked.connect(lambda item: w.edit_element(w.scene_list.row(item)))
    scene_row.addWidget(w.scene_list,1)
    scene_buttons=QVBoxLayout();scene_buttons.setSpacing(4)
    w.scene_add=QPushButton('+ Add element')
    w.scene_add.setToolTip('A new element after this one (a copy of it: then import its own SVG, image or text). '
                           'The camera moves to it.')
    w.scene_add.clicked.connect(lambda checked=False: w.add_scene())
    w.scene_picture=QPushButton('+ Same spot')
    w.scene_picture.setToolTip('A new element on the SAME page (no camera move): drawn next to the elements '
                               'before it. Import its artwork, then drag it on the preview to place it.')
    w.scene_picture.clicked.connect(lambda checked=False: w.add_picture())
    add_row=QHBoxLayout();add_row.setSpacing(4)
    add_row.addWidget(w.scene_add); add_row.addWidget(w.scene_picture)
    scene_buttons.addLayout(add_row)
    move_row=QHBoxLayout();move_row.setSpacing(4)
    w.scene_edit=QPushButton('Edit…');w.scene_edit.setObjectName('primary')
    w.scene_edit.setToolTip('Settings of this element in a window of its own, with its own preview: how it '
                            'comes in, times, colours, how it goes out and the move to the next one.')
    w.scene_edit.clicked.connect(lambda checked=False: w.edit_element(w.scene_index))
    w.scene_left=QPushButton('◀');w.scene_left.setToolTip('Move this element earlier')
    w.scene_left.clicked.connect(lambda checked=False: w.move_scene(-1))
    w.scene_right=QPushButton('▶');w.scene_right.setToolTip('Move this element later')
    w.scene_right.clicked.connect(lambda checked=False: w.move_scene(1))
    w.scene_delete=QPushButton('Delete');w.scene_delete.setToolTip('Delete this element')
    w.scene_delete.clicked.connect(lambda checked=False: w.delete_scene())
    for b in (w.scene_edit,w.scene_left,w.scene_right,w.scene_delete): move_row.addWidget(b)
    scene_buttons.addLayout(move_row)
    scene_row.addLayout(scene_buttons)
    trans=QFormLayout();trans.setSpacing(4)
    w.scene_transition=QComboBox();w.scene_transition.addItems(list(TRANSITIONS))
    w.scene_transition.setToolTip('How the camera goes from this element to the next one.')
    w.scene_transition.activated.connect(lambda index: w.scene_transition_changed())
    trans.addRow('Then',w.scene_transition)
    w.scene_transition_time=w.number(.2,6,1.2,.1)
    w.scene_transition_time.setToolTip('Length of the move to the next element (seconds).')
    w.scene_transition_time.valueChanged.connect(lambda value: w.scene_transition_changed())
    trans.addRow('Move (s)',w.scene_transition_time)
    w.preview_scope=QComboBox();w.preview_scope.addItems(['This element','Whole video','Board'])
    w.preview_scope.setToolTip('This element: play the element you work on. Whole video: everything with the '
                               'camera moves. Board: all elements from above — move and resize their frames.')
    w.preview_scope.currentIndexChanged.connect(lambda index: w.preview_scope_changed())
    trans.addRow('Preview',w.preview_scope)
    w.board_arrange=QPushButton('Arrange in a row'); w.board_arrange.setObjectName('subtle')
    w.board_arrange.setToolTip('Put every frame next to the one before it again (following the transitions).')
    w.board_arrange.clicked.connect(lambda checked=False: w.arrange_board())
    w.board_arrange.hide()
    trans.addRow('',w.board_arrange)
    scene_row.addLayout(trans)
    line_l.addLayout(scene_row)
    # The slider keeps the position; the timeline is what you see and drag.
    w.slider=QSlider(Qt.Orientation.Horizontal)
    w.slider.setRange(0,1000);w.slider.valueChanged.connect(w.scrub)
    w.slider.hide()
    line_l.addWidget(w.slider)
    w.stage_timeline=StageTimeline(w.slider)
    line_l.addWidget(w.stage_timeline)
    w.stage_timeline.stage_dragged.connect(lambda key,secs: w.set_stage_seconds(key,secs))
    w.stage_timeline.stage_drag_done.connect(lambda: w.commit_history())
    w.stage_timeline.audio_moved.connect(lambda secs: w.audio_offset.setValue(secs))
    w.audio_offset.valueChanged.connect(lambda value: w.stage_timeline.set_audio(w.timeline_audio()))
    w.stage_timeline.audio_dropped.connect(lambda path: w.audio_dropped(path))
    w.stage_timeline.audio_remove.connect(lambda: w.remove_audio())
    w.stage_timeline.overlay_selected.connect(lambda oid: w.select_overlay(oid))
    w.stage_timeline.overlay_changed.connect(lambda oid,start,length,track: w.move_overlay_clip(oid,start,length,track))
    w.stage_timeline.overlay_done.connect(lambda oid: w.commit_history())
    w.stage_timeline.overlay_edit.connect(lambda oid: w.edit_overlay(oid))
    w.stage_timeline.overlay_action.connect(lambda oid,action: w.overlay_action(oid,action))
    w.stage_timeline.overlay_dropped.connect(lambda path,seconds: w.add_overlay_picture(path,at=seconds))
    w.vertical_splitter.addWidget(timeline)
    w.vertical_splitter.setStretchFactor(0,1)
    w.vertical_splitter.setStretchFactor(1,0)
    w.vertical_splitter.setSizes([620,250])
    footer=QHBoxLayout()
    w.status=label('Ready  •  Import → adjust → preview → export','status')
    w.status.setWordWrap(True)
    footer.addWidget(w.status,1)
    w.progress=QProgressBar();w.progress.setFixedWidth(180);w.progress.setValue(0)
    w.progress.setTextVisible(False);w.progress.setFixedHeight(8)
    footer.addWidget(w.progress)
    outer.addLayout(footer)

    # Retain the existing preview/export signal wiring.
    for widget in (w.duration,w.speed,w.thickness,w.artwork_size,w.picture_x,w.picture_y,w.handsize,w.ax,w.ay):
        widget.valueChanged.connect(w.refresh)
    w.showhand.toggled.connect(w.refresh)
    w.left_handed.toggled.connect(w.refresh)
    w.entrance.currentIndexChanged.connect(w.refresh)
    w.pause_after.valueChanged.connect(w.refresh)
    w.res.currentIndexChanged.connect(w.refresh)
    w.use_color.toggled.connect(w.refresh)
    w.color_fade.valueChanged.connect(w.refresh)
    w.color_hold.valueChanged.connect(w.refresh)
    w.reveal_mode.currentIndexChanged.connect(w.refresh)
    w.brush_width.valueChanged.connect(w.schedule_brush_refresh)
    w.show_paint_hand.toggled.connect(w.refresh)
    w.sound_on.toggled.connect(lambda checked: (w.update_transport_icons(), w.sync_preview_sound()))
    w.paint_hand.activated.connect(lambda index: w.paint_hand_changed())
    w.paint_hand_size.valueChanged.connect(w.refresh)
    w.camera.currentIndexChanged.connect(w.refresh)
    w.pen_ease.currentIndexChanged.connect(w.refresh)
    w.erase_mode.currentIndexChanged.connect(w.prepare_eraser)
    w.eraser.currentIndexChanged.connect(w.refresh)
    for widget in (w.erase_time,w.erase_size):
        widget.valueChanged.connect(w.refresh)
    w.stroke_spacing.valueChanged.connect(w.schedule_brush_refresh)
    w.preserve_colors.toggled.connect(w.refresh)
    w.image_duration.valueChanged.connect(w.refresh)
    w.source_type.currentIndexChanged.connect(w.change_source)
    w.fps.valueChanged.connect(w.sync_workspace)
    w.webm.toggled.connect(w.sync_workspace)
    w.mov.toggled.connect(w.sync_workspace)
    w.mp4.toggled.connect(w.sync_workspace)
    for name in ('duration','speed','thickness','brush_width','stroke_spacing',
                 'image_duration','color_fade','color_hold','fps','res','order'):
        getattr(w,name).setAccessibleName(name.replace('_',' '))
    w.stage_timeline.setAccessibleName('Animation timeline: drag to scrub; arrows to step')
    fit_to_width(asset,stacked=True)       # labels above fields in the narrow column
    for content in (animation,hand,output,sound):
        fit_to_width(content)
    from PySide6.QtGui import QShortcut, QKeySequence
    w.save_shortcut=QShortcut(QKeySequence(QKeySequence.StandardKey.Save),w)
    w.save_shortcut.activated.connect(lambda: w.save_project())
    w.open_shortcut=QShortcut(QKeySequence(QKeySequence.StandardKey.Open),w)
    w.open_shortcut.activated.connect(lambda: w.open_project())
    w.space_shortcut=QShortcut(QKeySequence(Qt.Key.Key_Space),w)
    w.space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
    w.space_shortcut.activated.connect(
        lambda: None if isinstance(QApplication.focusWidget(),(QPlainTextEdit,QComboBox)) else w.toggle())
    w.undo_shortcut=QShortcut(QKeySequence(QKeySequence.StandardKey.Undo),w)
    w.undo_shortcut.activated.connect(lambda: w.undo())
    w.redo_shortcuts=[]
    for keys in (QKeySequence(QKeySequence.StandardKey.Redo),QKeySequence('Ctrl+Y')):
        shortcut=QShortcut(keys,w); shortcut.activated.connect(lambda: w.redo())
        w.redo_shortcuts.append(shortcut)
    w.delete_shortcuts=[]
    for target in (w.canvas,w.order):
        shortcut=QShortcut(QKeySequence(QKeySequence.StandardKey.Delete),target)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(lambda: w.delete_lines())
        w.delete_shortcuts.append(shortcut)
    w.update_theme_button()
    w.sync_workspace()
    calm_wheel(w)
    w.wheel_guard=WheelGuard(w)
    QApplication.instance().installEventFilter(w.wheel_guard)
