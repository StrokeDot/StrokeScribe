"""Original StrokeScribe Studio workspace.

An editor-style layout (source/paths, central monitor, inspector and timeline).
Only the UI is reorganized: rendering and export algorithms stay in their
existing modules. No third-party product assets or lookalike trade dress.
"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QObject, QEvent, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QScrollArea, QSplitter, QVBoxLayout,
    QHBoxLayout, QFormLayout, QPushButton, QLabel, QComboBox, QCheckBox,
    QSpinBox, QListWidget, QPlainTextEdit, QSlider, QTabWidget,
    QProgressBar, QSizePolicy, QAbstractSpinBox, QAbstractScrollArea,
    QGridLayout, QToolButton,
)
from version import APP_VERSION, DISPLAY_NAME


# Colours and the stylesheet live in theme.py (Dark default, Light optional).
from theme import stylesheet as theme_stylesheet, colors as theme_colors


def _jump_slider_class():
    from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider

    class JumpSlider(QSlider):
        """A slider that jumps to where you click on its track (then drags from there),
        instead of moving one step towards the click."""

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                option = QStyleOptionSlider(); self.initStyleOption(option)
                handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                                     QStyle.SubControl.SC_SliderHandle, self)
                if not handle.contains(event.position().toPoint()):
                    span = max(1, self.width() - handle.width())
                    x = int(event.position().x() - handle.width() / 2)
                    self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), x, span,
                                                                 self.invertedAppearance()))
            super().mousePressEvent(event)
    return JumpSlider


def linked_slider(spin, low, high, scale=1):
    """A horizontal slider kept in step with a spin box (the spin box owns the value).
    Click anywhere on the track to jump there, or drag."""
    slider = _jump_slider_class()(Qt.Orientation.Horizontal)
    slider.setRange(round(low * scale), round(high * scale))
    slider.setValue(round(spin.value() * scale))
    slider.setMinimumWidth(30)
    slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def from_slider(value):
        if round(spin.value() * scale) != value:
            spin.setValue(value / scale)

    def from_spin(value):
        slider.blockSignals(True)
        slider.setValue(round(value * scale))
        slider.blockSignals(False)

    slider.valueChanged.connect(from_slider)
    spin.valueChanged.connect(from_spin)
    spin.setProperty('compact', True)       # exp.111: a small number box beside its slider
    return slider


def compact_width(spin):
    """Just wide enough for the longest number this box can show (and its arrows)."""
    from PySide6.QtGui import QFont, QFontMetrics
    font = QFont(spin.font()); font.setPointSizeF(8.5)
    fm = QFontMetrics(font)
    texts = [spin.textFromValue(v) for v in (spin.minimum(), spin.maximum())]
    widest = max(fm.horizontalAdvance(spin.prefix() + t + spin.suffix()) for t in texts)
    return widest + 6 + 16 + 10


def label(text, kind='section'):
    w=QLabel(text)
    w.setObjectName(kind)
    return w


def caption(text):
    w=QLabel(text)
    w.setObjectName('note')
    w.setWordWrap(True)
    return w


def tidy_side_page(content):
    """Keep a side-panel page inside its column.

    Text notes and checkboxes cannot wrap a long unbroken word (a file name
    such as ChatGPT_Image_Oct_20.png) or their own label, so their natural
    width could push the whole page wider than the panel and under the
    scrollbar. Here they take the column's width instead (notes wrap, long
    words and labels are clipped), and every page keeps clear space on the
    right for the scrollbar.
    """
    layout = content.layout()
    if layout is not None:
        layout.setContentsMargins(12, 12, 20, 12)
    for note in content.findChildren(QLabel):
        if note.wordWrap() and note.objectName() == 'note':
            policy = note.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            note.setSizePolicy(policy)
            note.setMinimumWidth(0)
    for check in content.findChildren(QCheckBox):
        policy = check.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        check.setSizePolicy(policy)
        check.setMinimumWidth(0)
        if not check.toolTip():
            check.setToolTip(check.text())


def align_forms(content, label_width):
    """One label column for a whole panel page, like the Animation panel.

    Every form row has its label on the left at the same fixed width (long
    labels wrap onto two lines) and its field filling the rest, so labels and
    fields line up from the top of the page to the bottom.
    """
    for form in content.findChildren(QFormLayout):
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        for index in range(form.rowCount()):
            item = form.itemAt(index, QFormLayout.ItemRole.LabelRole)
            heading = item.widget() if item else None
            if isinstance(heading, QLabel):
                heading.setWordWrap(True)
                heading.setFixedWidth(label_width)
            field = form.itemAt(index, QFormLayout.ItemRole.FieldRole)
            control = field.widget() if field else None
            if isinstance(control, QCheckBox):
                # A checkbox row: fill the field column, but never ask for its
                # full label width (an explicit 1px minimum wins over the hint).
                policy = control.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
                control.setSizePolicy(policy)
                control.setMinimumWidth(1)
            elif control is not None and not isinstance(control, QLabel):
                # Fields fill the row like the Animation panel's (the form only
                # grows Expanding fields).
                policy = control.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
                control.setSizePolicy(policy)


def scroll_view(content):
    scroll=QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)   # exp.100: "as needed" could leave 10 px of a page under the bar
    scroll.setMinimumWidth(0)
    # Give the scroll viewport its real size hint; Ignored could collapse fields.
    scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    content.setMinimumWidth(0)
    content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
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
    element_clicked=Signal(int)         # whole video: an element's block was clicked
    element_edit=Signal(int)            # whole video: an element's block was double-clicked
    element_placed=Signal(int,float,int)   # whole video: an element dragged to a new start / track
    element_reset=Signal(int)           # whole video: back to "after the element before it", Track 1
    track_toggled=Signal(int,str)       # whole video: a track's 'mute' or 'hide' button
    element_camera_clicked=Signal(int)  # whole video: an element's own camera (zoom) clicked
    other_overlay_clicked=Signal(int,str)   # whole video: another element's text / picture (k, id)
    move_clicked=Signal(int)            # whole video: a camera move clicked (the move after element k)
    element_flag=Signal(int,str)        # whole video: one element's 'mute' or 'hide' (right-click menu)

    stage_source_edit=Signal(str,int)   # Draw/Paint source editor, exact clicked element

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
        self.scene_segments=None   # whole video: [(label, seconds, 'scene'|'join', parts)]
        self.items=None            # whole video on tracks: [(k, label, start, seconds, track, parts)]
        self.moves=None            # whole video: camera moves [(k, label, start, seconds)]
        self._ghost=None           # an element being dragged: (k, start, track)
        self.current_scene=0
        self.offset=0.             # whole video: where the edited element starts (seconds)
        self.audio=None            # {'start', 'seconds', 'name', 'envelope'} or None
        self.editable=set(self.STAGE_KEYS)   # stages whose length can be dragged
        self.overlays=[]           # overlay clips of the scene (dicts, see overlays.py)
        self.selected_overlay=None
        self._drag=None
        self._frozen=None          # time scale kept still while a clip edge is dragged
        # Whole video (exp.106): zoom in time (Ctrl + wheel, the − / + buttons) with a scroll
        # bar along the bottom, and the tracks scroll up and down when they do not fit.
        from PySide6.QtWidgets import QScrollBar
        self.zoom=1.; self.view_start=0.; self.y_off=0.; self._lanes_seen=0
        self.element_flags={}      # k -> {'hidden', 'muted'} of single elements
        self.hbar=QScrollBar(Qt.Orientation.Horizontal,self); self.hbar.hide()
        self.hbar.valueChanged.connect(self._hbar_moved)
        self.vbar=QScrollBar(Qt.Orientation.Vertical,self); self.vbar.hide()
        self.vbar.valueChanged.connect(self._vbar_moved)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip('Click to move the playhead. Drag the right edge of a clip to change its length. '
                        'Drop a sound or music file on the lower row; drag it to move it.')
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_render_state(self, runs, count, fps):
        """Preview frames ready or not: [(first frame, last frame, ready)] (see Window.render_runs)."""
        self.render_runs=list(runs); self.render_count=int(count); self.render_fps=float(fps) or 30.
        self.update()

    def update_state(self, draw, paint, hold, progress, erase=0., first='Draw'):
        self.first_label=first              # 'Move in' when the element comes in with an effect
        self.draw_seconds=max(0.,float(draw))
        self.paint_seconds=max(0.,float(paint))
        self.hold_seconds=max(0.,float(hold))
        self.erase_seconds=max(0.,float(erase))
        self.progress=max(0.,min(1.,float(progress)))
        self.update()

    HEADER=118.                         # whole video: the track headers on the left (name, mute, hide)

    def set_scenes(self, segments, current=0, items=None, moves=None, flags=None, element_flags=None):
        """Whole video: every element in a row, each with its own Draw / Paint / Hold / Out
        parts inside it (None: back to the parts of one element only).

        segments: [(label, seconds, 'scene' | 'join', parts)] with parts [(stage key, seconds)].
        The edited element (current) keeps its draggable edges, overlays and audio."""
        self.scene_segments=[tuple(s)+((),)*(4-len(s)) for s in segments] if segments else None
        self.current_scene=current
        self.offset=0.
        if self.scene_segments:
            k=0
            for label,secs,kind,_ in self.scene_segments:
                if kind=='scene':
                    if k==current: break
                    k+=1
                self.offset+=secs
        # Whole video on tracks (exp.104): each element at its own start, on its own track,
        # the camera moves on the Camera row. Without explicit items: one after another.
        if self.scene_segments and items is None:
            items,moves=[],[]; t=0.; k=0
            for label,secs,kind,parts in self.scene_segments:
                if kind=='scene':
                    items.append((k,label,t,secs,0,parts)); k+=1
                else:
                    moves.append((k-1,label,t,secs))
                t+=secs
        self.items=[tuple(i) for i in items] if (self.scene_segments and items) else None
        self.moves=[tuple(m) for m in (moves or ())] if self.items else None
        self.track_flags={int(k):dict(v) for k,v in (flags or {}).items()}
        self.element_flags={int(k):dict(v) for k,v in (element_flags or {}).items()}
        self.LEFT=self.HEADER if self.items else type(self).LEFT
        if not self.items:
            self.zoom=1.; self.view_start=0.; self.y_off=0.
        if self.lanes()!=self._lanes_seen:
            self._lanes_seen=self.lanes(); self._scroll_to_bottom=True
        if self.items:
            mine=[i for i in self.items if i[0]==current]
            if mine: self.offset=mine[0][2]
        self._fit_height()
        self.update()

    # ------------------------------------------------------------ tracks (whole video)
    CAM_H=14.

    def lanes(self):
        """Track rows shown: the tracks in use plus an empty one on top to drag onto."""
        if not self.items: return 0
        return max(i[4] for i in self.items)+2

    def _content_height(self):
        n=self.lanes()
        stack=(self.CAM_H+4+(self.CLIP_H+3)*n) if n else (self.CLIP_H+4)
        return int(22+6+stack+(self.LANE_H+3)*self.tracks()+self.AUDIO_H+10+(12 if self.items else 0))

    def _fit_height(self):
        need=self._content_height()
        if self.items:
            # Many tracks: the panel keeps a sensible height and the tracks scroll.
            self.setMinimumHeight(min(max(104,need),230)); self.setMaximumHeight(max(140,need+20))
        else:
            self.setMinimumHeight(max(104,need)); self.setMaximumHeight(max(140,need+20))
        self._update_bars()

    # ---------------------------------------------- zoom and scrolling (whole video)
    def _span(self):
        total=self._view_total()
        return total/max(1.,self.zoom) if total>0 else 0.

    def _px_per_sec(self):
        span=self._span()
        return self._width()/span if span>0 else 1.

    def _sec(self, x):
        return self.view_start+(x-self.LEFT)/self._width()*self._span()

    def set_zoom(self, zoom, anchor_x=None):
        total=self.total()
        if total<=0: return
        anchor_x=self.LEFT+self._width()/2 if anchor_x is None else anchor_x
        at=self._sec(anchor_x)
        self.zoom=max(1.,min(40.,float(zoom)))
        self.view_start=at-(anchor_x-self.LEFT)/self._width()*self._span()
        self._clamp_view(); self._update_bars(); self.update()

    def _clamp_view(self):
        self.view_start=max(0.,min(max(0.,self.total()-self._span()),self.view_start))

    def _hbar_moved(self, value):
        if self._syncing_bars: return
        room=max(0.,self.total()-self._span())
        self.view_start=room*value/1000.; self.update()

    def _vbar_moved(self, value):
        if self._syncing_bars: return
        self.y_off=float(value); self.update()

    _syncing_bars=False

    def _update_bars(self):
        if not hasattr(self,'hbar'): return
        self._syncing_bars=True
        try:
            zoomed=bool(self.items) and self.zoom>1.001
            self.hbar.setVisible(zoomed)
            if zoomed:
                room=max(1e-6,self.total()-self._span())
                self.hbar.setRange(0,1000); self.hbar.setPageStep(max(1,int(1000*self._span()/max(1e-6,room))))
                self.hbar.setValue(int(1000*self.view_start/room))
                self.hbar.setGeometry(int(self.LEFT),self.height()-11,int(self._width()),10)
            over=self._content_height()-self.height() if self.items else 0
            self.vbar.setVisible(over>0)
            if over>0:
                self.vbar.setRange(0,int(over)); self.vbar.setPageStep(max(1,self.height()))
                if getattr(self,'_scroll_to_bottom',False):
                    self.y_off=float(over); self._scroll_to_bottom=False
                self.y_off=max(0.,min(float(over),self.y_off))
                self.vbar.setValue(int(self.y_off))
                top=int(22+6+self.CAM_H+4)
                self.vbar.setGeometry(self.width()-11,top,10,self.height()-top-(12 if zoomed else 2))
            else:
                self.y_off=0.
        finally:
            self._syncing_bars=False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_bars()

    def wheelEvent(self, event):
        if not self.items:
            return super().wheelEvent(event)
        steps=event.angleDelta().y()/120. or event.angleDelta().x()/120.
        mods=event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.zoom*(1.25**steps),event.position().x())
        elif mods & Qt.KeyboardModifier.ShiftModifier or event.angleDelta().x():
            self.view_start-=steps*self._span()*.1; self._clamp_view(); self._update_bars(); self.update()
        elif self.vbar.isVisible():
            self.vbar.setValue(int(self.vbar.value()-steps*40))
        else:
            return super().wheelEvent(event)
        event.accept()

    ZOOM_BUTTONS=(('out','−'),('in','+'),('fit','Fit'))

    def _zoom_rect(self, which):
        i=[k for k,_ in self.ZOOM_BUTTONS].index(which)
        return QRectF(8.+i*26.,0.,22.,20.)

    def _track_rect(self, track):
        top=22.+6.+self.CAM_H+4.-self.y_off
        i=self.lanes()-1-int(track)
        return QRectF(self.LEFT,top+i*(self.CLIP_H+3),self._width(),self.CLIP_H)

    def _tracks_area(self):
        """Where tracks, pictures and the audio row are seen (below the Camera row)."""
        top=22.+6.+self.CAM_H+2.
        bottom=self.height()-(12. if self.hbar.isVisible() else 0.)
        return QRectF(0,top,self.width(),max(0.,bottom-top))

    def _icon_rect(self, track, which):
        lane=self._track_rect(track)
        x=self.HEADER-(64. if which=='mute' else 38.)
        return QRectF(x,lane.center().y()-12,24,24)

    def flag(self, track, which):
        return bool(self.track_flags.get(int(track),{}).get({'mute':'muted','hide':'hidden'}[which]))

    _ICON_CACHE={}

    @classmethod
    def _icon(cls, name, colour, size=16):
        key=(name,colour,size)
        if key not in cls._ICON_CACHE:
            from ui_icons import pixmap
            cls._ICON_CACHE[key]=pixmap(name,colour,size)
        return cls._ICON_CACHE[key]

    def _draw_icon(self, p, name, centre, colour, size=16):
        pm=self._icon(name,colour,size)
        p.drawPixmap(QPointF(centre.x()-size/2,centre.y()-size/2),pm)

    def _icon_button(self, p, c, rect, name, off=False, hover=False):
        """A round icon button: quiet when on, red when switched off, lit when hovered."""
        if off:
            bg=QColor(229,72,77,46)
        elif hover:
            bg=QColor(c.get('raised_hover',c.get('raised','#2A2833')))
        else:
            bg=None
        if bg is not None:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg); p.drawRoundedRect(rect,6,6)
        colour='#FF7A7E' if off else (c['text'] if hover else c['muted'])
        self._draw_icon(p,name,rect.center(),colour,15)

    def _paint_headers(self, p, c, small):
        """Left of the tracks: each track's name with its sound and hide buttons (like Filmora)."""
        used={i[4] for i in self.items or ()}
        hover=getattr(self,'_hover',None)
        name_font=QFont(self.font()); name_font.setPointSizeF(8.5); name_font.setWeight(QFont.Weight.DemiBold)
        for t in range(self.lanes()):
            lane=self._track_rect(t)
            chip=QRectF(6,lane.top(),self.HEADER-12,lane.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c['track'])); p.drawRoundedRect(chip,8,8)
            hidden=self.flag(t,'hide')
            p.setFont(name_font)
            p.setPen(QColor(c['text'] if t in used and not hidden else c['dim']))
            p.drawText(QRectF(chip.left()+10,chip.top(),chip.width()-64,chip.height()),
                       Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,f'Track {t+1}')
            if t not in used: continue
            for which,on,off in (('mute','volume','volume-off'),('hide','eye','eye-off')):
                r=self._icon_rect(t,which)
                is_off=self.flag(t,which)
                self._icon_button(p,c,r,off if is_off else on,is_off,hover==('track',t,which))
        p.setFont(small)

    def _mark_icon(self, p, centre, which):
        """This element is hidden / muted on its own: a small red badge on its clip."""
        r=QRectF(centre.x()-9,centre.y()-9,18,18)
        p.save(); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(20,20,26,190)); p.drawEllipse(r)
        self._draw_icon(p,'eye-off' if which=='hide' else 'volume-off',r.center(),'#FF7A7E',12)
        p.restore()

    def _paint_fixed_header(self, p, c, small):
        """Top left: the zoom buttons over the track names, and the Camera row's name."""
        cam=self._camera_rect()
        hover=getattr(self,'_hover',None)
        p.setFont(small)
        self._draw_icon(p,'camera',QPointF(18,cam.center().y()),c['muted'],14)
        p.setPen(QColor(c['muted']))
        p.drawText(QRectF(30,cam.top()-2,self.HEADER-34,cam.height()+4),
                   Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,'Camera')
        for which,name in (('out','zoom-out'),('in','zoom-in'),('fit','zoom-fit')):
            self._icon_button(p,c,self._zoom_rect(which),name,False,hover==('zoom',which))

    def _camera_rect(self):
        return QRectF(self.LEFT,22.+6.,self._width(),self.CAM_H)

    def _move_chip(self, start, secs):
        """The camera move's chip on the Camera row (at least 22 px wide, so it can be clicked)."""
        cam=self._camera_rect()
        x0,x1=self._x(start),self._x(start+secs)
        if x1-x0<22: mid=(x0+x1)/2; x0,x1=mid-11,mid+11
        return QRectF(x0+1,cam.top()+1,x1-x0-2,cam.height()-2)

    def _cam_rect(self, start, length):
        cam=self._camera_rect()
        x0,x1=self._x(start),self._x(start+length)
        if x1-x0<22: x1=x0+22
        return QRectF(x0+1,cam.top()+3,x1-x0-2,cam.height()-6)

    def _element_camera_at(self, pos):
        for k,start,length,until in getattr(self,'cam_marks',()) or ():
            if self._cam_rect(start,length).contains(pos): return k
        return None

    def _move_at(self, pos):
        if not self.items or pos.x()<self.LEFT: return None
        for k,label,start,secs in self.moves or ():
            if self._move_chip(start,secs).adjusted(0,-2,0,2).contains(pos):
                return k
        return None

    def _item_rect(self, item, start=None, track=None):
        k,label,s0,secs,t0,parts=item
        start=s0 if start is None else start
        lane=self._track_rect(t0 if track is None else track)
        x0,x1=self._x(start),self._x(start+secs)
        return QRectF(x0+1.5,lane.top()+3,max(1.,x1-x0-3),lane.height()-6)

    def _item_at(self, pos):
        if self.items and not self._tracks_area().contains(pos): return None
        for item in reversed(self.items or ()):
            if self._item_rect(item).adjusted(-1,-3,1,3).contains(pos):
                return item
        return None

    def _snap(self, k, start, px_per_sec):
        """Start times snap to 0, the playhead and the other elements' starts and ends."""
        secs=next(i[3] for i in self.items if i[0]==k)
        points=[0.,self.progress*self.total()]
        for i in self.items:
            if i[0]!=k: points+= [i[2],i[2]+i[3]]
        best=start
        limit=8./max(1e-6,px_per_sec)
        for p in points:
            for edge,value in ((start,p),(start+secs,p-secs)):
                if abs(edge-p)<limit and abs(edge-p)<abs(start-best)+limit:
                    best=value; limit=abs(edge-p)
        return max(0.,best)

    def element_length(self):
        """Seconds of the edited element (its own parts)."""
        return self.draw_seconds+self.paint_seconds+self.hold_seconds+self.erase_seconds

    def _blocks(self):
        """Whole video: [(element number or None for a camera move, start, seconds, segment)]."""
        if self.items:
            out=[(k,start,secs,(label,secs,'scene',parts)) for k,label,start,secs,_,parts in self.items]
            out+=[(None,start,secs,(label,secs,'join',())) for _,label,start,secs in self.moves or ()]
            return out
        out=[]; t=0.; k=0
        for seg in self.scene_segments or ():
            if seg[2]=='scene':
                out.append((k,t,seg[1],seg)); k+=1
            else:
                out.append((None,t,seg[1],seg))
            t+=seg[1]
        return out

    def _block_at(self, pos):
        if not self.scene_segments: return None
        if self.items:
            item=self._item_at(pos)
            return item[0] if item else None
        _,clips,_=self._rows()
        if not (clips.top()-2<=pos.y()<=clips.bottom()+2): return None
        for k,start,secs,_ in self._blocks():
            if k is not None and self._x(start)<=pos.x()<=self._x(start+secs):
                return k
        return None

    def set_audio(self, audio):
        self.audio=dict(audio) if audio else None
        self.update()

    CLIP_H=34.; LANE_H=22.; AUDIO_H=26.

    def tracks(self):
        every=list(self.overlays)+[o for _,o in getattr(self,'other_overlays',())]
        return (max(int(o.get('track',0)) for o in every)+1) if every else 0

    def set_overlays(self, items, selected=None, others=None):
        """others (exp.113, whole video): [(k, item)] the texts and pictures of the other
        elements, item['start'] in seconds of the whole video; shown, a click goes to them."""
        self.overlays=list(items or ())
        self.other_overlays=list(others or ())
        self.selected_overlay=selected
        self._fit_height()
        self.update()

    LEFT=12.
    RIGHT=12.

    # ------------------------------------------------------------ geometry
    def total(self):
        if self.items:
            ends=[i[2]+i[3] for i in self.items]+[m[2]+m[3] for m in self.moves or ()]
            return max(ends) if ends else 0.
        if self.scene_segments:
            return sum(s[1] for s in self.scene_segments)
        return self.element_length()

    def _stack_bottom(self):
        if self.items: return self._track_rect(0).bottom()
        return 22.+6.+self.CLIP_H

    def _rows(self):
        """(ruler height, the edited element's clip row, the audio row)."""
        ruler_h=22.; top=ruler_h+6.
        if self.items:
            mine=[i for i in self.items if i[0]==self.current_scene]
            clips=self._track_rect(mine[0][4] if mine else 0)
        else:
            clips=QRectF(self.LEFT,top,self._width(),self.CLIP_H)
        y=self._stack_bottom()+4
        n=self.tracks()
        lane_top=y
        y+=(self.LANE_H+3)*n if n else 0
        audio=QRectF(self.LEFT,y,self._width(),(self.AUDIO_H+10) if self.items else
                     max(18.,min(self.AUDIO_H+10,self.height()-y-4)))
        return ruler_h,clips,audio

    def _lane(self, track):
        return QRectF(self.LEFT,self._stack_bottom()+4+(self.LANE_H+3)*track,self._width(),self.LANE_H)

    def _overlay_rect(self, item):
        lane=self._lane(int(item.get('track',0)))
        start=self.offset+float(item.get('start',0))
        x0=self._x(start); x1=self._x(start+float(item.get('duration',3)))
        return QRectF(x0,lane.top(),max(8.,x1-x0),lane.height())

    def _other_rect(self, item):
        lane=self._lane(int(item.get('track',0)))
        x0=self._x(float(item.get('start',0))); x1=self._x(float(item.get('start',0))+float(item.get('duration',3)))
        return QRectF(x0,lane.top(),max(8.,x1-x0),lane.height())

    def _other_at(self, pos):
        if self.locked: return None
        for k,item in reversed(getattr(self,'other_overlays',())):
            if self._other_rect(item).contains(pos): return k,item
        return None

    def _overlay_at(self, pos):
        if self.locked: return None,None
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
        span=self._span()
        return self.LEFT+self._width()*((seconds-self.view_start)/span if span>0 else 0)

    def _edges(self):
        """[(stage key, x of its right edge, seconds before it)] of the visible stage clips."""
        out=[]; t=self.offset
        for key,secs in zip(self.STAGE_KEYS,(self.draw_seconds,self.paint_seconds,self.hold_seconds,self.erase_seconds)):
            if secs<=0: continue
            out.append((key,self._x(t+secs),t)); t+=secs
        return out

    def source_at(self,pos):
        """Match the actual coloured part rectangles; joins/other tracks are not sources."""
        if self.locked:return None
        _,clips,_=self._rows()
        if not clips.top()+3<=pos.y()<=clips.bottom()-3:return None
        if self.items:
            item=self._item_at(pos)
            if item is None: return None
            index,_,start,seconds,_,parts=item
            rect=self._item_rect(item)
            if not rect.top()<=pos.y()<=rect.bottom(): return None
            parts=[(key,value) for key,value in (parts or ()) if value>0] or [('draw',seconds)]
            total=sum(value for _,value in parts); x=rect.left()
            for key,value in parts:
                right=x+rect.width()*value/total
                if x<=pos.x()<right:return (key,index) if key in ('draw','paint') else None
                x=right
            return None
        if self.scene_segments:
            for index,start,seconds,segment in self._blocks():
                if index is None or seconds<=0:continue
                x=self._x(start)+1.5
                width=max(1.,self._x(start+seconds)-self._x(start)-3)
                parts=[(key,value) for key,value in (segment[3] or ()) if value>0] or [('draw',seconds)]
                total=sum(value for _,value in parts)
                for key,value in parts:
                    right=x+width*value/total
                    if x<=pos.x()<right:return (key,index) if key in ('draw','paint') else None
                    x=right
        else:
            start=0.
            for key,value in zip(self.STAGE_KEYS,(self.draw_seconds,self.paint_seconds,self.hold_seconds,self.erase_seconds)):
                if value<=0:continue
                left=self._x(start)+1.5;right=max(left+1.,self._x(start+value)-1.5)
                if left<=pos.x()<right:return (key,self.current_scene) if key in ('draw','paint') else None
                start+=value
        return None

    def source_menu(self,index,global_pos):
        from PySide6.QtWidgets import QMenu
        if self.locked:return
        menu=QMenu(self)
        menu.addAction('Edit Drawing Source…',lambda:self.stage_source_edit.emit('draw',index))
        menu.addAction('Edit Painting Source…',lambda:self.stage_source_edit.emit('paint',index))
        menu.exec(global_pos)

    def _edge_at(self, pos):
        if self.locked: return None
        _,clips,_=self._rows()
        if not (clips.top()-2<=pos.y()<=clips.bottom()+2): return None
        for key,x,_ in self._edges():
            if key in self.editable and abs(pos.x()-x)<=self.EDGE:
                return key
        return None

    def _audio_rect(self):
        if not self.audio: return None
        _,_,lane=self._rows()
        total=self.element_length()
        if total<=0: return None
        x0=self._x(self.offset+min(total,self.audio['start']))
        x1=self._x(self.offset+min(total,self.audio['start']+self.audio['seconds']))
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
        if not self.items: p.drawRoundedRect(clips,9,9)
        small=QFont(self.font());small.setPointSizeF(8.)
        p.setFont(small)
        if total<=0:
            p.setPen(QColor(c['dim']))
            p.drawText(clips,Qt.AlignmentFlag.AlignCenter,'Import artwork to begin')
            p.end()
            return
        # Ruler: major ticks with time labels, minor ticks between them.
        steps=[.05,.1,.2,.25,.5,1,2,5,10,15,30,60]
        span=self._span() or total
        major=next((t for t in steps if width*t/span>=70),steps[-1])
        minor=major/5
        import math as _m
        first=int(_m.floor(self.view_start/minor)); last=int(_m.ceil((self.view_start+span)/minor+1e-6))
        for i in range(first,last+1):
            t=i*minor
            if t<-1e-9 or t>total+1e-9: continue
            x=self._x(t)
            if x<left-1 or x>left+width+1: continue
            is_major=abs(t/major-round(t/major))<1e-6
            p.setPen(QPen(QColor(c['ruler'] if is_major else c['border_strong']),1))
            p.drawLine(QPointF(x,ruler_h-(9 if is_major else 4)),QPointF(x,ruler_h))
            if is_major and x<left+width-24:
                p.setPen(QColor(c['muted']))
                p.drawText(QRectF(x+3,1,60,14),Qt.AlignmentFlag.AlignLeft,
                           f'{t:.0f}s' if major>=1 else f'{t:.1f}s' if major>=.1 else f'{t:.2f}s')
        p.setPen(QPen(QColor(c['border']),1))
        p.drawLine(QPointF(left,ruler_h+.5),QPointF(left+width,ruler_h+.5))
        # Render bar under the ruler: red = preview frames not ready yet, green = ready.
        runs=getattr(self,'render_runs',None)
        if runs and getattr(self,'render_count',0):
            fps=getattr(self,'render_fps',30.)
            p.setPen(Qt.PenStyle.NoPen)
            for first,last,ready in runs:
                x0=self._x(first/fps); x1=self._x((last+1)/fps)
                x0=max(left,min(left+width,x0)); x1=max(left,min(left+width,x1))
                if x1<=x0: continue
                p.setBrush(QColor('#3BBF7A') if ready else QColor('#E5484D'))
                p.drawRect(QRectF(x0,ruler_h-3,x1-x0,3))
        # Clips for each phase, like clips on an editor track.
        stages=[(getattr(self,'first_label','Draw'),self.draw_seconds,c['draw']),
                ('Paint',self.paint_seconds,c['paint']),
                ('Hold',self.hold_seconds,c['hold']),
                ('Out',self.erase_seconds,c.get('erase','#D9667E'))]
        if self.items:
            self._paint_tracks(p,c,small)
            self._paint_fixed_header(p,c,small)
            stages=[]
        elif self.scene_segments:
            self._paint_whole(p,c,clips,small)
            stages=[]
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
        if self.items:
            p.save(); p.setClipRect(self._tracks_area())
        others=getattr(self,'other_overlays',())
        if others:
            # The other elements' texts and pictures (exp.113): fainter; a click goes to them.
            for track in range(self.tracks()):
                row=self._lane(track)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['track'])); p.drawRoundedRect(row,7,7)
            p.save(); p.setClipRect(QRectF(left,0,width,self.height()))
            for k,item in others:
                r=self._other_rect(item).adjusted(1,2,-1,-2)
                fill=QColor(c.get('erase','#E06A86') if item.get('kind')=='text' else c.get('accent_b','#4C42DE'))
                fill.setAlpha(90)
                edge=QColor(fill); edge.setAlpha(200)
                p.setPen(QPen(edge,1,Qt.PenStyle.DashLine)); p.setBrush(fill)
                p.drawRoundedRect(r,6,6)
                if r.width()>30:
                    p.setPen(QColor(c['text'])); p.setFont(small)
                    icon='T ' if item.get('kind')=='text' else '▣ '
                    p.drawText(r.adjusted(7,0,-6,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,
                               f'{icon}{str(item.get("name") or "")[:30]}  ({k+1})')
            p.restore()
        if self.overlays:
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
        if True:
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
                    px_per_sec=width/max(1e-6,total)
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
        if self.items:
            p.restore()
        # Playhead: a line through the track with a marker on the ruler.
        play_x=self._x(self.progress*total)
        if not left-1<=play_x<=left+width+1:
            p.end(); return
        accent=QColor(c['accent'])
        p.setPen(QPen(accent,2))
        p.drawLine(QPointF(play_x,ruler_h-2),QPointF(play_x,lane.bottom()))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(accent)
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(play_x-6,ruler_h-13),QPointF(play_x+6,ruler_h-13),
                                 QPointF(play_x+6,ruler_h-6),QPointF(play_x,ruler_h),
                                 QPointF(play_x-6,ruler_h-6)]))
        p.end()

    STAGE_NAMES={'draw':'Draw','paint':'Paint','hold':'Hold','erase':'Out','move':'Move in'}

    def _paint_whole(self, p, c, clips, small):
        """Whole video: one block per element with its parts inside, camera moves between."""
        colours={'draw':c['draw'],'paint':c['paint'],'hold':c['hold'],'erase':c.get('erase','#D9667E'),
                 'move':c['draw']}
        p.save(); p.setClipRect(QRectF(self.LEFT,0,self._width(),self.height()))
        bold=QFont(self.font()); bold.setPointSizeF(8.5); bold.setBold(True)
        for k,start,secs,seg in self._blocks():
            if secs<=0: continue
            x0,x1=self._x(start),self._x(start+secs)
            rect=QRectF(x0+1.5,clips.top()+3,max(1.,x1-x0-3),clips.height()-6)
            if k is None:                          # the camera move to the next element
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['border_strong']))
                p.drawRoundedRect(rect.adjusted(0,8,0,-8),5,5)
                if rect.width()>=20:
                    p.setPen(QColor(c['muted'])); p.setFont(small)
                    p.drawText(rect,Qt.AlignmentFlag.AlignCenter,'➜' if rect.width()<70 else '➜ '+seg[0])
                continue
            current=k==self.current_scene
            parts=[(key,v) for key,v in (seg[3] or ()) if v>0] or [('draw',secs)]
            whole=sum(v for _,v in parts) or 1.
            path=QPainterPath(); path.addRoundedRect(rect,7,7)
            p.save(); p.setClipPath(path,Qt.ClipOperation.IntersectClip)
            x=rect.left()
            for key,v in parts:
                w=rect.width()*v/whole
                fill=QColor(colours.get(key,c['draw'])); fill.setAlpha(225 if current else 120)
                p.fillRect(QRectF(x,rect.top(),w,rect.height()),fill)
                if x>rect.left():
                    p.setPen(QPen(QColor(0,0,0,70),1)); p.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
                x+=w
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor('white') if current else QColor(c['border_strong']),2 if current else 1))
            p.drawRoundedRect(rect,7,7)
            if current:
                # Grips on the edges that can be dragged.
                p.setPen(QPen(QColor(255,255,255,170),1.4))
                for key,ex,_ in self._edges():
                    if key in self.editable and ex-x0>=14:
                        gx=ex-5
                        p.drawLine(QPointF(gx,rect.center().y()-6),QPointF(gx,rect.center().y()+6))
                        p.drawLine(QPointF(gx-3,rect.center().y()-6),QPointF(gx-3,rect.center().y()+6))
            if rect.width()>=30:
                p.setFont(bold); p.setPen(QColor(c['clip_text'] if current else c['text']))
                text=seg[0] if rect.width()<110 else f'{seg[0]}  {secs:.1f}s'
                text=p.fontMetrics().elidedText(text,Qt.TextElideMode.ElideRight,int(rect.width()-16))
                p.drawText(rect.adjusted(8,0,-8,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,text)
        p.restore(); p.setFont(small)

    def _paint_tracks(self, p, c, small):
        """Whole video on tracks: the Camera row with its moves, then one row per track
        (the top row is empty: drag an element there to put it on a new track)."""
        colours={'draw':c['draw'],'paint':c['paint'],'hold':c['hold'],'erase':c.get('erase','#D9667E'),
                 'move':c['draw']}
        cam=self._camera_rect()
        area=self._tracks_area()
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['track'])); p.drawRoundedRect(cam,5,5)
        p.save(); p.setClipRect(area)
        for t in range(self.lanes()):
            p.drawRoundedRect(self._track_rect(t),9,9)
        p.restore()
        p.setFont(small)
        p.save(); p.setClipRect(QRectF(self.LEFT,0,self._width(),self.height()))
        for k,start,length,until in getattr(self,'cam_marks',()) or ():
            # exp.115: an element's own camera (zoom): an outlined bar; the part after the
            # camera move that took over from it is faded.
            r=self._cam_rect(start,length)
            lit=getattr(self,'_hover',None)==('cam',k)
            edge=QColor(c['accent']); fill=QColor(c['accent']); fill.setAlpha(110 if lit else 60)
            p.setPen(QPen(edge,1.2)); p.setBrush(fill); p.drawRoundedRect(r,4,4)
            if until is not None and until<start+length:
                gone=QRectF(self._x(until),r.top(),max(0.,r.right()-self._x(until)),r.height())
                faded=QColor(c['track']); faded.setAlpha(170)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(faded); p.drawRect(gone.intersected(r))
            if r.width()>=22:
                self._draw_icon(p,'zoom-in',QPointF(r.left()+11,r.center().y()),c['text'],11)
        for k,label,start,secs in self.moves or ():
            # A camera move: a camera drawn as a picture (not a word, so no font can cut it).
            # exp.111: click it to change how and how long the camera moves.
            r=self._move_chip(start,secs)
            lit=getattr(self,'_hover',None)==('move',k)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['accent'] if lit else c['border_strong']))
            p.drawRoundedRect(r,4,4)
            self._draw_icon(p,'camera',r.center(),'#FFFFFF' if lit else c['text'],12)
        p.restore()
        p.save(); p.setClipRect(QRectF(0,area.top(),self.LEFT,area.height()))
        self._paint_headers(p,c,small)
        p.restore()
        p.save(); p.setClipRect(QRectF(self.LEFT,area.top(),self._width(),area.height()))
        bold=QFont(self.font()); bold.setPointSizeF(8.5); bold.setBold(True)
        for item in self.items:
            k,label,start,secs,track,parts=item
            if secs<=0: continue
            rect=self._item_rect(item)
            current=k==self.current_scene
            dragged=self._ghost is not None and self._ghost[0]==k
            parts=[(key,v) for key,v in (parts or ()) if v>0] or [('draw',secs)]
            whole=sum(v for _,v in parts) or 1.
            path=QPainterPath(); path.addRoundedRect(rect,7,7)
            p.save(); p.setClipPath(path,Qt.ClipOperation.IntersectClip)
            hidden=self.flag(track,'hide') or self.element_flags.get(k,{}).get('hidden')
            if hidden: p.setOpacity(.35)                      # hidden: not in the video
            x=rect.left()
            for key,v in parts:
                w=rect.width()*v/whole
                fill=QColor(colours.get(key,c['draw'])); fill.setAlpha(80 if dragged else 225 if current else 120)
                p.fillRect(QRectF(x,rect.top(),w,rect.height()),fill)
                if x>rect.left():
                    p.setPen(QPen(QColor(0,0,0,70),1)); p.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
                x+=w
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor('white') if current else QColor(c['border_strong']),2 if current else 1))
            p.drawRoundedRect(rect,7,7)
            if current:
                p.setPen(QPen(QColor(255,255,255,170),1.4))
                for key,ex,_ in self._edges():
                    if key in self.editable and ex-rect.left()>=14:
                        gx=ex-5
                        p.drawLine(QPointF(gx,rect.center().y()-6),QPointF(gx,rect.center().y()+6))
                        p.drawLine(QPointF(gx-3,rect.center().y()-6),QPointF(gx-3,rect.center().y()+6))
            marks=[w for w,key in (('hide','hidden'),('mute','muted')) if self.element_flags.get(k,{}).get(key)]
            for n,which in enumerate(marks):           # this element hidden / muted on its own
                self._mark_icon(p,QPointF(rect.right()-12-n*20,rect.center().y()),which)
            if rect.width()>=30:
                p.setFont(bold); p.setPen(QColor(c['clip_text'] if current else c['text']))
                text=label if rect.width()<110 else f'{label}  {secs:.1f}s'
                text=p.fontMetrics().elidedText(text,Qt.TextElideMode.ElideRight,int(rect.width()-16))
                p.drawText(rect.adjusted(8,0,-8,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,text)
                p.setFont(small)
        if self._ghost is not None:
            k,start,track=self._ghost
            item=next((i for i in self.items if i[0]==k),None)
            if item is not None:
                r=self._item_rect(item,start,track)
                p.setBrush(QColor(255,255,255,40)); p.setPen(QPen(QColor('white'),1.5,Qt.PenStyle.DashLine))
                p.drawRoundedRect(r,7,7)
                p.setPen(QColor('white'))
                p.drawText(r.adjusted(8,0,-8,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,
                           f'{item[1]}  {start:.1f}s, Track {track+1}')
        p.restore(); p.setFont(small)

    def set_locked(self, locked):
        self.locked=bool(locked)
        self.setCursor(Qt.CursorShape.BusyCursor if self.locked else Qt.CursorShape.PointingHandCursor)
        self.update()

    # ------------------------------------------------------------ mouse
    def _seek(self, x):
        total=self.total()
        fraction=max(0.,min(1.,self._sec(x)/total)) if total>0 else 0.
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
                event.accept();return
            source=self.source_at(pos)
            item=self._item_at(pos) if self.items else None
            if item is not None:
                from PySide6.QtWidgets import QMenu
                k=item[0]
                menu=QMenu(self)
                menu.addAction('Edit Drawing Source…',lambda:self.stage_source_edit.emit('draw',k))
                menu.addAction('Edit Painting Source…',lambda:self.stage_source_edit.emit('paint',k))
                menu.addSeparator()
                flags=self.element_flags.get(k,{})
                menu.addAction('Show this element' if flags.get('hidden') else 'Hide this element',
                               lambda:self.element_flag.emit(k,'hide'))
                menu.addAction('Sounds on for this element' if flags.get('muted') else 'Mute this element',
                               lambda:self.element_flag.emit(k,'mute'))
                menu.addSeparator()
                menu.addAction('Start right after the element before it (Track 1)',lambda:self.element_reset.emit(k))
                menu.exec(event.globalPosition().toPoint())
            elif source is not None:self.source_menu(source[1],event.globalPosition().toPoint())
            event.accept(); return
        if event.button()!=Qt.MouseButton.LeftButton or self.total()<=0:
            return super().mousePressEvent(event)
        other=self._other_at(pos) if not self._overlay_at(pos)[0] else None
        if other is not None:
            self.other_overlay_clicked.emit(other[0],str(other[1].get('id')))
            event.accept(); return
        item,part=self._overlay_at(pos)
        if item is not None:
            self.selected_overlay=item.get('id'); self.overlay_selected.emit(item.get('id'))
            self._frozen=self.total()
            self._drag=('overlay',item,part,pos.x(),pos.y(),float(item.get('start',0)),
                        float(item.get('duration',3)),int(item.get('track',0)),self._px_per_sec())
            self.update(); event.accept(); return
        key=self._edge_at(pos)
        if key:
            start=next(t for k,_,t in self._edges() if k==key)
            self._frozen=self.total()
            self._drag=('edge',key,start,self._px_per_sec())
            event.accept(); return
        rect=self._audio_rect()
        if rect is not None and rect.contains(pos):
            self._drag=('audio',pos.x(),self.audio['start'],self._px_per_sec())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept(); return
        if self.items and pos.x()<self.LEFT and pos.y()<22:
            for which,_ in self.ZOOM_BUTTONS:
                if self._zoom_rect(which).adjusted(-2,-2,2,2).contains(pos):
                    if which=='fit': self.zoom=1.; self.view_start=0.; self._update_bars(); self.update()
                    else: self.set_zoom(self.zoom*(1.5 if which=='in' else 1/1.5))
                    event.accept(); return
        move=self._move_at(pos) if event.button()==Qt.MouseButton.LeftButton else None
        if move is not None:
            self.move_clicked.emit(move)
            event.accept(); return
        own=self._element_camera_at(pos) if event.button()==Qt.MouseButton.LeftButton else None
        if own is not None:
            self.element_camera_clicked.emit(own)
            event.accept(); return
        if self.items and pos.x()<self.LEFT and not self._tracks_area().contains(pos):
            event.accept(); return
        if self.items and pos.x()<self.LEFT:
            used={i[4] for i in self.items}
            for t in range(self.lanes()):
                if t not in used: continue
                for which in ('mute','hide'):
                    if self._icon_rect(t,which).adjusted(-3,-3,3,3).contains(pos):
                        self.track_toggled.emit(t,which)
                        event.accept(); return
            event.accept(); return
        item=self._item_at(pos) if self.items else None
        if item is not None:
            # Whole video on tracks: drag an element along its track or to another track
            # (a click without moving works on it, as before).
            self._frozen=self.total()
            self._drag=('block',item[0],pos.x(),pos.y(),item[2],item[4],self._px_per_sec(),False)
            event.accept(); return
        k=self._block_at(pos)
        self._drag=('seek',)
        self._seek(pos.x())
        if k is not None and k!=self.current_scene:
            self.element_clicked.emit(k)
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
                if self.scene_segments: total=max(.2,self.element_length())
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
            if kind=='block':
                _,k,x0,y0,start0,track0,px_per_sec,moved=self._drag
                if not moved and abs(pos.x()-x0)<5 and abs(pos.y()-y0)<5:
                    event.accept(); return
                start=self._snap(k,start0+(pos.x()-x0)/px_per_sec,px_per_sec)
                track=track0
                for t in range(self.lanes()):
                    lane=self._track_rect(t)
                    if lane.top()-2<=pos.y()<=lane.bottom()+2: track=t
                self._drag=self._drag[:7]+(True,)
                self._ghost=(k,round(start,2),track)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update(); event.accept(); return
            if kind=='edge':
                _,key,start,px_per_sec=self._drag
                seconds=max(.1,self._sec(pos.x())-start)
                self.stage_dragged.emit(key,round(seconds,2))
                self.setToolTip(f'{key.title()}: {seconds:.1f} s')
            elif kind=='audio':
                _,x0,start0,px_per_sec=self._drag
                self.audio_moved.emit(round(max(0.,start0+(pos.x()-x0)/px_per_sec),2))
            else:
                self._seek(pos.x())
            event.accept(); return
        # Hover over the track buttons and the zoom buttons: light them, say what they do.
        if self.items and pos.x()<self.LEFT:
            hover=None; tip=''
            for which,name in self.ZOOM_BUTTONS:
                if self._zoom_rect(which).contains(pos):
                    hover=('zoom',which); tip={'out':'Zoom out (Ctrl + wheel)','in':'Zoom in (Ctrl + wheel)',
                                               'fit':'Fit the whole video'}[which]
            if hover is None and self._tracks_area().contains(pos):
                used={i[4] for i in self.items}
                for t in range(self.lanes()):
                    if t not in used: continue
                    for which in ('mute','hide'):
                        if self._icon_rect(t,which).contains(pos):
                            hover=('track',t,which)
                            off=self.flag(t,which)
                            tip=(f'Track {t+1}: sounds off. Click to turn them on.' if off else
                                 f'Track {t+1}: mute its pencil and brush sounds') if which=='mute' else \
                                (f'Track {t+1} is hidden. Click to show it.' if off else
                                 f'Track {t+1}: hide it from the video')
            if hover!=getattr(self,'_hover',None):
                self._hover=hover; self.update()
            self.setToolTip(tip)
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor)
            return super().mouseMoveEvent(event)
        own=self._element_camera_at(pos) if self._move_at(pos) is None else None
        if own is not None:
            if getattr(self,'_hover',None)!=('cam',own):
                self._hover=('cam',own); self.update()
            self.setToolTip(f'Element {own+1}: its own camera (zoom). Click to change it.')
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return super().mouseMoveEvent(event)
        move=self._move_at(pos)
        if move is not None:
            if getattr(self,'_hover',None)!=('move',move):
                self._hover=('move',move); self.update()
            label,start,secs=next((m[1],m[2],m[3]) for m in self.moves if m[0]==move)
            self.setToolTip(f'Camera: {label}, {secs:.1f} s. Click to change it.')
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return super().mouseMoveEvent(event)
        if getattr(self,'_hover',None) is not None:
            self._hover=None; self.update(); self.setToolTip('')
        # Hover: show what can be grabbed.
        item,part=self._overlay_at(pos)
        if item is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor if part in ('start','end') else Qt.CursorShape.OpenHandCursor)
            return super().mouseMoveEvent(event)
        if self._edge_at(pos):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._block_at(pos) is not None:
            k=self._block_at(pos)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(f'Element {k+1}: click to work on it, double-click Draw/Paint to edit its source' if k!=self.current_scene
                            else 'The element you are editing: drag a white edge to change a part\'s length, '
                                 'double-click for its settings.')
        else:
            rect=self._audio_rect()
            self.setCursor(Qt.CursorShape.OpenHandCursor if rect is not None and rect.contains(pos)
                           else Qt.CursorShape.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self,event):
        if self.locked or event.button()!=Qt.MouseButton.LeftButton:
            event.accept();return
        self._drag=None;self._frozen=None
        item,_=self._overlay_at(event.position())
        if item is not None:
            self.overlay_edit.emit(item.get('id'));event.accept();return
        source=self.source_at(event.position())
        if source is not None:
            self.stage_source_edit.emit(*source);event.accept();return
        k=self._block_at(event.position())
        if k is not None:
            self.element_edit.emit(k);event.accept();return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self,event):
        if self._drag and self._drag[0]=='block':
            _,k,x0,y0,start0,track0,px_per_sec,moved=self._drag
            self._frozen=None
            ghost=self._ghost; self._ghost=None
            self._drag=None
            if moved and ghost is not None:
                if (abs(ghost[1]-start0)>1e-3 or ghost[2]!=track0):
                    self.element_placed.emit(k,float(ghost[1]),int(ghost[2]))
            else:
                self._seek(event.position().x())
                if k!=self.current_scene: self.element_clicked.emit(k)
            self.update(); self.setCursor(Qt.CursorShape.PointingHandCursor)
            event.accept(); return
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
        if self._audio_url(event) or self._audio_url(event,self.PICTURE_TYPES):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path=self._audio_url(event)
        if path:
            self.audio_dropped.emit(path)
            event.acceptProposedAction(); return
        picture=self._audio_url(event,self.PICTURE_TYPES)
        if picture:
            x=event.position().x()
            seconds=self._sec(x)-self.offset
            seconds=max(0.,min(self.element_length(),seconds))
            self.overlay_dropped.emit(picture,round(seconds,2))
            event.acceptProposedAction()

    def keyPressEvent(self,event):
        if self.locked:
            event.accept(); return
        mods=event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier and mods & Qt.KeyboardModifier.ShiftModifier and event.key() in (Qt.Key.Key_D,Qt.Key.Key_P):
            self.stage_source_edit.emit('draw' if event.key()==Qt.Key.Key_D else 'paint',self.current_scene)
            event.accept();return
        if event.key()==Qt.Key.Key_Menu or (event.key()==Qt.Key.Key_F10 and mods & Qt.KeyboardModifier.ShiftModifier):
            self.source_menu(self.current_scene,self.mapToGlobal(self.rect().center()))
            event.accept();return
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
        if not button.toolTip(): button.setToolTip(button.text())
    for box in content.findChildren(QComboBox):
        box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        box.setMinimumContentsLength(6)
        # Never ignore the combobox size hint: Qt can allocate a zero-width
        # field in QFormLayout while leaving the label/row fully visible.
        box.setMinimumWidth(96)
        policy=box.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        box.setSizePolicy(policy)
        if not box.toolTip(): box.setToolTip(box.currentText())
    for box in content.findChildren(QAbstractSpinBox):
        box.setMinimumWidth(84)
        policy=box.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        box.setSizePolicy(policy)
    for check in content.findChildren(QCheckBox):
        policy=check.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        check.setSizePolicy(policy)
        check.setMinimumWidth(0)
        if not check.toolTip(): check.setToolTip(check.text())
    for note in content.findChildren(QLabel):
        if note.text() and len(note.text()) > 24:
            note.setWordWrap(True)
            if not note.toolTip(): note.setToolTip(note.text())
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


