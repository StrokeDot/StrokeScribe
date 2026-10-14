"""Original StrokeScribe Studio workspace.

An editor-style layout (source/paths, central monitor, inspector and timeline).
Only the UI is reorganized: rendering and export algorithms stay in their
existing modules. No third-party product assets or lookalike trade dress.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QScrollArea, QSplitter, QVBoxLayout,
    QHBoxLayout, QFormLayout, QPushButton, QLabel, QComboBox, QCheckBox,
    QSpinBox, QListWidget, QPlainTextEdit, QSlider, QTabWidget,
    QProgressBar, QSizePolicy,
)
from version import APP_VERSION, DISPLAY_NAME


STUDIO_STYLE = """
QWidget { background: #12171F; color: #E7ECF5; font-size: 12px; }
QMainWindow { background: #0E1218; }
QFrame#topBar { background: #1A2230; border-bottom: 1px solid #334152; }
QFrame#assetPanel, QFrame#inspectorPanel, QFrame#monitorPanel, QFrame#timelinePanel {
    background: #1A222D; border: 1px solid #344153; border-radius: 9px;
}
QFrame#monitorPanel { background: #101721; }
QLabel#micro { color: #91A3B8; font-size: 10px; font-weight: 700; }
QLabel#section { color: #9DB1C9; font-size: 11px; font-weight: 700; }
QLabel#brand { color: #F6F8FC; font-size: 20px; font-weight: 800; }
QLabel#subtitle { color: #92A8C1; font-size: 11px; }
QLabel#timeCode { color: #E8F4FF; font-size: 15px; font-weight: 700; }
QLabel#status { color: #B0C0D2; font-size: 11px; }
QLabel#note { color: #B6C4D4; }
QPushButton {
    background: #263447; border: 1px solid #40536A; border-radius: 6px;
    padding: 8px 11px; font-weight: 600;
}
QPushButton:hover { background: #334764; border-color: #6587AD; }
QPushButton:pressed { background: #243A56; }
QPushButton:disabled { background: #1B2330; color: #64758A; border-color: #2D3947; }
QPushButton#primary { background: #387BDD; color: #FFFFFF; border-color: #508DEA; }
QPushButton#primary:hover { background: #5693ED; }
QPushButton#subtle { background: transparent; border: 1px solid #3A4859; }
QComboBox, QDoubleSpinBox, QSpinBox, QPlainTextEdit, QListWidget {
    background: #101722; color: #EDF3FA; border: 1px solid #3A4A5E;
    border-radius: 6px; padding: 5px 7px; selection-background-color: #3A77BA;
}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover { border-color: #6999CF; }
QComboBox QAbstractItemView { background: #1C2735; color: #EDF3FA; selection-background-color: #385C85; }
QFormLayout QLabel { color: #BED0E0; }
QCheckBox { spacing: 9px; padding: 5px 0px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox::indicator:checked { background: #4189F2; border: 1px solid #74ABF8; border-radius: 3px; }
QCheckBox::indicator:unchecked { background: #101722; border: 1px solid #66788F; border-radius: 3px; }
QSlider::groove:horizontal { background: #344457; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #5296F4; border-radius: 2px; }
QSlider::handle:horizontal { background: #EAF4FF; width: 13px; margin: -5px 0; border-radius: 6px; }
QTabWidget::pane { border: 1px solid #304052; border-radius: 5px; background: #1A222D; }
QTabBar::tab { background: #222E3D; color: #9DADC1; padding: 9px 12px;
    border: 1px solid #304052; border-bottom: 0px; }
QTabBar::tab:selected { background: #344A66; color: #FFFFFF; }
QScrollArea { border: 0px; background: transparent; }
QScrollBar:vertical { width: 10px; background: #1A222D; }
QScrollBar::handle:vertical { background: #43566E; border-radius: 4px; min-height: 28px; }
QProgressBar { border: 1px solid #405067; border-radius: 5px;
    background: #101722; color: #E7ECF5; text-align: center; height: 15px; }
QProgressBar::chunk { background: #5798ED; border-radius: 4px; }
QSplitter::handle { background: #101721; }
"""


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
    scroll.setWidget(content)
    return scroll


def form_layout():
    form=QFormLayout()
    form.setContentsMargins(0,8,0,8)
    form.setSpacing(9)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    return form


class StageTimeline(QFrame):
    """Interactive time overview, with separate draw/paint/hold phases."""
    def __init__(self, slider, parent=None):
        super().__init__(parent)
        self.slider=slider
        self.draw_seconds=4.
        self.paint_seconds=0.
        self.hold_seconds=0.
        self.progress=0.
        self.setMinimumHeight(64)
        self.setMaximumHeight(75)
        self.setToolTip('Click a stage to move the playback cursor.')
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def update_state(self, draw, paint, hold, progress):
        self.draw_seconds=max(.001,float(draw))
        self.paint_seconds=max(0.,float(paint))
        self.hold_seconds=max(0.,float(hold))
        self.progress=max(0.,min(1.,float(progress)))
        self.update()

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left=10.; width=max(1.,self.width()-20.)
        top=14.; height=33.
        total=max(.001,self.draw_seconds+self.paint_seconds+self.hold_seconds)
        stages=[('DRAW',self.draw_seconds,'#4E88DB'),
                ('PAINT',self.paint_seconds,'#30A898'),
                ('HOLD',self.hold_seconds,'#CBA15C')]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#101722'))
        p.drawRoundedRect(QRectF(left,top,width,height),6,6)
        x=left
        for name,secs,color in stages:
            if secs<=0:
                continue
            part=width*secs/total
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x+1,top+2,max(1,part-2),height-4),4,4)
            if part>=50:
                p.setPen(QColor('#FFFFFF'))
                p.setFont(QFont('Segoe UI',9,QFont.Weight.DemiBold))
                p.drawText(QRectF(x,top,part,height),
                    Qt.AlignmentFlag.AlignCenter, name)
                p.setPen(Qt.PenStyle.NoPen)
            x+=part
        play_x=left+width*self.progress
        p.setPen(QPen(QColor('#F7F9FF'),2))
        p.drawLine(QPointF(play_x,top-5),QPointF(play_x,top+height+7))
        p.setPen(QColor('#A7B9CC'))
        p.setFont(QFont('Segoe UI',8))
        p.drawText(QRectF(left,50,width,14),
                   Qt.AlignmentFlag.AlignLeft,'00:00')
        p.drawText(QRectF(left,50,width,14),
                   Qt.AlignmentFlag.AlignRight,f'{total:.1f} s')
        p.end()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            fraction=max(0.,min(1.,(event.position().x()-10)/max(1,self.width()-20)))
            self.slider.setValue(round(1000*fraction))
            event.accept()
            return
        super().mousePressEvent(event)


def build_workspace(w, Canvas, BRAND_ICON):
    """Construct UI fields expected by Window methods without altering logic."""
    w.setWindowTitle(f'{DISPLAY_NAME}  •  Studio')
    w.resize(1490,890)
    w.setMinimumSize(1040,690)
    QApplication.instance().setStyleSheet(STUDIO_STYLE)
    root=QWidget()
    w.setCentralWidget(root)
    outer=QVBoxLayout(root)
    outer.setContentsMargins(10,10,10,10)
    outer.setSpacing(9)

    # Header: no third-party brand graphics.
    bar=QFrame(); bar.setObjectName('topBar')
    bar_l=QHBoxLayout(bar); bar_l.setContentsMargins(14,8,14,8)
    if BRAND_ICON.is_file():
        icon=QLabel()
        icon.setPixmap(QPixmap(str(BRAND_ICON)).scaled(
            43,43,Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        bar_l.addWidget(icon)
        w.setWindowIcon(QIcon(str(BRAND_ICON)))
    title=QVBoxLayout();title.setSpacing(0)
    title.addWidget(label('STROKESCRIBE','brand'))
    title.addWidget(label(f'Animation studio  •  Prototype v{APP_VERSION}','subtitle'))
    bar_l.addLayout(title)
    bar_l.addStretch(1)
    bar_l.addWidget(label('LOCAL PROJECT  /  SVG + IMAGE','micro'))
    w.version_button=QPushButton(f'About  •  v{APP_VERSION}')
    w.version_button.setObjectName('subtle')
    w.version_button.clicked.connect(w.show_version_info)
    bar_l.addWidget(w.version_button)
    quick_export=QPushButton('Export Animation')
    quick_export.setObjectName('primary')
    quick_export.clicked.connect(w.save)
    bar_l.addWidget(quick_export)
    w.quick_export=quick_export
    outer.addWidget(bar)

    split=QSplitter(Qt.Orientation.Horizontal)
    split.setChildrenCollapsible(False)
    outer.addWidget(split,1)

    # Source and stroke order (left).
    asset=QFrame();asset.setObjectName('assetPanel')
    asset.setMinimumWidth(215)
    asset_l=QVBoxLayout(asset);asset_l.setContentsMargins(11,13,11,12)
    asset_l.setSpacing(9)
    asset_l.addWidget(label('01  /  SOURCE & PATHS','micro'))
    asset_l.addWidget(caption('Import artwork or generate single-line lettering.'))
    w.source_type=QComboBox(); w.source_type.addItems(['SVG source','Image source'])
    asset_l.addWidget(w.source_type)
    w.import_button=QPushButton('Import SVG…')
    w.import_button.setObjectName('primary')
    w.import_button.clicked.connect(w.load)
    asset_l.addWidget(w.import_button)
    w.image_controls=QWidget()
    image_form=form_layout();w.image_controls.setLayout(image_form)
    w.image_mode=QComboBox();w.image_mode.addItems([
        'Auto trace','Stroke reconstruction','AI redraw (not available)'])
    w.image_mode.model().item(2).setEnabled(False)
    image_form.addRow('Reconstruction',w.image_mode)
    w.image_detail=QComboBox();w.image_detail.addItems(['Low','Medium','High'])
    w.image_detail.setCurrentIndex(1)
    image_form.addRow('Detail',w.image_detail)
    w.preserve_colors=QCheckBox('Preserve original colors')
    w.preserve_colors.setChecked(True)
    image_form.addRow(w.preserve_colors)
    w.image_duration=w.number(.2,120,8,.5)
    image_form.addRow('Paint time (s)',w.image_duration)
    w.rebuild_button=QPushButton('Apply image settings')
    w.rebuild_button.clicked.connect(w.rebuild_image)
    image_form.addRow(w.rebuild_button)
    w.image_controls.hide()
    asset_l.addWidget(w.image_controls)
    asset_l.addWidget(label('TEXT / LETTERING'))
    w.text=QPlainTextEdit('Hello world!')
    w.text.setMaximumHeight(74)
    asset_l.addWidget(w.text)
    lettering=QPushButton('Generate lettering')
    lettering.clicked.connect(w.letter)
    asset_l.addWidget(lettering)
    asset_l.addWidget(label('STROKE ORDER'))
    asset_l.addWidget(caption('Select a path to change the drawing order.'))
    w.order=QListWidget()
    w.order.setMinimumHeight(155)
    asset_l.addWidget(w.order,1)
    reorder=QHBoxLayout()
    for text,direction in [('Move up',-1),('Move down',1)]:
        button=QPushButton(text)
        button.clicked.connect(lambda checked=False,d=direction:w.move(d))
        reorder.addWidget(button)
    asset_l.addLayout(reorder)
    w.note=caption('Ready.')
    asset_l.addWidget(w.note)
    split.addWidget(scroll_view(asset))

    # Large, dedicated visual monitor (center).
    monitor=QFrame();monitor.setObjectName('monitorPanel')
    monitor.setMinimumWidth(390)
    monitor_l=QVBoxLayout(monitor);monitor_l.setContentsMargins(10,10,10,10)
    monitor_l.setSpacing(8)
    top=QHBoxLayout()
    top.addWidget(label('02  /  PREVIEW MONITOR','micro'))
    top.addStretch(1)
    top.addWidget(label('TRANSPARENT CANVAS','micro'))
    monitor_l.addLayout(top)
    w.canvas=Canvas()
    w.canvas.setMinimumSize(360,250)
    monitor_l.addWidget(w.canvas,1)
    monitor_l.addWidget(caption('Checkerboard = transparent  •  Scrub on the timeline below'))
    split.addWidget(monitor)

    # Inspector settings grouped by task (right).
    inspector=QFrame();inspector.setObjectName('inspectorPanel')
    inspector.setMinimumWidth(250)
    inspector_l=QVBoxLayout(inspector);inspector_l.setContentsMargins(10,11,10,10)
    inspector_l.addWidget(label('03  /  INSPECTOR','micro'))
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
    animation_l.addWidget(label('COLOR & PAINTING'))
    w.load_color_button=QPushButton('Load matching colored PNG…')
    w.load_color_button.clicked.connect(w.load_color)
    animation_l.addWidget(w.load_color_button)
    w.use_color=QCheckBox('Reveal original artwork after drawing')
    w.use_color.setEnabled(False)
    animation_l.addWidget(w.use_color)
    w.color_note=caption('No original PNG loaded')
    animation_l.addWidget(w.color_note)
    a2=form_layout();animation_l.addLayout(a2)
    w.reveal_mode=QComboBox()
    w.reveal_mode.addItems(['Fade','Brush painting','Stroke-guided painting',
                            'Clean contour painting','Adaptive Hand Painting'])
    a2.addRow('Paint mode',w.reveal_mode)
    w.color_fade=w.number(0,20,.4,.1);a2.addRow('Paint time (s)',w.color_fade)
    w.brush_width=w.number(.02,.5,.14,.02);a2.addRow('Brush width',w.brush_width)
    w.stroke_spacing=w.number(.2,.9,.55,.05)
    w.stroke_spacing.setToolTip('Lower values add more overlap between brush strokes.')
    a2.addRow('Stroke spacing',w.stroke_spacing)
    w.color_hold=w.number(0,30,.6,.1);a2.addRow('Hold (s)',w.color_hold)
    animation_l.addStretch(1)
    tabs.addTab(scroll_view(animation),'Animation')

    hand=QWidget();hand_l=QVBoxLayout(hand)
    hand_l.setContentsMargins(9,12,9,8);hand_l.setSpacing(12)
    hand_l.addWidget(label('HAND & PEN'))
    load_hand=QPushButton('Load transparent hand PNG…')
    load_hand.clicked.connect(w.loadhand)
    hand_l.addWidget(load_hand)
    w.showhand=QCheckBox('Show hand while drawing')
    w.showhand.setChecked(True);hand_l.addWidget(w.showhand)
    w.show_paint_hand=QCheckBox('Show hand while painting')
    w.show_paint_hand.setChecked(True);hand_l.addWidget(w.show_paint_hand)
    hand_l.addWidget(caption('Calibrate the pencil tip to your hand PNG for accurate tracing.'))
    h=form_layout();hand_l.addLayout(h)
    w.handsize=w.number(.02,.8,.18,.01);h.addRow('Hand scale',w.handsize)
    w.ax=w.number(0,1,.1,.01);h.addRow('Pen tip X',w.ax)
    w.ay=w.number(0,1,.1,.01);h.addRow('Pen tip Y',w.ay)
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
    w.webm=QCheckBox('Compact WebM / VP9 + alpha (test in Filmora)')
    output_l.addWidget(w.webm)
    w.webm_quality=QSpinBox()
    w.webm_quality.setRange(18,42);w.webm_quality.setValue(28)
    w.webm_quality.setToolTip('Lower means higher quality and generally larger files.')
    e2=form_layout();e2.addRow('WebM quality',w.webm_quality)
    output_l.addLayout(e2)
    w.mov=QCheckBox('ProRes 4444 MOV (larger)')
    output_l.addWidget(w.mov)
    w.keep_png=QCheckBox('Keep generated PNG frames')
    w.keep_png.setChecked(False)
    w.keep_png.setToolTip('If video encoding succeeds, frame PNGs can be removed.')
    output_l.addWidget(w.keep_png)
    output_l.addWidget(caption('If neither video format is selected, all transparent PNG frames are kept.'))
    w.export=QPushButton('Export transparent animation…')
    w.export.setObjectName('primary');w.export.clicked.connect(w.save)
    output_l.addWidget(w.export)
    w.cancel=QPushButton('Cancel export')
    w.cancel.setEnabled(False);w.cancel.clicked.connect(w.cancel_export)
    output_l.addWidget(w.cancel)
    w.progress=QProgressBar()
    output_l.addWidget(w.progress)
    w.status=label('Local CPU rendering • transparent output','status')
    w.status.setWordWrap(True)
    output_l.addWidget(w.status)
    output_l.addStretch(1)
    tabs.addTab(scroll_view(output),'Export')
    split.addWidget(inspector)
    split.setStretchFactor(0,0)
    split.setStretchFactor(1,1)
    split.setStretchFactor(2,0)
    split.setSizes([274,870,326])

    # Time-based workflow remains visible whichever Inspector tab is open.
    timeline=QFrame();timeline.setObjectName('timelinePanel')
    line_l=QVBoxLayout(timeline)
    line_l.setContentsMargins(14,10,14,9);line_l.setSpacing(6)
    header=QHBoxLayout()
    header.addWidget(label('04  /  ANIMATION TIMELINE','micro'))
    header.addStretch(1)
    w.clock=label('0.00 / 0.00 s','timeCode')
    header.addWidget(w.clock)
    line_l.addLayout(header)
    controls=QHBoxLayout();controls.setSpacing(10)
    w.play=QPushButton('Play / Pause');w.play.clicked.connect(w.toggle)
    controls.addWidget(w.play)
    restart=QPushButton('Restart');restart.clicked.connect(w.restart)
    controls.addWidget(restart)
    w.slider=QSlider(Qt.Orientation.Horizontal)
    w.slider.setRange(0,1000);w.slider.valueChanged.connect(w.scrub)
    controls.addWidget(w.slider,1)
    line_l.addLayout(controls)
    w.stage_timeline=StageTimeline(w.slider)
    line_l.addWidget(w.stage_timeline)
    outer.addWidget(timeline)

    # Retain the existing preview/export signal wiring.
    for widget in (w.duration,w.speed,w.thickness,w.handsize,w.ax,w.ay):
        widget.valueChanged.connect(w.refresh)
    w.showhand.toggled.connect(w.refresh)
    w.res.currentIndexChanged.connect(w.refresh)
    w.use_color.toggled.connect(w.refresh)
    w.color_fade.valueChanged.connect(w.refresh)
    w.color_hold.valueChanged.connect(w.refresh)
    w.reveal_mode.currentIndexChanged.connect(w.refresh)
    w.brush_width.valueChanged.connect(w.refresh)
    w.show_paint_hand.toggled.connect(w.refresh)
    w.stroke_spacing.valueChanged.connect(w.refresh)
    w.preserve_colors.toggled.connect(w.refresh)
    w.image_duration.valueChanged.connect(w.refresh)
    w.source_type.currentIndexChanged.connect(w.change_source)
