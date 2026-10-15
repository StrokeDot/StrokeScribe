"""Original StrokeScribe Studio workspace.

An editor-style layout (source/paths, central monitor, inspector and timeline).
Only the UI is reorganized: rendering and export algorithms stay in their
existing modules. No third-party product assets or lookalike trade dress.
"""
from __future__ import annotations

from pathlib import Path
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
QFrame#topBar { background: #151D29; border-bottom: 1px solid #334152; }
QLabel#brandWordmark { background: transparent; }
QFrame#assetPanel, QFrame#inspectorPanel, QFrame#monitorPanel, QFrame#timelinePanel {
    background: #1A222D; border: 1px solid #344153; border-radius: 9px;
}
QFrame#monitorPanel { background: #101721; }
QLabel { background: transparent; }
QPushButton:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QListWidget:focus { border: 1px solid #78AEFF; }
QListWidget::item { padding: 6px; border-bottom: 1px solid #233144; }
QListWidget::item:selected { background: #244A78; color: #FFFFFF; }
QToolTip { background: #25374E; color: #FFFFFF; border: 1px solid #648AB8; padding: 6px; }
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
    """Interactive time overview, with separate draw/paint/hold phases."""
    def __init__(self, slider, parent=None):
        super().__init__(parent)
        self.slider=slider
        self.draw_seconds=4.
        self.paint_seconds=0.
        self.hold_seconds=0.
        self.progress=0.
        self.setMinimumHeight(82)
        self.setMaximumHeight(90)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip('Click a stage to move the playback cursor.')
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def update_state(self, draw, paint, hold, progress):
        self.draw_seconds=max(0.,float(draw))
        self.paint_seconds=max(0.,float(paint))
        self.hold_seconds=max(0.,float(hold))
        self.progress=max(0.,min(1.,float(progress)))
        self.update()

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left=10.; width=max(1.,self.width()-20.)
        top=29.; height=33.
        total=self.draw_seconds+self.paint_seconds+self.hold_seconds
        if total<=0:
            p.setPen(QColor('#91A3B8'))
            p.drawText(QRectF(left,top,width,height),
                Qt.AlignmentFlag.AlignCenter, 'IMPORT ARTWORK TO BEGIN')
            p.end()
            return
        # A time ruler shares the same scale as the animation phases.
        p.setPen(QColor('#91A3B8'))
        ticks=max(2,min(10,int(width/110)))
        for i in range(ticks+1):
            x=left+width*i/ticks
            p.drawLine(QPointF(x,23),QPointF(x,27))
            align=Qt.AlignmentFlag.AlignCenter
            text_x=max(left,min(x-30,left+width-60))
            p.drawText(QRectF(text_x,3,60,16),align,f'{total*i/ticks:.1f}s')
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
        p.drawText(QRectF(left,68,width,14),
                   Qt.AlignmentFlag.AlignLeft,'00:00')
        p.drawText(QRectF(left,50,width,14),
                   Qt.AlignmentFlag.AlignRight,f'{total:.1f} s')
        p.end()

    def mousePressEvent(self,event):
        if (event.button()==Qt.MouseButton.LeftButton
                and self.draw_seconds+self.paint_seconds+self.hold_seconds>0):
            fraction=max(0.,min(1.,(event.position().x()-10)/max(1,self.width()-20)))
            self.slider.setValue(round(1000*fraction))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.draw_seconds+self.paint_seconds+self.hold_seconds>0:
            fraction=max(0.,min(1.,(event.position().x()-10)/max(1,self.width()-20)))
            self.slider.setValue(round(1000*fraction))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right):
            self.slider.setValue(self.slider.value()+(-10 if event.key()==Qt.Key.Key_Left else 10))
        elif event.key()==Qt.Key.Key_Home:
            self.slider.setValue(0)
        elif event.key()==Qt.Key.Key_End:
            self.slider.setValue(1000)
        else:
            super().keyPressEvent(event)


def spin_box_style(assets):
    """Large, clearly drawn up/down buttons for every number box.

    Styling the spin boxes without styling their buttons left Qt drawing tiny,
    nearly invisible arrows that were hard to click.
    """
    def url(name):
        return (Path(assets) / f'{name}.png').as_posix()
    return f"""
QAbstractSpinBox {{ padding-right: 28px; min-height: 22px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 24px; background: #1E2A39;
    border-left: 1px solid #3A4A5E; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right;
    border-bottom: 1px solid #3A4A5E; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right;
    border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #2C3E55; }}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{ background: #3A77BA; }}
QAbstractSpinBox::up-arrow {{ image: url("{url('spin_up')}"); width: 10px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url("{url('spin_down')}"); width: 10px; height: 6px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url("{url('spin_up_disabled')}"); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url("{url('spin_down_disabled')}"); }}
"""


def build_workspace(w, Canvas, BRAND_ICON):
    """Construct UI fields expected by Window methods without altering logic."""
    w.setWindowTitle(f'{DISPLAY_NAME}  •  Studio')
    w.resize(1490,890)
    w.setMinimumSize(1040,690)
    w.setStyleSheet(STUDIO_STYLE + spin_box_style(Path(BRAND_ICON).parent))
    root=QWidget()
    w.setCentralWidget(root)
    outer=QVBoxLayout(root)
    outer.setContentsMargins(10,10,10,10)
    outer.setSpacing(9)

    # Original compact StrokeScribe branding, drawn using native Qt widgets.
    # The three brand dots are decoration, NOT fake OS close/minimize buttons.
    bar=QFrame(); bar.setObjectName('topBar')
    bar_l=QHBoxLayout(bar); bar_l.setContentsMargins(14,8,14,8)
    bar_l.setSpacing(9)
    dots=QWidget()
    dots_l=QHBoxLayout(dots);dots_l.setContentsMargins(0,0,3,0);dots_l.setSpacing(6)
    for color in ('#F56B76','#EFBF4D','#53C993'):
        dot=QLabel()
        dot.setFixedSize(11,11)
        dot.setStyleSheet('background-color: '+color+'; border-radius: 5px;')
        dots_l.addWidget(dot)
    dots.setToolTip('StrokeScribe brand colors; window controls remain in the Windows title bar.')
    bar_l.addWidget(dots)
    if BRAND_ICON.is_file():
        w.setWindowIcon(QIcon(str(BRAND_ICON)))
        QApplication.instance().setWindowIcon(QIcon(str(BRAND_ICON)))
    title=QHBoxLayout();title.setSpacing(10)
    w.brand_wordmark=QLabel(
        '<span style="color:#F6F8FC">Stroke</span>'
        '<span style="color:#58A7FF">Scribe</span>')
    w.brand_wordmark.setObjectName('brandWordmark')
    w.brand_wordmark.setFont(QFont('Segoe UI',17,QFont.Weight.Bold))
    title.addWidget(w.brand_wordmark)
    w.brand_version=label(f'Prototype v{APP_VERSION}','subtitle')
    title.addWidget(w.brand_version)
    bar_l.addLayout(title)
    bar_l.addStretch(1)
    from PySide6.QtWidgets import QToolButton, QMenu
    w.project_menu=QToolButton()
    w.project_menu.setText('▣  Sample drawing  ▾')
    w.project_menu.setToolTip('Current artwork. Choose Import SVG or Import Image to replace it.')
    w.project_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    projects=QMenu(w.project_menu)
    projects.addAction('Import SVG artwork…',w.open_svg_source)
    projects.addAction('Import PNG / JPG artwork…',w.open_image_source)
    w.project_menu.setMenu(projects)
    bar_l.addWidget(w.project_menu)
    w.output_summary=label('1920 × 1080  •  30 fps','micro')
    bar_l.addWidget(w.output_summary)
    w.undo_button=QPushButton('↶')
    w.undo_button.setToolTip('Undo last stroke order change')
    w.undo_button.setObjectName('subtle')
    w.undo_button.setEnabled(False)
    w.undo_button.clicked.connect(w.undo_stroke_order)
    bar_l.addWidget(w.undo_button)
    w.redo_button=QPushButton('↷')
    w.redo_button.setToolTip('Redo last stroke order change')
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
    w.settings_button.setToolTip('Open export settings')
    w.settings_button.setObjectName('subtle')
    w.settings_button.clicked.connect(w.open_export)
    bar_l.addWidget(w.settings_button)
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

    split=QSplitter(Qt.Orientation.Horizontal)
    w.workspace_splitter=split
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
    image_form=form_layout();w.image_controls.setLayout(image_form);w.image_source_form=image_form
    w.image_mode=QComboBox();w.image_mode.addItems([
        'Auto trace','Stroke reconstruction','AI redraw (local model)'])
    image_form.addRow('Method',w.image_mode)
    w.ai_model=QComboBox()
    w.ai_model.setEditable(True)
    w.ai_model.addItems(['qwen3-vl:4b','qwen3-vl:2b','qwen3-vl:8b'])
    w.ai_model.setToolTip('Ollama vision model, running locally on your PC. Requires separate model download.')
    image_form.addRow('Local AI model',w.ai_model)
    w.ai_profile=QComboBox()
    w.ai_profile.addItems(['Fast','Balanced','Quality'])
    w.ai_profile.setCurrentIndex(1)
    w.ai_profile.setToolTip(
        'Balanced: same 640px, eight-object recognition as before; optimized local '
        'contour work and 5-minute model reuse. Fast trades some detail for speed; '
        'Quality analyzes a larger image and may take longer.')
    image_form.addRow('AI processing',w.ai_profile)
    w.ai_note=caption('Balanced recommended: keeps current recognition detail, reduces local work, and caches the Qwen analysis. Models stay on your PC.')
    image_form.addRow(w.ai_note)
    w.image_detail=QComboBox();w.image_detail.addItems(['Low','Medium','High'])
    w.image_detail.setCurrentIndex(1)
    w.image_detail.setToolTip('Medium is recommended. Switching detail after AI analysis reuses the same object recognition and recomputes only local contours.')
    image_form.addRow('Detail',w.image_detail)
    w.preserve_colors=QCheckBox('Preserve original colors')
    w.preserve_colors.setChecked(True)
    image_form.addRow(w.preserve_colors)
    w.image_duration=w.number(.2,120,8,.5)
    # Painting timing belongs in the Animation inspector.
    w.image_duration.setParent(w.image_controls)
    w.rebuild_button=QPushButton('Apply image settings')
    w.rebuild_button.clicked.connect(w.rebuild_image)
    image_form.addRow(w.rebuild_button)
    image_form.setRowVisible(w.ai_model,False)
    image_form.setRowVisible(w.ai_profile,False)
    image_form.setRowVisible(w.ai_note,False)
    w.image_mode.currentIndexChanged.connect(w.update_image_mode)
    w.image_controls.hide()
    asset_l.addWidget(w.image_controls)
    asset_l.addWidget(label('TEXT / HANDWRITING'))
    w.text=QPlainTextEdit('Hello world!')
    w.text.setMaximumHeight(74)
    asset_l.addWidget(w.text)
    from font_library import STARTER_FONTS
    w.font_select=QComboBox()
    w.font_select.setEditable(True)
    w.font_select.addItems(['Built-in single-line pen']+list(STARTER_FONTS))
    w.font_select.setToolTip('Select an open-licensed Google Fonts family. Download before use, or import your own TTF/OTF.')
    asset_l.addWidget(w.font_select)
    w.font_size=w.number(24,128,68,4)
    font_size_form=form_layout()
    font_size_form.addRow('Glyph detail size',w.font_size)
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
    asset_l.addLayout(style_form)
    w.generate_text=QPushButton('Animate lettering')
    w.generate_text.clicked.connect(w.letter)
    asset_l.addWidget(w.generate_text)
    w.download_font=QPushButton('Download selected Google Font')
    w.download_font.clicked.connect(w.install_selected_font)
    asset_l.addWidget(w.download_font)
    w.download_starters=QPushButton('Download 10 handwriting fonts')
    w.download_starters.clicked.connect(w.install_starter_fonts)
    asset_l.addWidget(w.download_starters)
    w.import_font_button=QPushButton('Import local TTF / OTF…')
    w.import_font_button.clicked.connect(w.import_local_font)
    asset_l.addWidget(w.import_font_button)
    browse_fonts=QPushButton('Browse Google Fonts catalog ↗')
    browse_fonts.setObjectName('subtle')
    browse_fonts.clicked.connect(w.browse_google_fonts)
    asset_l.addWidget(browse_fonts)
    w.font_note=caption('Built-in pen works offline. Google Fonts are downloaded only when requested; license files are saved too.')
    asset_l.addWidget(w.font_note)
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
    w.preview_background=QComboBox()
    w.preview_background.addItems(['Transparency grid','White background','Dark background'])
    w.preview_background.setToolTip('Preview background only. Exports keep transparency.')
    w.preview_background.setAccessibleName('Preview background')
    top.addWidget(w.preview_background)
    monitor_l.addLayout(top)
    w.canvas=Canvas()
    w.canvas.setMinimumSize(360,250)
    monitor_l.addWidget(w.canvas,1)
    w.preview_background.currentIndexChanged.connect(w.canvas.set_background)
    w.preview_background.currentIndexChanged.connect(
        lambda index: index in (1,2) and w.mp4_background.setCurrentIndex(index-1))
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
    w.artwork_size=w.number(25,200,100,5)
    w.artwork_size.setSuffix('%')
    w.artwork_size.setToolTip('Scale only the artwork, not the hand. The hand size stays controlled by Hand Size. Above 100% may crop the artwork.')
    a.addRow('Artwork size',w.artwork_size)
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
    w.reveal_mode.addItems(['Fade','Brush painting','Adaptive Hand Painting'])
    a2.addRow('Paint mode',w.reveal_mode)
    w.image_paint_hint=caption('AI plans the paths internally. Choose a visible outline drawing, or paint directly. Original PNG colors are preserved.')
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
    w.handsize=w.number(.02,.8,.75,.01);h.addRow('Hand scale',w.handsize)
    w.ax=w.number(0,1,.20,.01);h.addRow('Pen tip X',w.ax)
    w.ay=w.number(0,1,.20,.01);h.addRow('Pen tip Y',w.ay)
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
    w.mp4_background.addItems(['White','Dark','Black'])
    w.mp4_background.setToolTip('Background color of the MP4. White and Dark match the preview backgrounds.')
    e3=form_layout();e3.addRow('MP4 background',w.mp4_background)
    output_l.addLayout(e3)
    w.keep_png=QCheckBox('Keep generated PNG frames')
    w.keep_png.setChecked(False)
    w.keep_png.setToolTip('If video encoding succeeds, frame PNGs can be removed.')
    output_l.addWidget(w.keep_png)
    output_l.addWidget(caption('If no video format is selected, all transparent PNG frames are kept.'))
    w.export=QPushButton('Export animation…')
    w.export.setObjectName('primary');w.export.clicked.connect(w.save)
    output_l.addWidget(w.export)
    w.cancel=QPushButton('Cancel export')
    w.cancel.setEnabled(False);w.cancel.clicked.connect(w.cancel_export)
    output_l.addWidget(w.cancel)
    output_l.addWidget(caption('Export progress appears below the timeline.'))
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
    footer=QHBoxLayout()
    w.status=label('Ready  •  Import → adjust → preview → export','status')
    w.status.setWordWrap(True)
    footer.addWidget(w.status,1)
    w.progress=QProgressBar();w.progress.setFixedWidth(180);w.progress.setValue(0)
    footer.addWidget(w.progress)
    outer.addLayout(footer)

    # Retain the existing preview/export signal wiring.
    for widget in (w.duration,w.speed,w.thickness,w.artwork_size,w.handsize,w.ax,w.ay):
        widget.valueChanged.connect(w.refresh)
    w.showhand.toggled.connect(w.refresh)
    w.res.currentIndexChanged.connect(w.refresh)
    w.use_color.toggled.connect(w.refresh)
    w.color_fade.valueChanged.connect(w.refresh)
    w.color_hold.valueChanged.connect(w.refresh)
    w.reveal_mode.currentIndexChanged.connect(w.refresh)
    w.brush_width.valueChanged.connect(w.schedule_brush_refresh)
    w.show_paint_hand.toggled.connect(w.refresh)
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
    w.sync_workspace()