RAIL_ICON = '#A9A6B8'          # rail and header icons: muted, accent when open
RAIL_ACTIVE = '#B7A6FF'


def _header_icon(name):
    from ui_icons import pixmap
    mark = QLabel(); mark.setObjectName('panelIcon')
    mark.setPixmap(pixmap(name, RAIL_ICON, 20)); mark.setFixedSize(22, 22)
    return mark


def _close_button(tip):
    from PySide6.QtWidgets import QToolButton
    from PySide6.QtCore import QSize
    from ui_icons import icon
    button = QToolButton(); button.setObjectName('panelClose')
    button.setIcon(icon('close', RAIL_ICON)); button.setIconSize(QSize(16, 16))
    button.setToolTip(tip); button.setAccessibleName(tip)
    button.setAutoRaise(True)
    return button


def build_rails(w, tabs, inspector):
    """Icon rails beside the two side panels (outside the splitter).

    Panels start closed, so the canvas is big. Left rail: Handwriting. Right
    rail: Source, Animation, Hand, Sound, Export. Clicking an icon slides its
    panel open toward the canvas (pushing the canvas over); clicking it again,
    or the panel's close button, slides it shut. Each side remembers its state.
    """
    from PySide6.QtWidgets import QToolButton
    from PySide6.QtCore import QSize
    from ui_icons import icon
    layout = w.sidebar_layout

    def rail_frame():
        frame = QFrame(); frame.setObjectName('iconRail')
        # Room around the buttons, so the purple square of the open panel does not
        # touch the window edge (exp.100).
        frame.setFixedWidth(54)
        column = QVBoxLayout(frame); column.setContentsMargins(5, 10, 5, 10); column.setSpacing(6)
        return frame, column

    def rail_button(name, text):
        button = QToolButton(); button.setObjectName('railButton')
        button.setText(text)
        button.setIcon(icon(name, RAIL_ICON, '#FFFFFF'))      # the open panel: white on purple
        button.setIconSize(QSize(18, 18))
        button.setCheckable(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setAccessibleName(text)
        return button

    left, left_l = rail_frame()
    w.left_rail_buttons = {}
    for key, text in LEFT_RAIL:
        button = rail_button(key, text)
        button.setToolTip(text + ' panel')
        button.clicked.connect(lambda checked=False, k=key: w.show_left_panel(k, toggle=True))
        left_l.addWidget(button)
        w.left_rail_buttons[key] = button
    w.rail_text = w.left_rail_buttons['text']
    w.rail_text.setToolTip('Text: handwriting and lettering')
    left_l.addStretch(1)

    right, right_l = rail_frame()
    w.rail_buttons = {}
    for key, text in RAIL:
        button = rail_button(key, text)
        button.setToolTip(text + ' panel')
        button.clicked.connect(lambda checked=False, k=key: w.show_right_panel(k, toggle=True))
        right_l.addWidget(button)
        w.rail_buttons[key] = button
    right_l.addStretch(1)

    w.workspace_row_layout.insertWidget(0, left)
    w.workspace_row_layout.addWidget(right)
    w.left_rail, w.right_rail = left, right

    # Panel headers: an icon before the title, a close button at the end.
    hw_header = w.handwriting_panel.title_label.parentWidget().layout()
    w.left_panel_icon = _header_icon('text')
    hw_header.insertWidget(0, w.left_panel_icon)
    w.handwriting_close = _close_button('Close panel')
    w.handwriting_close.clicked.connect(lambda checked=False: layout.set_expanded('source', False))
    hw_header.addWidget(w.handwriting_close)
    right_header = inspector.title_label.parentWidget().layout()
    w.right_panel_icon = _header_icon('source')
    right_header.insertWidget(0, w.right_panel_icon)
    w.right_panel_close = _close_button('Close panel')
    w.right_panel_close.clicked.connect(lambda checked=False: layout.set_expanded('inspector', False))
    right_header.addWidget(w.right_panel_close)

    def show_right_panel(key, toggle=False):
        index = TABS[key]
        if toggle and layout.expanded['inspector'] and tabs.currentIndex() == index:
            layout.set_expanded('inspector', False)
        else:
            tabs.setCurrentIndex(index)
            layout.set_expanded('inspector', True)
        sync()

    def show_left_panel(key, toggle=False):
        index = LEFT[key]
        if toggle and layout.expanded['source'] and w.left_tabs.currentIndex() == index:
            layout.set_expanded('source', False)
        else:
            w.left_tabs.setCurrentIndex(index)
            layout.set_expanded('source', True)
        sync()

    def show_handwriting_panel():
        show_left_panel('text')
        w.text.setFocus()

    def sync(*_):
        from ui_icons import pixmap
        key = next((k for k, i in TABS.items() if i == tabs.currentIndex()), 'source')
        inspector.title_label.setText(tabs.tabText(tabs.currentIndex()))
        w.right_panel_icon.setPixmap(pixmap(key, RAIL_ICON, 20))
        left_key = next((k for k, i in LEFT.items() if i == w.left_tabs.currentIndex()), 'text')
        w.handwriting_panel.title_label.setText(w.left_tabs.tabText(w.left_tabs.currentIndex()))
        w.left_panel_icon.setPixmap(pixmap(left_key, RAIL_ICON, 20))
        for name, button in w.left_rail_buttons.items():
            button.blockSignals(True)
            button.setChecked(bool(layout.expanded['source']) and w.left_tabs.currentIndex() == LEFT[name])
            button.blockSignals(False)
        for name, button in w.rail_buttons.items():
            button.blockSignals(True)
            button.setChecked(bool(layout.expanded['inspector']) and tabs.currentIndex() == TABS[name])
            button.blockSignals(False)

    w.show_right_panel = show_right_panel
    w.show_left_panel = show_left_panel
    w.show_handwriting_panel = show_handwriting_panel
    w.sync_rails = sync
    tabs.currentChanged.connect(sync)
    w.left_tabs.currentChanged.connect(sync)
    layout.listeners.append(sync)
    sync()
    build_fullscreen(w)


def build_fullscreen(w):
    """Canvas fullscreen: only the Program monitor (canvas + transport) shows.

    The button in the Program header or F11 toggles it; Esc leaves it. Panel
    open/closed states are restored afterwards and are not saved as changed.
    """
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtCore import QSize
    from ui_icons import icon
    w.fullscreen_button.setIcon(icon('fullscreen', RAIL_ICON))
    w.fullscreen_button.setIconSize(QSize(18, 18))
    w.fullscreen_button.setToolTip('Fullscreen canvas (F11)')
    w.canvas_fullscreen = False
    saved = {}

    def chrome():
        return [w.menuBar(), w.top_bar, w.left_rail, w.right_rail, w.timeline_panel,
                w.handwriting_panel, w.workspace_splitter.widget(2)]

    def enter():
        if w.canvas_fullscreen:
            return
        saved.clear()
        saved['visible'] = {id(x): x.isVisible() for x in chrome()}
        saved['banner'] = w.update_banner.isVisible()
        saved['window'] = w.windowState()
        for part in chrome():
            part.hide()
        w.update_banner.hide()
        w.canvas_fullscreen = True
        w.fullscreen_button.setIcon(icon('exit-fullscreen', RAIL_ICON))
        w.fullscreen_button.setToolTip('Leave fullscreen (Esc or F11)')
        w.exit_fullscreen_key.setEnabled(True)
        w.showFullScreen()

    def leave():
        if not w.canvas_fullscreen:
            return
        w.canvas_fullscreen = False
        w.exit_fullscreen_key.setEnabled(False)
        w.setWindowState(saved.get('window', Qt.WindowState.WindowNoState))
        for part in chrome():
            part.setVisible(saved['visible'].get(id(part), True))
        w.update_banner.setVisible(saved.get('banner', False))
        w.sidebar_layout._resize()
        w.fullscreen_button.setIcon(icon('fullscreen', RAIL_ICON))
        w.fullscreen_button.setToolTip('Fullscreen canvas (F11)')

    def toggle():
        leave() if w.canvas_fullscreen else enter()

    w.enter_canvas_fullscreen, w.leave_canvas_fullscreen = enter, leave
    w.toggle_canvas_fullscreen = toggle
    w.fullscreen_button.clicked.connect(lambda checked=False: toggle())
    w.fullscreen_key = QShortcut(QKeySequence('F11'), w)
    w.fullscreen_key.activated.connect(toggle)
    w.exit_fullscreen_key = QShortcut(QKeySequence('Esc'), w)
    w.exit_fullscreen_key.activated.connect(leave)
    w.exit_fullscreen_key.setEnabled(False)


class LineList(QListWidget):
    """Line list that reports when lines were dragged to a new place."""
    dropped=Signal()
    def dropEvent(self,event):
        super().dropEvent(event)
        self.dropped.emit()

    def keyPressEvent(self,event):
        # Escape dismisses selection without deleting or changing any line.
        if event.key()==Qt.Key.Key_Escape and self.selectedItems():
            self.clearSelection()
            event.accept()
            return
        super().keyPressEvent(event)


# Inspector tabs, in order.
TABS = {'animation': 0, 'hand': 1, 'export': 2, 'source': 3, 'ai': 4}
# Left panel pages (Text = handwriting).
LEFT = {'text': 0, 'sound': 1, 'music': 2, 'camera': 3}
LEFT_RAIL = (('text', 'Text'), ('sound', 'Sound'), ('music', 'Music'), ('camera', 'Camera'))
# The right rail shows Source first; the tab widget keeps it last so the
# long-standing indexes of the other panels never change.
RAIL = (('source', 'Image'), ('ai', 'AI'), ('animation', 'Animation'), ('hand', 'Hand'),
        ('export', 'Export'))


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
    w.top_bar=bar
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
    # Not shown in the top bar: every project action is in the File menu, and
    # resolution / frame rate are set in Export. The widgets stay (hidden) so
    # existing code that keeps them up to date continues to work.
    w.project_menu.hide()
    w.output_summary.hide()
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
    # Pre-render, next to Library at the top: one click makes the preview play smoothly.
    w.prerender_button=QPushButton('Pre-render')
    w.prerender_button.setToolTip('Make every frame of the preview ready so it plays smoothly. Only the '
                                  'parts you change are made again. Click again to stop.')
    w.prerender_button.clicked.connect(lambda checked=False: w.prerender_whole())
    bar_l.addWidget(w.prerender_button)
    w.create_image_button=QPushButton('✦  Create image')
    w.create_image_button.setToolTip('AI line art for your image, new images from text, or edits '
                                     '(local models; runs on your graphics card).')
    w.create_image_button.clicked.connect(lambda checked=False: w.open_create_image())
    bar_l.addWidget(w.create_image_button)
    w.create_image_button.hide()          # replaced by the AI panel (right rail)
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
    # Icon rails sit outside the splitter, so they stay visible when either
    # side panel is collapsed (they are how a closed panel is reopened).
    w.workspace_row=QWidget()
    w.workspace_row_layout=QHBoxLayout(w.workspace_row)
    w.workspace_row_layout.setContentsMargins(3,0,3,0)    # the rails keep off the window edges
    w.workspace_row_layout.setSpacing(2)
    w.workspace_row_layout.addWidget(split,1)
    w.vertical_splitter.addWidget(w.workspace_row)
    outer.addWidget(w.vertical_splitter,1)

    # Handwriting (left): text and lettering only. Imports live in Source (right).
    asset_panel,asset_outer,_=panel('assetPanel','Text')
    w.handwriting_panel=asset_panel
    asset_panel.setMinimumWidth(225)
    asset_panel.setMaximumWidth(460)
    asset=QWidget();asset.setObjectName('panelBody')
    asset_l=QVBoxLayout(asset);asset_l.setContentsMargins(12,10,12,12)
    asset_l.setSpacing(9)

    # Source (right rail): every SVG / PNG / image import, the selected
    # element's card, its transform and appearance, and image-to-drawing.
    source_page=QWidget();source_page.setObjectName('panelBody')
    w.source_page=source_page
    src_l=QVBoxLayout(source_page);src_l.setContentsMargins(9,12,9,8)
    src_l.setSpacing(9)
    src_l.addWidget(caption('Import an SVG drawing or a picture (PNG, JPG, WebP, BMP).'))
    # The mode combo is internal state now: the two buttons below choose the
    # kind of import, and the selected element decides which settings show.
    w.source_type=QComboBox(); w.source_type.addItems(['SVG source','Image source'])
    w.source_type.setVisible(False)
    src_l.addWidget(w.source_type)
    w.import_button=QPushButton('Import SVG…')
    w.import_button.setObjectName('primary')
    w.import_button.setToolTip('Import an SVG drawing. You can add it to the project or replace the selected element.')
    w.import_button.clicked.connect(lambda checked=False: w.open_svg_source())
    src_l.addWidget(w.import_button)
    w.import_image_button=QPushButton('Import image…')
    w.import_image_button.setToolTip('Import a PNG, JPG, WebP or BMP picture; StrokeScribe turns it into line art and paints its colours.')
    w.import_image_button.clicked.connect(lambda checked=False: w.open_image_source())
    src_l.addWidget(w.import_image_button)
    # The selected element, as it really is: an imported file (thumbnail and
    # its real name) or native handwriting (no thumbnail, no file name).
    w.source_card=QFrame();w.source_card.setObjectName('sourcePreview')
    w.source_card.setMinimumWidth(0)
    w.source_card.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
    card_l=QVBoxLayout(w.source_card);card_l.setContentsMargins(12,14,12,14);card_l.setSpacing(6)
    w.source_card_thumb=QLabel();w.source_card_thumb.setFixedHeight(150)
    w.source_card_thumb.setMinimumWidth(0)
    w.source_card_thumb.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
    w.source_card_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    card_l.addWidget(w.source_card_thumb)
    card_text=QVBoxLayout();card_text.setSpacing(4)
    w.source_card_title=label('','panelTitle')
    w.source_card_detail=caption('')
    for text in (w.source_card_title,w.source_card_detail):
        text.setWordWrap(True);text.setMinimumWidth(0)
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        text.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
    card_text.addWidget(w.source_card_title)
    card_text.addWidget(w.source_card_detail)
    w.edit_handwriting_button=QPushButton('Edit in Handwriting panel')
    w.edit_handwriting_button.setObjectName('subtle')
    w.edit_handwriting_button.clicked.connect(lambda checked=False: w.show_handwriting_panel())
    card_text.addWidget(w.edit_handwriting_button)
    card_l.addLayout(card_text)
    src_l.addWidget(w.source_card)
    # exp.111: one button back to the picture as it came in.
    w.restore_original_button=QPushButton('↺  Restore original')
    w.restore_original_button.setObjectName('subtle')
    w.restore_original_button.setToolTip('Back to the picture as it came in: size, position, blend, opacity, '
                                         'ink on the page, colour and light. Ctrl+Z undoes it.')
    w.restore_original_button.clicked.connect(lambda checked=False: w.restore_original_look())
    src_l.addWidget(w.restore_original_button)
    # Image panel sections (exp.100), each closed until you open it, like Filmora:
    # Transform, Appearance, Ink on the page, Colour, Light, Original image, Image to drawing.
    from ui_sections import Section
    # The old "Source settings" fold is gone (kept hidden for older code).
    w.source_settings_toggle=QPushButton('Source settings',source_page);w.source_settings_toggle.setCheckable(True)
    w.source_settings_toggle.setChecked(True);w.source_settings_toggle.hide()
    w.source_settings=QWidget();w.source_settings.setMinimumWidth(0)
    ss_l=QVBoxLayout(w.source_settings);ss_l.setContentsMargins(0,0,0,0);ss_l.setSpacing(4)
    src_l.addWidget(w.source_settings)
    # Transform (imported artwork) — filled with the shared placement group.
    w.section_transform=Section('Transform',tip='Size and position of the picture on the page.')
    w.source_transform_heading=w.section_transform
    ss_l.addWidget(w.section_transform)
    w.source_transform_slot=QVBoxLayout();w.source_transform_slot.setSpacing(6)
    w.section_transform.body.addLayout(w.source_transform_slot)
    # Image settings use the same compact vertical field rhythm as lettering.
    # Unlike a wrapped QFormLayout, these groups cannot impose a wide label
    # column on the Source viewport when its splitter is dragged narrower.
    w.image_controls=QWidget()
    w.image_controls.setMinimumWidth(0)
    w.image_controls.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
    image_form=QVBoxLayout(w.image_controls)
    image_form.setContentsMargins(0,2,0,0)
    image_form.setSpacing(8)
    w.image_source_form=image_form

    # Label-left rows like the Animation panel (one shared label column).
    w.image_fields=form_layout()

    def image_choice(title, control):
        if image_form.indexOf(w.image_fields) < 0:
            image_form.addLayout(w.image_fields)
        w.image_fields.addRow(title,control)

    image_form.addWidget(caption('Line art: clean, artist-style pen strokes from any image, '
                                 'drawn by a small built-in line model. Original colors are painted afterwards.'))
    w.image_animation_style=QComboBox()
    w.image_animation_style.addItems(['Artist (layered)','Standard'])
    w.image_animation_style.setToolTip('Artist: light guide shapes first, then the main lines area by area '
                                       '(densest detail last, drawn more slowly), then dark accents, '
                                       'like a real pencil drawing. Standard: one pass of lines.')
    image_choice('Animation',w.image_animation_style)
    w.image_style=QComboBox();w.image_style.addItems(['Clean drawing','Detailed (all lines)'])
    w.image_style.setToolTip('Clean drawing: fewer, longer, smooth strokes like an artist\'s drawing; '
                             'shading is revealed by the colour painting. Detailed: every line found.')
    image_choice('Drawing style',w.image_style)
    w.image_detail=QComboBox();w.image_detail.addItems(['Low','Medium','High','Max'])
    w.image_detail.setCurrentIndex(1)
    w.image_detail.setToolTip('How many inner lines are drawn. Medium is recommended; Max draws the most detail and takes a little longer.')
    image_choice('Detail',w.image_detail)
    w.clean_faint=QCheckBox('Clean the background')
    w.clean_faint.setToolTip('Removes nearly invisible pixels (under 25% visible) left by background removal, '
                             'so neither the drawing nor the hand goes there.')
    image_form.addWidget(w.clean_faint)
    w.preserve_colors=QCheckBox('Preserve original colors')
    w.preserve_colors.setChecked(True)
    image_form.addWidget(w.preserve_colors)
    w.image_duration=w.number(.2,120,8,.5)
    # Painting timing belongs in the Animation inspector.
    w.image_duration.setParent(w.image_controls)
    w.rebuild_button=QPushButton('Apply image settings')
    w.rebuild_button.clicked.connect(w.rebuild_image)
    image_form.addWidget(w.rebuild_button)
    w.ai_lineart_button=QPushButton('✦  AI line art…')
    w.ai_lineart_button.setToolTip('An AI model redraws the image as clean line art; StrokeScribe '
                                   'traces those lines and paints your original colours.')
    w.ai_lineart_button.clicked.connect(lambda checked=False: w.open_create_image())
    image_form.addWidget(w.ai_lineart_button)
    w.own_lines_button=QPushButton('Use my line drawing…')
    w.own_lines_button.setToolTip('Already have a black line drawing of this image (for example from '
                                  'ChatGPT)? StrokeScribe lines it up with the image and traces it.')
    w.own_lines_button.clicked.connect(lambda checked=False: w.use_own_line_drawing())
    image_form.addWidget(w.own_lines_button)
    w.export_svg_button=QPushButton('Export drawing as SVG…')
    w.export_svg_button.setToolTip('Save the strokes as an editable SVG plus the matching colour PNG. '
                                   'Fix any line in Inkscape, then import with SVG source.')
    w.export_svg_button.clicked.connect(lambda checked=False: w.export_svg())
    image_form.addWidget(w.export_svg_button)
    w.image_controls.hide()
    # Appearance and matching-colour fields are built with the Animation
    # controls further down; their places in Source are reserved here.
    w.section_appearance=Section('Appearance',tip='Blend mode, opacity and paper cleanup.')
    w.source_appearance_heading=w.section_appearance
    ss_l.addWidget(w.section_appearance)
    w.source_appearance_slot=QVBoxLayout();w.source_appearance_slot.setSpacing(6)
    w.section_appearance.body.addLayout(w.source_appearance_slot)
    # Ink on the page, Colour, Light (build_look_sections).
    w.source_look_slot=QVBoxLayout();w.source_look_slot.setSpacing(4)
    ss_l.addLayout(w.source_look_slot)
    w.section_colors=Section('Matching colours',tip='The coloured picture that is painted after the lines.')
    w.source_colors_heading=w.section_colors
    src_l.addWidget(w.section_colors)
    w.source_colors_slot=QVBoxLayout();w.source_colors_slot.setSpacing(6)
    w.section_colors.body.addLayout(w.source_colors_slot)
    w.section_image_drawing=Section('Image to drawing',tip='How the picture is turned into lines.')
    w.image_drawing_heading=w.section_image_drawing
    src_l.addWidget(w.section_image_drawing)
    w.section_image_drawing.body.addWidget(w.image_controls)
    # No side margins inside these sections: the fields keep the width they had before
    # they moved into sections (8 px more made the narrowest panel overflow).
    for section in (w.section_transform,w.section_appearance,w.section_colors,w.section_image_drawing):
        section.body.setContentsMargins(0,6,0,10)
    w.source_note_slot=QVBoxLayout()
    src_l.addLayout(w.source_note_slot)
    src_l.addStretch(1)
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
    w.letter_detail_slider=linked_slider(w.font_size,24,128)
    detail_row=QWidget();detail_row.setMinimumWidth(0)
    detail_l=QHBoxLayout(detail_row);detail_l.setContentsMargins(0,0,0,0);detail_l.setSpacing(8)
    detail_l.addWidget(w.letter_detail_slider,1);detail_l.addWidget(w.font_size)
    font_size_form.addRow('Letter detail',detail_row)
    # Letter detail applies by itself (a moment after the last change).
    w.letter_timer=QTimer(w); w.letter_timer.setSingleShot(True); w.letter_timer.setInterval(700)
    w.letter_timer.timeout.connect(lambda: w.reletter())
    w.font_size.valueChanged.connect(lambda v: w.letter_timer.start()
                                     if getattr(w.drawing,'source_kind',None)=='font' else None)
    asset_l.addLayout(font_size_form)
    # Choosing another font re-writes the text at once (no need to press Animate);
    # Letter detail only means something for real fonts, not the built-in pen.
    w.font_select.activated.connect(lambda i: w.font_choice_changed())
    w.font_size.setEnabled(w.font_select.currentText()!='Built-in single-line pen')
    w.font_select.currentIndexChanged.connect(
        lambda i: w.font_size.setEnabled(w.font_select.currentText()!='Built-in single-line pen'))
    style_form=form_layout()
    w.font_color_button=QPushButton('Letter color: #25364A')
    w.font_color_button.setToolTip('Choose the ink color of handwritten text. Applies to current lettering and future lettering.')
    w.font_color_button.clicked.connect(w.choose_letter_color)
    w.ink_picker_button=QToolButton();w.ink_picker_button.setObjectName('subtle')
    from ui_icons import icon as _icon
    w.ink_picker_button.setIcon(_icon('eyedropper','#A9A6B8'))
    w.ink_picker_button.setToolTip('Pick a colour (use "Pick Screen Color" to take it from anywhere on screen)')
    w.ink_picker_button.clicked.connect(lambda checked=False: w.choose_letter_color())
    ink_row=QWidget();ink_row.setMinimumWidth(0)
    ink_l=QHBoxLayout(ink_row);ink_l.setContentsMargins(0,0,0,0);ink_l.setSpacing(6)
    ink_l.addWidget(w.font_color_button,1);ink_l.addWidget(w.ink_picker_button)
    style_form.addRow('Ink color',ink_row)
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
    # Fonts (collapsible): downloads and imports, closed by default.
    w.fonts_toggle=QPushButton('▸  Fonts');w.fonts_toggle.setObjectName('subtle')
    w.fonts_toggle.setCheckable(True)
    asset_l.addWidget(w.fonts_toggle)
    w.fonts_box=QWidget();w.fonts_box.setMinimumWidth(0)
    fonts_l=QVBoxLayout(w.fonts_box);fonts_l.setContentsMargins(0,0,0,0);fonts_l.setSpacing(8)
    w.fonts_toggle.toggled.connect(lambda opened: (w.fonts_box.setVisible(opened),
        w.fonts_toggle.setText(('▾' if opened else '▸')+'  Fonts')))
    fonts_l.addWidget(w.download_font)
    from font_library import STARTER_FONTS as _ALL_FONTS
    w.download_starters=QPushButton(f'Download all {len(_ALL_FONTS)} fonts')
    w.download_starters.setToolTip('Download every font in the list at once (about 10–40 MB; already '
                                   'downloaded fonts are skipped). Or choose one and use it: it downloads by itself.')
    w.download_starters.clicked.connect(w.install_starter_fonts)
    fonts_l.addWidget(w.download_starters)
    w.import_font_button=QPushButton('Import TTF / OTF…')
    w.import_font_button.clicked.connect(w.import_local_font)
    fonts_l.addWidget(w.import_font_button)
    browse_fonts=QPushButton('Browse Google Fonts ↗')
    browse_fonts.setObjectName('subtle')
    browse_fonts.clicked.connect(w.browse_google_fonts)
    fonts_l.addWidget(browse_fonts)
    w.font_note=caption('Built-in pen works offline. Google Fonts are downloaded only when requested; license files are saved too.')
    fonts_l.addWidget(w.font_note)
    asset_l.addWidget(w.fonts_box)
    w.fonts_box.setVisible(False)
    # Placement (lettering only) — filled with the shared placement group.
    w.handwriting_placement_heading=label('PLACEMENT')
    asset_l.addWidget(w.handwriting_placement_heading)
    w.handwriting_placement_slot=QVBoxLayout();w.handwriting_placement_slot.setSpacing(6)
    asset_l.addLayout(w.handwriting_placement_slot)
    asset_l.addStretch(1)
    # Lines & order works for every kind of element, so it lives in Animation.
    w.lines_box=QWidget()
    lines_box_l=QVBoxLayout(w.lines_box);lines_box_l.setContentsMargins(0,0,0,0);lines_box_l.setSpacing(8)
    # The big Line order window (line_order_dialog): see, pick, move several lines, auto order.
    w.line_order_button=QPushButton('✎  Line order…')
    w.line_order_button.setObjectName('primary')
    w.line_order_button.setToolTip('Open the Line order window: see the drawing big, pick several lines '
                                   'and move them together, or order them automatically.')
    w.line_order_button.clicked.connect(lambda checked=False: w.open_line_order())
    lines_box_l.addWidget(w.line_order_button)
    w.lines_toggle=QPushButton('▸ Lines & order')
    w.lines_toggle.setObjectName('subtle')
    w.lines_toggle.setCheckable(True)
    w.lines_toggle.setChecked(False)
    w.lines_toggle.setToolTip('Optional detailed line-by-line editing. Click to expand.')
    lines_box_l.addWidget(w.lines_toggle)
    w.lines_group=QWidget()
    lines_l=QVBoxLayout(w.lines_group)
    lines_l.setContentsMargins(0,0,0,0); lines_l.setSpacing(8)
    lines_l.addWidget(label('LINES & ORDER'))
    lines_l.addWidget(caption('Click a line on the preview (Ctrl+click for more) or in the list. '
                              'Drag in the list to change the drawing order.'))
    w.order=LineList()
    w.order.dropped.connect(lambda: w.order_dragged())
    w.order.setMinimumHeight(155)
    w.order.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
    w.order.setDragDropMode(QListWidget.DragDropMode.InternalMove)
    w.order.setDefaultDropAction(Qt.DropAction.MoveAction)
    w.order.itemSelectionChanged.connect(lambda: w.lines_selected())
    lines_l.addWidget(w.order,1)
    reorder=QHBoxLayout()
    for text,direction in [('Move up',-1),('Move down',1)]:
        button=QPushButton(text)
        button.clicked.connect(lambda checked=False,d=direction:w.move(d))
        reorder.addWidget(button)
    lines_l.addLayout(reorder)
    edit_row=QHBoxLayout()
    w.reverse_button=QPushButton('Reverse')
    w.reverse_button.setToolTip('Draw the selected line(s) from the other end.')
    w.reverse_button.clicked.connect(lambda checked=False: w.reverse_lines())
    edit_row.addWidget(w.reverse_button)
    w.delete_button=QPushButton('Delete')
    w.delete_button.setToolTip('Remove the selected line(s) from the animation (Delete key). Undo brings them back.')
    w.delete_button.clicked.connect(lambda checked=False: w.delete_lines())
    edit_row.addWidget(w.delete_button)
    lines_l.addLayout(edit_row)
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
    lines_l.addLayout(lt)
    for widget in (w.reverse_button,w.delete_button,w.line_pace,w.line_pause):
        widget.setEnabled(False)
    w.lines_group.setVisible(False)
    # One place for the order: the Line order window. The small list stays inside
    # (selection on the preview uses it) but is not shown.
    w.lines_toggle.setVisible(False)
    w.lines_toggle.toggled.connect(
        lambda opened: (w.lines_group.setVisible(opened),
                        w.lines_toggle.setText('▾ Lines & order' if opened else '▸ Lines & order')))
    lines_box_l.addWidget(w.lines_group)
    w.note=caption('Ready.')
    w.source_note_slot.addWidget(w.note)
    w.left_tabs=QTabWidget()
    w.left_tabs.setDocumentMode(True)
    w.left_tabs.setMinimumWidth(0)
    w.left_tabs.tabBar().hide()
    w.text_scroll=scroll_view(asset)
    w.left_tabs.addTab(w.text_scroll,'Text')
    asset_outer.addWidget(w.left_tabs,1)
    split.addWidget(asset_panel)

    # Large, dedicated visual monitor (center).
    monitor,monitor_outer,top=panel('monitorPanel','')
    monitor.title_label.hide()                 # no "Program" title over the preview
    monitor.setMinimumWidth(390)
    w.source_sidebar_button=QToolButton()
    w.source_sidebar_button.setObjectName('subtle')
    w.source_sidebar_button.setFixedWidth(30)
    top.insertWidget(0,w.source_sidebar_button)
    w.inspector_sidebar_button=QToolButton()
    w.inspector_sidebar_button.setObjectName('subtle')
    w.inspector_sidebar_button.setFixedWidth(30)
    top.addWidget(w.inspector_sidebar_button)
    # The rails open and close the panels now; these stay as hidden controls.
    w.source_sidebar_button.hide();w.inspector_sidebar_button.hide()
    w.fullscreen_button=QToolButton();w.fullscreen_button.setObjectName('subtle')
    w.fullscreen_button.setAutoRaise(True)
    w.fullscreen_button.setAccessibleName('Fullscreen canvas')
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
    top.addWidget(w.fullscreen_button)
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
    inspector.setMaximumWidth(480)
    tabs=QTabWidget()
    tabs.setDocumentMode(True)
    tabs.setMinimumWidth(0)
    tabs.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
    tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
    tabs.tabBar().setUsesScrollButtons(True)
    w.inspector_tabs=tabs
    inspector_l.addWidget(tabs,1)

    animation=QWidget()
    animation_l=QVBoxLayout(animation);animation_l.setContentsMargins(9,12,9,8)
    animation_l.setSpacing(10)
    from ui_sections import Section
    # Filmora-style sections: click a header to open it; optional parts have a switch.
    # Drawing on / off (exp.100): on = the hand draws the element (the default);
    # off = the element comes in with a Move in effect instead (the section below).
    # Both switches are views of the stored "Comes in" setting (w.entrance).
    w.draw_on=QCheckBox('Drawing',animation);w.draw_on.hide();w.draw_on.setChecked(True)
    w.draw_on.setToolTip('On: the hand draws this element. Off: it comes in with a Move in effect.')
    w.move_in_on=QCheckBox('Move in',animation);w.move_in_on.hide()
    w.move_in_on.setToolTip('On: this element comes in with an effect (Fade, Slide…) instead of being drawn.')
    w.section_drawing=Section('Drawing',switch=w.draw_on,tip='The hand draws the lines.')
    animation_l.addWidget(w.section_drawing)
    a=form_layout();w.section_drawing.body.addLayout(a)
    w.duration=w.number(.2,120,4,.1);a.addRow('Draw time (s)',w.duration)
    w.timing_form=a
    w.speed=w.number(.1,5,1,.1);a.addRow('Playback speed',w.speed)
    w.thickness=w.number(.1,10,1,.1);a.addRow('Line width',w.thickness)
    w.artwork_size=w.number(25,200,100,5)
    w.artwork_size.setSuffix('%')
    w.artwork_size.setToolTip('Scale only the artwork, not the hand. The hand size stays controlled by Hand Size. Above 100% may crop the artwork.')
    # Size and position are one setting with two homes: Handwriting → Placement
    # for lettering, Source → Transform for imported artwork (moved on select).
    w.placement_box=QWidget()
    w.placement_box.setMinimumWidth(0)
    placement_l=QVBoxLayout(w.placement_box);placement_l.setContentsMargins(0,0,0,0);placement_l.setSpacing(5)
    w.placement_form=form_layout();placement_l.addLayout(w.placement_form)
    scale_box=QWidget();scale_box.setMinimumWidth(0)
    scale_row=QHBoxLayout(scale_box);scale_row.setContentsMargins(0,0,0,0);scale_row.setSpacing(8)
    scale_row.addWidget(w.artwork_size)
    w.scale_slider=linked_slider(w.artwork_size,25,200)
    scale_row.addWidget(w.scale_slider,1)
    w.placement_form.addRow('Scale',scale_box)
    # Position on the page: drag the picture on the preview, or type it here.
    w.picture_x=w.number(-100,100,0,1); w.picture_x.setSuffix('%')
    w.picture_y=w.number(-100,100,0,1); w.picture_y.setSuffix('%')
    for box,side in ((w.picture_x,'right (minus: left)'),(w.picture_y,'down (minus: up)')):
        box.setToolTip(f'Move the picture {side}, in % of the video size. '
                       'Easier: drag the picture on the preview.')
    w.picture_center=QPushButton('Center'); w.picture_center.setObjectName('subtle')
    w.picture_center.setToolTip('Put the picture back in the middle.')
    w.picture_center.clicked.connect(lambda checked=False: (w.picture_x.setValue(0), w.picture_y.setValue(0)))
    # Give the two position spinboxes the FULL row width. When this nested
    # horizontal pair shared a form row with the 'Position X / Y' label, its
    # combined minimum width could force the entire Inspector form outside the
    # scroll viewport after image-only fields appeared.
    # One row each, so both fields keep a usable width in the narrowest panel.
    # Slider plus number, like Scale (exp.100): drag, click the track, or type.
    w.position_sliders={}
    for title,box in (('Position X',w.picture_x),('Position Y',w.picture_y)):
        holder=QWidget();holder.setMinimumWidth(0)
        row=QHBoxLayout(holder);row.setContentsMargins(0,0,0,0);row.setSpacing(8)
        row.addWidget(box)
        slider=linked_slider(box,-100,100)
        slider.setToolTip(box.toolTip())
        row.addWidget(slider,1)
        w.position_sliders[title]=slider
        w.placement_form.addRow(title,holder)
    w.x_slider,w.y_slider=w.position_sliders['Position X'],w.position_sliders['Position Y']
    w.placement_form.addRow('',w.picture_center)
    w.source_transform_slot.addWidget(w.placement_box)    # moved by kind on select
    w.pen_ease=QComboBox()
    w.pen_ease.addItems(['Constant speed','Natural (ease in and out)'])
    w.pen_ease.setToolTip('Natural: every line starts and ends a little slower, like a real hand.')
    a.addRow('Pen movement',w.pen_ease)
    w.pause_after=w.number(0,60,0,.5)
    w.pause_after.setToolTip('Seconds the finished element stays on screen before it goes out or the '
                             'camera moves on (works with or without colours).')
    a.addRow('Pause after (s)',w.pause_after)
    w.camera=QComboBox()
    from camera import ZOOM_MODE as _ZOOM_MODE
    w.camera.addItems(['Off','Gentle zoom','Close-up zoom',_ZOOM_MODE])
    w.camera.setToolTip('Camera follow: the view zooms in and glides after the pen, then pulls back '
                        'to show the whole picture at the end.')
    w.auto_timing_button=QPushButton('Auto timing')
    w.auto_timing_button.setToolTip('Pick draw, paint and hold times from how much there is to draw '
                                    'and paint (or from the voiceover length, if one is loaded).')
    w.auto_timing_button.clicked.connect(lambda checked=False: w.auto_timing())
    w.auto_timing_button.hide()          # removed from the panel (kept for File projects/tests)
    w.section_move_in=Section('Move in',switch=w.move_in_on,
                              tip='The element comes in with an effect instead of being drawn by the hand.')
    animation_l.addWidget(w.section_move_in)
    mi=form_layout();w.section_move_in.body.addLayout(mi);w.move_in_form=mi
    from frame_render import ENTRANCES
    w.entrance=QComboBox(); w.entrance.addItems(list(ENTRANCES))
    w.entrance.setToolTip('The effect this element comes in with (no drawing hand).')
    w.entrance.view().setRowHidden(0,True)           # "Draw with the hand" is the Drawing switch
    mi.addRow('Comes in',w.entrance)
    import move_in
    w.entrance_part=QComboBox(); w.entrance_part.addItems(list(move_in.PARTS))
    w.entrance_part.setToolTip('What comes in with the effect: the whole picture, or only the lines '
                               '(then the painting hand paints the colours as usual).')
    mi.addRow('Moves in',w.entrance_part)
    w.move_time=w.number(.2,120,4,.1)
    w.move_time.setToolTip('How long the element takes to come in with its effect.')
    mi.addRow('Move-in time (s)',w.move_time)
    # The hand that carries the picture in (Slide effects): upload it right here too.
    w.move_in_hand_button=QPushButton('Upload hand…')
    w.move_in_hand_button.setToolTip('Your own transparent PNG of a hand that holds the picture while it '
                                     'slides in. Draw it coming from below (arm down); it is turned for '
                                     'the other sides. More settings: Hand panel > Move-in hand.')
    w.move_in_hand_button.clicked.connect(lambda checked=False: w.choose_move_hand())
    mi.addRow('Moving hand',w.move_in_hand_button)
    w.move_in_hand_name=caption('Built-in hand')
    w.move_in_hand_name.setWordWrap(True)
    mi.addRow('',w.move_in_hand_name)
    w.section_painting=Section('Colour & painting',tip='How the colours are painted after the lines.')
    animation_l.addWidget(w.section_painting)
    w.load_color_button=QPushButton('Load matching colored PNG…')
    w.load_color_button.clicked.connect(w.load_color)
    w.source_colors_slot.addWidget(w.load_color_button)
    w.clean_color=QCheckBox('Clean the PNG\'s background')
    w.clean_color.setChecked(True)
    w.clean_color.setToolTip('Makes the transparency complete: a painted checkerboard ("fake transparency") '
                             'or a plain sheet behind the artwork, and faint leftovers, become transparent. '
                             'Parts inside the artwork are kept.')
    w.clean_color.toggled.connect(lambda checked: w.reload_color())
    w.source_colors_slot.addWidget(w.clean_color)
    # Short label: it sits under the MATCHING COLORS heading in the narrow
    # Source column (the long wording needed 251 px with Linux fonts).
    w.use_color=QCheckBox('Reveal colors after drawing')
    w.use_color.setToolTip('Reveal the original artwork (the matching colored PNG) after the lines are drawn.')
    w.use_color.setEnabled(False)
    w.source_colors_slot.addWidget(w.use_color)
    w.color_note=caption('No original PNG loaded')
    w.source_colors_slot.addWidget(w.color_note)
    w.blend_mode=QComboBox()
    from blend_modes import MODES as _BLEND_MODES
    w.blend_mode.addItems(_BLEND_MODES)
    w.blend_mode.setToolTip(
        'Composites this artwork over a visible background/earlier element. '
        'Multiply makes white paper disappear visually over that background. '
        'An alpha/transparent export still needs background cleanup if you '
        'want to remove white pixels permanently.')
    # Shown in Source → Appearance for imported artwork; the Element Editor
    # keeps editing the same fields (lettering included), as before.
    blend_form=form_layout()
    blend_form.addRow('Blend mode',w.blend_mode)
    w.artwork_opacity=w.number(0,100,100,1)
    w.artwork_opacity.setSuffix('%')
    w.opacity_slider=linked_slider(w.artwork_opacity,0,100)
    opacity_box=QWidget();opacity_box.setMinimumWidth(0)
    opacity_row=QHBoxLayout(opacity_box);opacity_row.setContentsMargins(0,0,0,0);opacity_row.setSpacing(8)
    opacity_row.addWidget(w.artwork_opacity);opacity_row.addWidget(w.opacity_slider,1)
    blend_form.addRow('Opacity',opacity_box)
    w.opacity_row=opacity_box
    w.paper_cleanup=QCheckBox('Clean white / paper background')
    blend_form.addRow(w.paper_cleanup)
    w.paper_tolerance=w.number(0,80,22,1)
    blend_form.addRow('Paper tolerance',w.paper_tolerance)
    w.paper_softness=w.number(0,50,8,1)
    blend_form.addRow('Edge softness',w.paper_softness)
    w.source_appearance_slot.addLayout(blend_form)
    build_look_sections(w)
    w.appearance_form=blend_form
    a2=form_layout();w.section_painting.body.addLayout(a2)
    w.reveal_mode=PaintModeCombo(lambda: w.open_paint_mode_picker())
    w.reveal_mode.addItems(['Brush painting','Adaptive Hand Painting','Zigzag sweep',
                            'Top to bottom (rows)','Left to right (columns)',
                            'Adaptive — Short up/down strokes',
                            'Painter — real parts, strokes follow the shape'])
    w.reveal_mode.setItemData(3,'Like a painter: the colours are brushed in band by band from the top '
                              'down, sweeping left and right across the whole picture.',Qt.ItemDataRole.ToolTipRole)
    w.reveal_mode.setItemData(4,'The colours are brushed in band by band from the left to the right, '
                              'sweeping up and down across the whole picture.',Qt.ItemDataRole.ToolTipRole)
    w.reveal_mode.setCurrentIndex(1)
    w.reveal_mode.setItemData(2,'The hand follows one route along the object, scribbling colour '
                              'back and forth across it (wider on broad parts).',Qt.ItemDataRole.ToolTipRole)
    w.reveal_mode.setItemData(5,'Uses the original Adaptive region-by-region route with rapid '
                              'short up/down brush flicks along that route. Does not use '
                              'top-to-bottom painting bands.',
                              Qt.ItemDataRole.ToolTipRole)
    w.reveal_mode.setItemData(6,'New: paints like a person: big parts first, details last, each part '
                              'brushed around its shape from the edge inwards.',Qt.ItemDataRole.ToolTipRole)
    a2.addRow('Paint mode',w.reveal_mode)
    # Painter: which parts it paints (colour areas, or real parts found by the AI).
    w.painter_parts_note=caption('Parts: colour areas')
    w.painter_parts_note.setWordWrap(True)
    a2.addRow('',w.painter_parts_note)
    w.find_parts_button=QPushButton('Find real parts (AI)…')
    w.find_parts_button.setToolTip('Segment Anything finds the real parts of this picture (a cushion, '
                                   'a speaker, the band) for Painter. Runs once on your graphics card; '
                                   'the first time it downloads the model (about 2.4 GB).')
    w.find_parts_button.clicked.connect(lambda checked=False: w.find_ai_parts())
    w.colour_parts_button=QPushButton('Colour areas')
    w.colour_parts_button.setToolTip('Forget the AI parts and paint by colour areas again.')
    w.colour_parts_button.clicked.connect(lambda checked=False: w.forget_ai_parts())
    w.painter_parts_buttons=QWidget();w.painter_parts_buttons.setMinimumWidth(0)
    _row=QHBoxLayout(w.painter_parts_buttons);_row.setContentsMargins(0,0,0,0);_row.setSpacing(6)
    for _b in (w.find_parts_button,w.colour_parts_button):
        _b.setMinimumWidth(0);_b.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        _row.addWidget(_b,1)
    a2.addRow('Parts',w.painter_parts_buttons)
    w.image_paint_hint=caption('Image sources paint with Adaptive Hand Painting or Zigzag sweep. Original PNG colors are preserved.')
    a2.addRow(w.image_paint_hint)
    w.color_fade=w.number(0,20,.4,.1);a2.addRow('SVG paint time (s)',w.color_fade)
    a2.addRow('Image paint time (s)',w.image_duration)
    w.paint_form=a2
    w.image_animation=QComboBox()
    w.image_animation.addItems(['Draw, then Paint','Paint Only','Drawing only'])
    w.image_animation.setToolTip(
        'Draw, then Paint: draw temporary lines and replace them while painting. '
        'Paint Only: skip all visible line drawing and paint colors directly. '
        'Drawing only: animate the strokes without revealing original colors. '
        'Both painting modes use the same AI path analysis and brush coverage; there is no separate erasing phase.')
    a2.addRow('Image animation',w.image_animation)
    w.image_animation.currentIndexChanged.connect(w.change_image_animation)
    w.brush_width=w.number(.02,.5,.14,.02);a2.addRow('Brush width',w.brush_width)
    w.stroke_spacing=w.number(.2,.9,.55,.05)
    w.stroke_spacing.setToolTip('Lower values add more overlap between brush strokes.')
    a2.addRow('Stroke spacing',w.stroke_spacing)
    w.color_hold=w.number(0,30,.6,.1);a2.addRow('Hold (s)',w.color_hold)
    # "Goes out" on / off: a switch for the Goes out list (Off, or the last way chosen).
    w.erase_on=QCheckBox('Exit',animation);w.erase_on.hide()
    w.erase_on.setToolTip('The element goes away at the end (eraser or an effect).')
    w.section_out=Section('Exit (at the end)',switch=w.erase_on,
                          tip='How the element goes away at the end: an eraser, or an effect.')
    animation_l.addWidget(w.section_out)
    a3=form_layout();w.section_out.body.addLayout(a3)
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
    animation_l.addWidget(w.lines_box)
    # exp.111: the order of the work: 1 Drawing, 2 Colour & painting, 3 Line order,
    # then Move in, and Exit (at the end) last.
    for widget in (w.section_drawing,w.section_painting,w.lines_box,w.section_move_in,w.section_out):
        animation_l.removeWidget(widget)
    for widget in (w.section_drawing,w.section_painting,w.lines_box,w.section_move_in,w.section_out):
        animation_l.addWidget(widget)
    animation_l.addStretch(1)
    tabs.addTab(scroll_view(animation),'Animation')

    hand=QWidget();hand_l=QVBoxLayout(hand)
    hand_l.setContentsMargins(9,12,9,8);hand_l.setSpacing(12)
    # Two clear parts: the hand that DRAWS the lines, and the one that PAINTS the colours.
    def picture(key,into=None):
        row=QHBoxLayout(); row.setSpacing(10)
        pic=QLabel(); pic.setObjectName('monitorWell'); pic.setFixedSize(120,92)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(pic); w.hand_pictures[key]=pic
        row.addStretch(1)
        (into if into is not None else hand_l).addLayout(row)
        return row
    w.hand_pictures={}

    def pair(*buttons):
        """Buttons side by side in the field column of a form row."""
        box=QWidget();box.setMinimumWidth(0)
        row=QHBoxLayout(box);row.setContentsMargins(0,0,0,0);row.setSpacing(6)
        for button in buttons:
            row.addWidget(button,1)
        return box

    # 1. The drawing hand: one label column, like the Animation panel.
    from ui_sections import Section
    w.section_draw_hand=Section('Drawing hand',tip='The hand that draws the lines.')
    hand_l.addWidget(w.section_draw_hand)
    picture('draw',w.section_draw_hand.body)
    w.hand_name=caption('Hand: none')
    w.section_draw_hand.body.addWidget(w.hand_name)
    h=form_layout();w.section_draw_hand.body.addLayout(h)
    w.hand_size_pct=QSpinBox();w.hand_size_pct.setRange(2,80);w.hand_size_pct.setSuffix('%')
    w.hand_size_pct.setToolTip('Size of the drawing hand.')
    h.addRow('Size',w.hand_size_pct)
    w.builtin_tool=QComboBox()
    w.builtin_tool.addItems(['Hand with pen','Pencil','Marker'])
    w.builtin_tool.setToolTip('The built-in hand holding a pen (default), or a pencil or marker on its own.')
    w.builtin_tool.activated.connect(
        lambda index: w.use_builtin_tool(('hand','pencil','marker')[index]))
    h.addRow('Built-in',w.builtin_tool)
    load_hand=QPushButton('My PNG…')
    load_hand.setToolTip('Your own transparent PNG of a hand holding a pen.')
    load_hand.clicked.connect(w.loadhand)
    hands_library=QPushButton('Library…')
    hands_library.setToolTip('Choose a hand from your Hands library.')
    hands_library.clicked.connect(lambda checked=False: w.open_library('hands'))
    h.addRow('Your own',pair(load_hand,hands_library))
    w.showhand=QCheckBox('Show while drawing')
    w.showhand.setToolTip('Show the hand while it draws the lines.')
    w.showhand.setChecked(True);h.addRow('',w.showhand)
    h.setRowVisible(w.showhand,False)            # the switch on the section header
    # Right or left hand: a small two-way switch. The (hidden) check box keeps the
    # value for projects, undo and the element editor.
    w.left_handed=QCheckBox('Left-handed',hand);w.left_handed.hide()
    w.left_handed_toggle=side_toggle(w.left_handed,
        'Right-handed or left-handed drawing hand. Left mirrors the drawing hand, the eraser '
        'and the move-in hand.')
    h.addRow('Hand',w.left_handed_toggle)
    w.handsize=w.number(.02,.8,.75,.01);h.addRow('Hand size',w.handsize)
    h.setRowVisible(w.handsize,False)        # edited through Size (%) above
    w.hand_size_pct.setValue(round(w.handsize.value()*100))
    w.hand_size_pct.valueChanged.connect(
        lambda v: abs(w.handsize.value()*100-v)>=.5 and w.handsize.setValue(v/100))
    w.handsize.valueChanged.connect(lambda v: (w.hand_size_pct.blockSignals(True),
        w.hand_size_pct.setValue(round(v*100)),w.hand_size_pct.blockSignals(False)))
    # Defaults calibrated for the built-in hand (assets/default_hand.png).
    w.ax=w.number(0,1,.08,.005);w.ax.setDecimals(3);h.addRow('Pen tip X',w.ax)
    w.ay=w.number(0,1,.13,.005);w.ay.setDecimals(3);h.addRow('Pen tip Y',w.ay)
    w.find_tip_button=QPushButton('Find')
    w.find_tip_button.setToolTip('Look for the pen tip in the hand image automatically. New hands get '
                                 'their pen tip found by themselves; adjust it if lines do not start at the pen.')
    w.find_tip_button.clicked.connect(lambda checked=False: w.find_pen_tip())
    w.pick_tip_button=QPushButton('Click to set…')
    w.pick_tip_button.setToolTip('Show the hand and click exactly on the pen tip.')
    w.pick_tip_button.clicked.connect(lambda checked=False: w.pick_pen_tip())
    h.addRow('Pen tip',pair(w.find_tip_button,w.pick_tip_button))
    # 2. The painting hand.
    w.section_paint_hand=Section('Painting hand',tip='The hand that paints the colours.')
    hand_l.addWidget(w.section_paint_hand)
    picture('paint',w.section_paint_hand.body)
    from tools_kit import PAINT_CHOICES
    ph=form_layout();w.section_paint_hand.body.addLayout(ph)
    w.paint_hand=QComboBox()
    w.paint_hand.addItems(list(PAINT_CHOICES))
    w.paint_hand.setToolTip('The same hand paints the colours (default), or it switches to the built-in '
                            'paint brush, or to a hand from your Hands library.')
    ph.addRow('Paints with',w.paint_hand)
    w.paint_hand_size=w.number(5,90,30,1);w.paint_hand_size.setDecimals(0)
    w.paint_hand_size.setToolTip('Width of the painting hand, as a share of the video width.')
    w.paint_hand_size.setSuffix('%')
    ph.addRow('Size',w.paint_hand_size)
    w.paint_hand_form=ph
    w.paint_hand_choose=QPushButton('Choose…')
    w.paint_hand_choose.setToolTip('Choose the painting hand from your Hands library.')
    w.paint_hand_choose.clicked.connect(lambda checked=False: w.choose_paint_hand())
    ph.addRow('',w.paint_hand_choose)
    w.paint_hand_name=caption('')
    ph.addRow('',w.paint_hand_name)
    w.show_paint_hand=QCheckBox('Show while painting')
    w.show_paint_hand.setToolTip('Show the hand while it paints the colours.')
    w.show_paint_hand.setChecked(True);ph.addRow('',w.show_paint_hand)
    ph.setRowVisible(w.show_paint_hand,False)    # the switch on the section header
    w.paint_left_handed=QCheckBox('Left-handed',hand);w.paint_left_handed.hide()
    w.paint_left_handed_toggle=side_toggle(w.paint_left_handed,
        'Right-handed or left-handed painting hand. With "Same as drawing hand" it follows '
        'the drawing hand.')
    ph.addRow('Hand',w.paint_left_handed_toggle)
    # 3. The move-in hand: carries the picture in on the Slide effects (Animation > Comes in).
    w.section_move_hand=Section('Move-in hand',tip='The hand that carries the picture in on the Slide effects.')
    hand_l.addWidget(w.section_move_hand)
    picture('move',w.section_move_hand.body)
    mh=form_layout();w.section_move_hand.body.addLayout(mh)
    w.move_hand_name=caption('Hand: built-in (placeholder)')
    mh.addRow('',w.move_hand_name)
    w.move_hand_size=w.number(5,90,35,1);w.move_hand_size.setDecimals(0)
    w.move_hand_size.setSuffix('%')
    w.move_hand_size.setToolTip('Width of the move-in hand, as a share of the video width.')
    mh.addRow('Size',w.move_hand_size)
    w.move_hand_choose=QPushButton('Upload hand…')
    w.move_hand_choose.setToolTip('Your own transparent PNG of a hand that holds the picture. '
                                  'Draw it coming from below (arm down); it is turned for the other sides.')
    w.move_hand_choose.clicked.connect(lambda checked=False: w.choose_move_hand())
    w.move_hand_builtin=QPushButton('Built-in')
    w.move_hand_builtin.setToolTip('Go back to the built-in hand.')
    w.move_hand_builtin.clicked.connect(lambda checked=False: w.set_move_hand(None))
    mh.addRow('Hand',pair(w.move_hand_choose,w.move_hand_builtin))
    w.move_hand_gx=w.number(0,1,move_in.DEFAULT_GRIP[0],.005);w.move_hand_gx.setDecimals(3)
    w.move_hand_gx.setToolTip('Where the hand holds the picture, across the hand image (0 = left, 1 = right).')
    mh.addRow('Grip X',w.move_hand_gx)
    w.move_hand_gy=w.number(0,1,move_in.DEFAULT_GRIP[1],.005);w.move_hand_gy.setDecimals(3)
    w.move_hand_gy.setToolTip('Where the hand holds the picture, down the hand image (0 = top, 1 = bottom).')
    mh.addRow('Grip Y',w.move_hand_gy)
    w.move_hand=QCheckBox('Show while moving in')
    w.move_hand.setToolTip('A hand carries the picture in when it slides in (Animation > Comes in: '
                           'Slide in from …), lets go, and leaves the way it came.')
    w.move_hand.setChecked(True);mh.addRow('',w.move_hand)
    mh.setRowVisible(w.move_hand,False)          # the switch on the section header
    w.section_draw_hand.attach_switch(w.showhand,'Show the hand while it draws the lines.')
    w.section_paint_hand.attach_switch(w.show_paint_hand,'Show the hand while it paints the colours.')
    w.section_move_hand.attach_switch(w.move_hand,'A hand carries the picture in on the Slide effects.')
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
    from ui_icons import icon as _icon
    sound_files=form_layout();sound_l.addLayout(sound_files)
    w.sound_remove_buttons={}
    for key,text in (('sound_pencil_file','Pencil'),('sound_brush_file','Brush'),('sound_eraser_file','Eraser')):
        box=QWidget();box.setMinimumWidth(0)
        row=QHBoxLayout(box);row.setContentsMargins(0,0,0,0);row.setSpacing(6)
        button=QPushButton('Add sound…')
        button.setToolTip(f'Choose a recording (MP3, WAV, M4A…) for the {text.lower()}.')
        button.clicked.connect(lambda checked=False,k=key: w.choose_sound_file(k))
        row.addWidget(button,1)
        reset=QToolButton();reset.setObjectName('panelClose')
        reset.setIcon(_icon('trash','#E5484D'));reset.setFixedWidth(30)
        reset.setToolTip(f'Remove the {text.lower()} sound.')
        reset.clicked.connect(lambda checked=False,k=key: w.set_sound_file(k,None))
        row.addWidget(reset)
        reset.hide()                         # shown once a sound is chosen
        sound_files.addRow(text,box)
        w.sound_file_buttons[key]=(button,text)
        w.sound_remove_buttons[key]=reset
    w.sound_volume=QSpinBox();w.sound_volume.setRange(0,100);w.sound_volume.setValue(80)
    w.sound_volume.setSuffix('%')
    e4=form_layout();e4.addRow('Volume',w.sound_volume)
    sound_l.addLayout(e4)
    w.sound_preview=QCheckBox('Hear the sound when playing the preview')
    w.sound_preview.setChecked(True)
    sound_l.addWidget(w.sound_preview)
    sound_l.addWidget(caption('Included in MP4, WebM and MOV. PNG exports also get soundtrack.wav.'))
    sound_l.addStretch(1)
    # Music: the voiceover / music track.
    music=QWidget();music_l=QVBoxLayout(music)
    music_l.setContentsMargins(9,12,9,8);music_l.setSpacing(10)
    music_l.addWidget(label('VOICEOVER / MUSIC'))
    audio_row=QGridLayout()
    audio_row.setHorizontalSpacing(6)
    audio_row.setVerticalSpacing(5)
    w.load_audio_button=QPushButton('Load audio…')
    w.load_audio_button.setToolTip('Add a voiceover or music track (MP3, WAV, M4A, OGG, FLAC…).')
    w.load_audio_button.clicked.connect(lambda checked=False: w.load_audio())
    audio_row.addWidget(w.load_audio_button,0,0)
    audio_library=QPushButton('Library…')
    audio_library.clicked.connect(lambda checked=False: w.open_library('audio'))
    audio_row.addWidget(audio_library,0,1)
    w.remove_audio_button=QPushButton('Remove')
    w.remove_audio_button.setEnabled(False)
    w.remove_audio_button.clicked.connect(lambda checked=False: w.remove_audio())
    audio_row.addWidget(w.remove_audio_button,1,0,1,2)
    music_l.addLayout(audio_row)
    w.audio_note=caption('No audio track')
    music_l.addWidget(w.audio_note)
    e5=form_layout()
    w.audio_volume=QSpinBox();w.audio_volume.setRange(0,200);w.audio_volume.setValue(100)
    w.audio_volume.setSuffix('%');e5.addRow('Track volume',w.audio_volume)
    w.audio_offset=w.number(0,600,0,.1)
    w.audio_offset.setToolTip('Seconds into the video when the track starts.')
    e5.addRow('Starts at (s)',w.audio_offset)
    music_l.addLayout(e5)
    w.fit_audio_button=QPushButton('Fit animation to audio')
    w.fit_audio_button.setEnabled(False)
    w.fit_audio_button.setToolTip('Stretch draw, paint, hold and erase times so the video ends when the track ends.')
    w.fit_audio_button.clicked.connect(lambda checked=False: w.fit_to_audio())
    music_l.addWidget(w.fit_audio_button)
    music_l.addStretch(1)
    # Camera: camera follow (moves between elements are set on the timeline).
    camera_page=QWidget();camera_l=QVBoxLayout(camera_page)
    camera_l.setContentsMargins(9,12,9,8);camera_l.setSpacing(10)
    camera_l.addWidget(label('THIS ELEMENT\'S CAMERA'))
    camera_form=form_layout();camera_form.addRow('Camera',w.camera)
    camera_l.addLayout(camera_form)
    w.camera_note=caption('')
    camera_l.addWidget(w.camera_note)
    # exp.115: the element's own camera, from a start framing to an end framing. The
    # camera moves between elements (the camera row of the timeline) have the last word:
    # a zoom still running when the move starts goes on, and the move takes over from it.
    w.camera_zoom_box=QWidget(); zb=QVBoxLayout(w.camera_zoom_box); zb.setContentsMargins(0,0,0,0); zb.setSpacing(6)
    w.camera_zoom_widgets={}
    def cam_row(form,key,text,low,high,value,step,suffix,decimals=0,tip=''):
        spin=w.number(low,high,value,step); spin.setDecimals(decimals); spin.setSuffix(suffix)
        if tip: spin.setToolTip(tip)
        setattr(w,key,spin); w.camera_zoom_widgets[key]=spin
        holder=QWidget(); line=QHBoxLayout(holder); line.setContentsMargins(0,0,0,0); line.setSpacing(8)
        slider=linked_slider(spin,low,high,scale=10 if decimals else 1)
        line.addWidget(slider,1); line.addWidget(spin)
        form.addRow(text,holder)
        return spin
    for title,prefix,zoom in (('START','cam_start',100.),('END','cam_end',160.)):
        zb.addWidget(label(title+' FRAMING'))
        f=form_layout(); zb.addLayout(f)
        cam_row(f,prefix+'_zoom','Zoom',100,500,zoom,5,'%',tip='100% shows the whole element; 200% is twice as close.')
        cam_row(f,prefix+'_x','Centre X',0,100,50,1,'%',tip='Where the camera looks, across (50% = the middle).')
        cam_row(f,prefix+'_y','Centre Y',0,100,50,1,'%',tip='Where the camera looks, down (50% = the middle).')
    zb.addWidget(label('SPEED'))
    f=form_layout(); zb.addLayout(f)
    cam_row(f,'cam_begin','Starts at',0,120,0,.1,' s',1,'Seconds into the element when the camera starts to move.')
    cam_row(f,'cam_time','Zoom time',.2,30,1.2,.1,' s',1,'How long the camera takes from the start framing to '
            'the end framing. Longer than the element: it goes on into the camera move after it.')
    zb.addWidget(caption('The camera moves between elements (camera row of the timeline) have the last word: '
                         'if this zoom is still running when the move starts, the move takes over from it '
                         'gradually and lands on the next element.'))
    camera_l.addWidget(w.camera_zoom_box)
    camera_l.addStretch(1)
    def camera_mode_changed(*_):
        zoom=w.camera.currentText()==_ZOOM_MODE
        w.camera_zoom_box.setVisible(zoom)
        w.camera_note.setText('' if zoom else 'Gentle / Close-up zoom: the view zooms in and glides after the pen, '
                              'then pulls back to show the whole picture. Camera moves between elements are on '
                              'the timeline: click a camera on the Camera row.')
    w.camera.currentIndexChanged.connect(camera_mode_changed)
    for spin in w.camera_zoom_widgets.values():
        spin.valueChanged.connect(lambda *_: w.refresh())
    w.camera_mode_changed=camera_mode_changed
    camera_mode_changed()
    w.left_tabs.addTab(scroll_view(sound),'Sound')
    w.left_tabs.addTab(scroll_view(music),'Music')
    w.left_tabs.addTab(scroll_view(camera_page),'Camera')
    tabs.insertTab(TABS['source'],scroll_view(source_page),'Image')
    # AI: the Create Image / Create a sound tools (replaces the top-bar button).
    ai_page=QWidget();ai_l=QVBoxLayout(ai_page)
    ai_l.setContentsMargins(9,12,9,8);ai_l.setSpacing(10)
    ai_l.addWidget(caption('Runs on your PC with the local AI engine. Each tool opens the Create '
                           'Image window on that task.'))
    w.ai_buttons={}
    for task,text,tip in (
            ('lineart','Line art for my image','An AI model redraws the selected image as clean line art.'),
            ('generate','Create image from text','Describe a picture and create it on your PC.'),
            ('edit','Edit an image','Change an image with a written instruction.'),
            ('sound','Create a sound','Make a pencil, brush or eraser sound.')):
        button=QPushButton(text);button.setToolTip(tip)
        button.clicked.connect(lambda checked=False,t=task: w.open_create_image(t))
        ai_l.addWidget(button)
        w.ai_buttons[task]=button
    w.ai_buttons['lineart'].setObjectName('primary')
    ai_l.addStretch(1)
    tabs.insertTab(TABS['ai'],scroll_view(ai_page),'AI')
    # The rail replaces the tab strip; the panel title names the open page.
    tabs.tabBar().hide()
    inspector.title_label.setText(tabs.tabText(tabs.currentIndex()))
    split.addWidget(inspector)
    split.setStretchFactor(0,0)
    split.setStretchFactor(1,1)
    split.setStretchFactor(2,0)
    split.setSizes([290,850,330])
    from workspace_layout import SidebarController
    w.sidebar_layout=SidebarController(w,split,asset_panel,inspector,
                                       w.source_sidebar_button,w.inspector_sidebar_button,
                                       names={'source':'Handwriting','inspector':'right'})
    build_rails(w,tabs,inspector)

    # Time-based workflow remains visible whichever Inspector tab is open.
    timeline,timeline_outer,timeline_head=panel('timelinePanel','Timeline','Click or drag to scrub')
    w.timeline_panel=timeline
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
    w.scene_list.setIconSize(QSize(58,33))         # exp.110: smaller cards
    w.scene_list.setGridSize(QSize(112,78))
    w.scene_list.setWordWrap(True)
    w.scene_list.setFixedHeight(90)
    w.scene_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    w.scene_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.scene_list.setToolTip('The elements of your video, in order (like VideoScribe). Click one to work on it; '
                            'double-click (or Edit…) for its settings: how it comes in, its times, colours, '
                            'how it goes out and the move to the next one.')
    w.scene_list.currentRowChanged.connect(lambda row: w.select_scene(row))
    w.scene_list.itemDoubleClicked.connect(lambda item: w.edit_element(w.scene_list.row(item)))
    def strip_menu_at():
        item=w.scene_list.item(len(w.scenes))
        if item is None: return w.add_element_menu(False,None)
        rect=w.scene_list.visualItemRect(item)
        from PySide6.QtWidgets import QMenu
        w.add_element_menu(False,None,at=w.scene_list.viewport().mapToGlobal(rect.bottomLeft()))
    w._strip_menu_at=strip_menu_at
    scene_row.addWidget(w.scene_list,1)
    scene_buttons=QVBoxLayout();scene_buttons.setSpacing(4)
    w.scene_add=QPushButton('+ Add element')
    w.scene_add.setToolTip('A new element after this one: choose a picture or SVG, write a text, or pick from the Library. '
                           'The camera moves to it.')
    w.scene_add.clicked.connect(lambda checked=False: w.add_element_menu(False,w.scene_add))
    w.scene_picture=QPushButton('+ On this page')
    w.scene_picture.setToolTip('A new element on the SAME page (no camera move), like VideoScribe: it goes '
                               'to a free place next to the pictures already there. When the page is full, '
                               'it goes to a new page and the camera moves there.')
    w.scene_picture.clicked.connect(lambda checked=False: w.add_element_menu(True,w.scene_picture))
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
    w.preview_scope.setItemData(0,'Only the element you are editing (its own parts on the timeline).',Qt.ItemDataRole.ToolTipRole)
    w.preview_scope.setItemData(1,'The whole video: every element one after the other, with the camera moves.',Qt.ItemDataRole.ToolTipRole)
    w.preview_scope.setItemData(2,'Board: all elements on one big page seen from above. Move them, make them '
                                  'bigger or smaller: the camera follows.',Qt.ItemDataRole.ToolTipRole)
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
    w.stage_timeline.element_clicked.connect(lambda k: w.timeline_element_clicked(k))
    w.stage_timeline.move_clicked.connect(lambda k: w.edit_camera_move(k))
    w.stage_timeline.element_camera_clicked.connect(lambda k: w.edit_element_camera(k))
    w.stage_timeline.other_overlay_clicked.connect(lambda k,oid: w.go_to_overlay(k,oid))
    w.stage_timeline.element_edit.connect(lambda k: w.edit_element(k))
    w.stage_timeline.element_placed.connect(lambda k,start,track: w.place_element(k,start,track))
    w.stage_timeline.element_reset.connect(lambda k: w.reset_element_time(k))
    w.stage_timeline.track_toggled.connect(lambda t,which: w.toggle_track(t,which))
    w.stage_timeline.element_flag.connect(lambda k,which: w.toggle_element_flag(k,which))
    w.stage_timeline.stage_source_edit.connect(w.edit_stage_source)
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
    w.left_handed.toggled.connect(lambda checked: w.sync_hand_sides())
    w.paint_left_handed.toggled.connect(w.refresh)
    w.entrance.currentIndexChanged.connect(w.refresh)
    w.entrance.currentIndexChanged.connect(lambda index: w.update_entrance_controls())
    w.entrance_part.currentIndexChanged.connect(w.refresh)
    w.entrance_part.currentIndexChanged.connect(lambda index: w.update_applicable())
    w.use_color.toggled.connect(lambda checked: w.update_applicable())
    w.preserve_colors.toggled.connect(lambda checked: w.update_applicable())
    w.image_animation.currentIndexChanged.connect(lambda index: w.update_applicable())
    w.erase_mode.currentIndexChanged.connect(lambda index: w.update_applicable())
    def erase_switched(on):
        if on:
            if w.erase_mode.currentText()=='Off':
                w.erase_mode.setCurrentText(getattr(w,'_last_erase',None) or 'Zigzag (follows the shapes)')
            w.section_out.set_expanded(True)
        elif w.erase_mode.currentText()!='Off':
            w._last_erase=w.erase_mode.currentText()
            w.erase_mode.setCurrentText('Off')
    w.erase_on.toggled.connect(erase_switched)
    # Drawing / Move in switches -> the stored "Comes in" (w.entrance).
    def draw_switched(on):
        if on:
            if w.entrance.currentIndex()!=0:
                w._last_entrance=w.entrance.currentText()
                w.entrance.setCurrentIndex(0)
        elif w.entrance.currentIndex()==0:
            w.entrance.setCurrentText(getattr(w,'_last_entrance',None) or 'Fade in')
            w.section_move_in.set_expanded(True)
        w.sync_entrance_switches()
    w.draw_on.toggled.connect(draw_switched)
    w.move_in_on.toggled.connect(lambda on: w.draw_on.setChecked(not on))
    # Move-in time is the element's animation time (the same value as Draw time).
    def same_time(src,dst):
        if abs(dst.value()-src.value())>1e-9:
            dst.setValue(src.value())
    w.move_time.valueChanged.connect(lambda v: same_time(w.move_time,w.duration))
    w.duration.valueChanged.connect(lambda v: same_time(w.duration,w.move_time))
    w.move_time.setValue(w.duration.value())
    w.move_hand.toggled.connect(w.refresh)
    for widget in (w.move_hand_size,w.move_hand_gx,w.move_hand_gy):
        widget.valueChanged.connect(w.schedule_refresh)
    w.pause_after.valueChanged.connect(w.refresh)
    w.res.currentIndexChanged.connect(w.refresh)
    w.use_color.toggled.connect(w.refresh)
    w.color_fade.valueChanged.connect(w.refresh)
    w.color_hold.valueChanged.connect(w.refresh)
    w.reveal_mode.currentIndexChanged.connect(w.refresh)
    w.reveal_mode.currentIndexChanged.connect(lambda index: w.update_painter_parts())
    for field in (w.blend_mode,w.artwork_opacity,w.paper_cleanup,
                  w.paper_tolerance,w.paper_softness):
        if isinstance(field,QComboBox):
            field.currentIndexChanged.connect(w.refresh)
        elif isinstance(field,QCheckBox):
            field.toggled.connect(w.refresh)
        else:
            # Opacity / tolerance / softness are dragged with sliders: redraw at
            # most every 40 ms instead of once per slider step.
            field.valueChanged.connect(w.schedule_refresh)
    w.brush_width.valueChanged.connect(w.schedule_brush_refresh)
    w.show_paint_hand.toggled.connect(w.refresh)
    w.sound_on.toggled.connect(lambda checked: (w.update_transport_icons(), w.sync_preview_sound()))
    w.paint_hand.activated.connect(lambda index: w.paint_hand_changed())
    w.paint_hand_size.valueChanged.connect(w.refresh)
    w.update_paint_hand_label()          # Size shows only for a different painting hand
    w.update_move_hand_label()
    w.update_painter_parts()
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
    w.text.textChanged.connect(lambda: w.update_element_panels())
    w.fps.valueChanged.connect(w.sync_workspace)
    w.webm.toggled.connect(w.sync_workspace)
    w.mov.toggled.connect(w.sync_workspace)
    w.mp4.toggled.connect(w.sync_workspace)
    for name in ('duration','speed','thickness','brush_width','stroke_spacing',
                 'image_duration','color_fade','color_hold','fps','res','order'):
        getattr(w,name).setAccessibleName(name.replace('_',' '))
    w.stage_timeline.setAccessibleName('Animation timeline: click to scrub; double-click Draw or Paint to edit source; Ctrl+Shift+D or P edits selected source')
    fit_to_width(asset,stacked=True)       # labels above fields in the narrow column
    fit_to_width(source_page,stacked=False)
    for content in (animation,hand,output,sound,music,camera_page,ai_page):
        fit_to_width(content,stacked=False)
        for form in content.findChildren(QFormLayout):
            form.setVerticalSpacing(5)
    # After fit_to_width (which sets checkbox policies): nothing may widen a page.
    for content in (asset,source_page,animation,hand,output,sound,music,camera_page,ai_page):
        tidy_side_page(content)
    # Image, Hand and Sound line up like Animation: one label column per page.
    align_forms(source_page,88)
    align_forms(hand,88)
    # Buttons sharing a row may shrink (text clips) rather than widen the page.
    for button in (w.find_tip_button,w.pick_tip_button):
        button.setMinimumWidth(0)
    for button in hand.findChildren(QPushButton):
        if button.text() in ('My PNG…','Library…','Find','Click to set…'):
            policy=button.sizePolicy();policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            button.setSizePolicy(policy);button.setMinimumWidth(0)
    align_forms(sound,64)
    # QFormLayout.WrapLongRows can change the geometry of ALL animation
    # controls when image-specific rows are shown/hidden. In particular it
    # may grow the scroll content beyond its viewport and clip the right-hand
    # spinbox buttons. A bounded label column gives each field stable space
    # at the minimum 270px Inspector width, regardless of the selected element.
    for form in animation.findChildren(QFormLayout):
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        for index in range(form.rowCount()):
            item=form.itemAt(index,QFormLayout.ItemRole.LabelRole)
            heading=item.widget() if item else None
            if isinstance(heading,QLabel):
                heading.setWordWrap(True)
                heading.setMaximumWidth(106)
                heading.setSizePolicy(QSizePolicy.Policy.Maximum,
                                      QSizePolicy.Policy.Preferred)
    # Only the side-by-side Position X/Y spinboxes need to disregard their
    # *preferred* native width. With a 270px Inspector and vertical scrollbar,
    # both spinbox minimumSizeHints together still widened the scroll content
    # (269px for a 262px viewport on Qt/Linux). Keep explicit 84px minima so
    # the text and increment/decrement arrows remain functional. This must
    # come after fit_to_width(), which normally resets spinbox size policies.
    # Position X and Y have their own rows now (experimental.81): they fill the
    # row like every other field, keeping the explicit 84px minimum.
    for field in (w.picture_x,w.picture_y):
        field.setMinimumWidth(0)               # exp.111: compact, sized below
    # Ink on the page / Colour / Light: each slider row (slider, number, reset) is too wide
    # to sit beside its label in the narrowest Image panel (exp.100: 287 px for 260).
    # The label goes above the row, and the number box is a little narrower.
    from PySide6.QtWidgets import QAbstractSpinBox as _Spin
    for section in (w.section_ink,w.section_look_colour,w.section_look_light):
        for form in section.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            for index in range(form.rowCount()):
                item=form.itemAt(index,QFormLayout.ItemRole.LabelRole)
                heading=item.widget() if item else None
                if isinstance(heading,QLabel):
                    heading.setMinimumWidth(0); heading.setMaximumWidth(16777215)
        for spin in section.findChildren(_Spin):
            spin.setMinimumWidth(64)
    # exp.111: the number boxes beside sliders are small (more room for the slider), and
    # plain number boxes do not stretch across the whole panel.
    for spin in w.findChildren(_Spin):
        if spin.property('compact'):
            spin.setMinimumWidth(0); spin.setMaximumWidth(16777215)
            spin.setFixedWidth(compact_width(spin))
            policy=spin.sizePolicy(); policy.setHorizontalPolicy(QSizePolicy.Policy.Fixed)
            spin.setSizePolicy(policy)
        elif spin.window() is w:
            spin.setMaximumWidth(max(spin.minimumWidth(),132))
    # In a QScrollArea with widgetResizable=True, a Preferred-size panel
    # still reports its full QVBoxLayout minimumSizeHint as a hard width.
    # On Linux this stayed at 269px when the Inspector viewport was 262px.
    # Let ONLY the outer Animation page shrink to the actual viewport.
    # The interactive controls retain their explicit safe minimum widths.
    # Do not apply Ignored to comboboxes or individual form controls: that
    # earlier mistake made whole dropdowns disappear.
    policy=animation.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    animation.setSizePolicy(policy)
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
    # Redo: Ctrl+Y and Ctrl+Shift+Z, ONE shortcut per key. On Windows the standard Redo
    # key is Ctrl+Y too; two shortcuts on the same key are "ambiguous" and neither ran.
    w.redo_shortcuts=[]
    seen=set()
    for keys in QKeySequence.keyBindings(QKeySequence.StandardKey.Redo)+[QKeySequence('Ctrl+Y'),
                                                                         QKeySequence('Ctrl+Shift+Z')]:
        text=keys.toString()
        if not text or text in seen: continue
        seen.add(text)
        shortcut=QShortcut(keys,w); shortcut.activated.connect(lambda: w.redo())
        w.redo_shortcuts.append(shortcut)
    # Ctrl+Z / Ctrl+Y in a number box or a list undo the program, not just the typing.
    w.undo_keys=UndoKeys(w)
    QApplication.instance().installEventFilter(w.undo_keys)
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


class PaintModeCombo(QComboBox):
    """The Paint mode list: clicking it opens the bigger picker (paint_mode_dialog)
    instead of a dropdown. The list itself, its order and its items stay the same."""

    def __init__(self, picker=None):
        super().__init__()
        self.picker = picker
        # A button that opens the picker: no dropdown arrow.
        self.setObjectName('paintModeButton')
        self.setStyleSheet('QComboBox#paintModeButton::drop-down { width: 0px; border: none; }'
                           'QComboBox#paintModeButton::down-arrow { image: none; width: 0px; }')
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def showPopup(self):
        if self.picker is None:
            return super().showPopup()
        self.picker()


def side_toggle(box, tip):
    """Two small buttons, Right | Left, kept in step with the check box `box` (checked = left)."""
    from PySide6.QtWidgets import QButtonGroup
    holder=QWidget();holder.setMinimumWidth(0);holder.setObjectName('sideToggle')
    row=QHBoxLayout(holder);row.setContentsMargins(0,0,0,0);row.setSpacing(0)
    group=QButtonGroup(holder);group.setExclusive(True)
    buttons=[]
    for text,left in (('Right',False),('Left',True)):
        b=QPushButton(text);b.setCheckable(True);b.setToolTip(tip)
        b.setMinimumWidth(0);b.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        b.setObjectName('sideToggleLeft' if left else 'sideToggleRight')
        b.clicked.connect(lambda checked=False,left=left: box.setChecked(left))
        group.addButton(b);row.addWidget(b,1);buttons.append(b)
    def sync(*_):
        left=box.isChecked()
        for b,is_left in zip(buttons,(False,True)):
            b.blockSignals(True);b.setChecked(left==is_left);b.blockSignals(False)
    box.toggled.connect(sync)
    holder.sync=sync;holder.buttons=buttons
    sync()
    return holder


class UndoKeys(QObject):
    """Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z go to the program's undo even when a number box,
    a slider, a list or a dropdown has the keyboard. Only real text fields (writing a
    title, the handwriting text) keep their own typing undo."""

    def __init__(self, window):
        super().__init__(window)
        self.main = window

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeySequence
        if event.type() not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        # QWidget.window(obj), not obj.window(): some widgets keep the main window in an
        # attribute called `window`, which hides the method (a crash on Ctrl+Z there).
        if not isinstance(obj, QWidget) or QWidget.window(obj) is not self.main:
            return False
        undo = event.matches(QKeySequence.StandardKey.Undo)
        redo = (event.matches(QKeySequence.StandardKey.Redo) or
                (event.key() == Qt.Key.Key_Y and event.modifiers() == Qt.KeyboardModifier.ControlModifier) or
                (event.key() == Qt.Key.Key_Z and event.modifiers() ==
                 (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)))
        if not (undo or redo):
            return False
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit
        box = obj
        if isinstance(obj, QLineEdit) and isinstance(obj.parent(), (QAbstractSpinBox, QComboBox)):
            box = obj.parent()                           # the text inside a number box
        if isinstance(box, (QPlainTextEdit, QTextEdit)) or (isinstance(box, QLineEdit) and box is obj):
            return False                                 # a real text field: its own typing undo
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()                               # the key comes to us as a key press
            return True
        (self.main.undo if undo else self.main.redo)()
        return True


def build_look_sections(w):
    """Image panel: Ink on the page, Colour and Light (picture_look), Filmora-style:
    a section per group with an on/off switch, and slider rows with a reset button."""
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QToolButton
    import picture_look
    from ui_icons import icon
    from ui_sections import Section
    w.look_widgets={}

    def switch(key,text,tip):
        box=QCheckBox(text);box.hide();box.setToolTip(tip)    # its switch is on the section header
        box.setChecked(bool(picture_look.DEFAULTS[key]))
        setattr(w,key,box);w.look_widgets[key]=box
        return box

    def row(form,key,text,low=-100,high=100,suffix='',tip=''):
        default=float(picture_look.DEFAULTS[key])
        spin=w.number(low,high,default,1);spin.setDecimals(0)
        if suffix: spin.setSuffix(suffix)
        if tip: spin.setToolTip(tip)
        setattr(w,key,spin);w.look_widgets[key]=spin
        slider=linked_slider(spin,low,high)
        reset=QToolButton();reset.setObjectName('panelClose')
        reset.setIcon(icon('reset',RAIL_ICON,RAIL_ACTIVE));reset.setIconSize(QSize(14,14))
        reset.setToolTip(f'Back to {default:g}')
        reset.clicked.connect(lambda checked=False: spin.setValue(default))
        box=QWidget();box.setMinimumWidth(0)
        line=QHBoxLayout(box);line.setContentsMargins(0,0,0,0);line.setSpacing(6)
        line.addWidget(slider,1);line.addWidget(spin);line.addWidget(reset)
        form.addRow(text,box)
        return spin

    # Ink on the page: the paper of the picture becomes see-through, its lines ink.
    ink_on=switch('ink_on','Ink on the page','The picture becomes ink on the page: its own paper becomes '
                  'see-through, so no square shows; the page shows through the lines.')
    w.section_ink=Section('Ink on the page',switch=ink_on,
                          tip='Make the picture look printed on the page (no square around it).')
    w.source_look_slot.addWidget(w.section_ink)
    f=form_layout();w.section_ink.body.addLayout(f)
    w.ink_edges=QComboBox();w.ink_edges.addItems(list(picture_look.EDGES))
    w.ink_edges.setToolTip('Soft edges: the border fades out. Oval fade: everything around the middle fades, '
                           'like an old book illustration.')
    w.look_widgets['ink_edges']=w.ink_edges
    f.addRow('Edges',w.ink_edges)
    row(f,'ink_edge_size','Edge fade',0,60,'%','How far the fading reaches in from the border.')
    row(f,'ink_removal','Paper removal',0,100,'','More: more of the picture\'s own paper tone becomes '
        'see-through (a grey background disappears too).')
    row(f,'ink_strength','Ink strength',10,200,'%','How dark the ink is.')
    w.ink_colour=QComboBox();w.ink_colour.addItems(list(picture_look.INK_COLOURS))
    w.ink_colour.setToolTip('The colour of the ink. "The picture\'s own colours" keeps its colours, as ink.')
    w.look_widgets['ink_colour']=w.ink_colour
    f.addRow('Ink colour',w.ink_colour)
    # Colour, like Filmora.
    colour_on=switch('look_colour_on','Colour','Temperature, tint and saturation of the picture.')
    w.section_look_colour=Section('Colour',switch=colour_on)
    w.source_look_slot.addWidget(w.section_look_colour)
    f=form_layout();w.section_look_colour.body.addLayout(f)
    for key,text in picture_look.COLOUR:
        row(f,key,text)
    # Light, like Filmora.
    light_on=switch('look_light_on','Light','Exposure, brightness, contrast, highlights, shadows, whites and blacks.')
    w.section_look_light=Section('Light',switch=light_on)
    w.source_look_slot.addWidget(w.section_look_light)
    f=form_layout();w.section_look_light.body.addLayout(f)
    for key,text in picture_look.LIGHT:
        row(f,key,text)
    # Any change: the picture again (sliders at most every 40 ms).
    # No "Preparing brush route" while adjusting (exp.100): the finished picture shows at
    # once and the brushes are planned on Play, a scrub or Pre-render.
    for key,widget in w.look_widgets.items():
        if isinstance(widget,QCheckBox):
            widget.toggled.connect(lambda checked: w.look_changed())
        elif isinstance(widget,QComboBox):
            widget.currentIndexChanged.connect(lambda index: w.look_changed())
        else:
            widget.valueChanged.connect(lambda value: w.look_changed(slider=True))
    # Turning a group on opens it.
    for section in (w.section_ink,w.section_look_colour,w.section_look_light):
        section.switch.source.toggled.connect(lambda on,sec=section: on and sec.set_expanded(True))
