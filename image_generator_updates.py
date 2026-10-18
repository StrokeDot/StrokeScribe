"""Reusable image-model update drawer.

Metadata is injected. The bundled provider is demonstration data only: no
hardware scan, installed-file scan, network request or download happens here.
"""
from __future__ import annotations
from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QSizePolicy,
)
import theme


@dataclass(frozen=True)
class ModelUpdateItem:
    id: str
    name: str
    provider: str
    category: str
    installed: bool = False
    installed_version: str = ''
    available_version: str = ''
    quantization: str = ''
    precision: str = ''
    download_size: int = 0
    compatibility: str = ''
    performance_note: str = ''
    new_model: bool = False

    @property
    def has_update(self):
        # A future provider supplies the newer available version; never infer
        # a real update from a local file name or installed quantization.
        return bool(self.installed and self.installed_version and
                    self.available_version and self.available_version != self.installed_version)


def demo_items():
    return (
        ModelUpdateItem('flux-klein','FLUX.2 [klein] 4B','Black Forest Labs',
                        'Image generation',True,'BF16','BF16',precision='BF16',
                        download_size=16_100_000_000,compatibility='Fits your PC'),
        ModelUpdateItem('qwen-edit','Qwen-Image-Edit 2511','Qwen','Image editing',
                        True,'2511','2511 preview revision',quantization='GGUF Q4_K_M',
                        download_size=7_400_000_000,compatibility='Fits your PC'),
        ModelUpdateItem('flux-dev','FLUX.2 [dev]','Black Forest Labs','Image generation',
                        available_version='Preview',precision='BF16 (or GGUF)',
                        download_size=28_300_000_000,compatibility='Fits your PC',
                        performance_note='Runs slower on your PC',new_model=True),
    )


def label(text, name='', wrap=True):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    result.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Minimum)
    if name: result.setObjectName(name)
    return result


class StatusBadge(QLabel):
    def __init__(self, text, tone='muted'):
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setProperty('tone',tone)
        self.setObjectName('modelBadge')
        self.setSizePolicy(QSizePolicy.Policy.Maximum,QSizePolicy.Policy.Fixed)


class SectionHeader(QWidget):
    def __init__(self, title, count, description):
        super().__init__()
        layout=QVBoxLayout(self);layout.setContentsMargins(0,5,0,0);layout.setSpacing(3)
        layout.addWidget(label(f'{title} ({count})','updateSection'))
        layout.addWidget(label(description,'updateMuted'))


class ModelStatusCard(QFrame):
    action_requested = Signal(str,str)

    def __init__(self, item):
        super().__init__()
        self.item=item
        self.setObjectName('modelStatusCard')
        layout=QVBoxLayout(self);layout.setContentsMargins(12,11,12,11);layout.setSpacing(7)
        title=QHBoxLayout();title.setSpacing(8)
        icon=label('◇','modelIcon',False);icon.setFixedSize(28,28)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter);title.addWidget(icon)
        title.addWidget(label(item.name,'modelName'),1)
        title.addWidget(StatusBadge('Installed' if item.installed else 'Compatible',
                                   'good' if item.installed else 'accent'))
        layout.addLayout(title)
        state='Update available' if item.has_update else 'Up to date' if item.installed else 'New model' if item.new_model else 'Compatible'
        status=label('● '+state,'modelStatus')
        status.setProperty('tone','warning' if item.has_update else 'good' if item.installed else 'accent')
        layout.addWidget(status)
        layout.addWidget(label(f'{item.provider}  |  {item.category}','updateMuted'))
        version=item.quantization or item.precision or item.installed_version or item.available_version
        info=[f'Version: {version}'] if version else []
        if item.download_size: info.append(f'{item.download_size/1e9:.1f} GB')
        if item.compatibility: info.append(item.compatibility)
        layout.addWidget(label('  |  '.join(info),'updateMuted'))
        if item.performance_note:
            layout.addWidget(label('● '+item.performance_note,'modelWarning'))
        self.details=label(
            f'Installed version: {item.installed_version or "Not installed"}\n'
            f'Available version: {item.available_version or "Not specified"}\n'
            'Demonstration metadata; versions, size and PC fit have not been checked.',
            'updateMuted')
        self.details.hide()
        layout.addWidget(self.details)
        actions=QHBoxLayout();actions.setSpacing(7)
        details=QPushButton('Details');details.setCheckable(True)
        details.toggled.connect(self.details.setVisible)
        actions.addWidget(details)
        actions.addStretch(1)
        names=('Update','Keep current') if item.has_update else ('Up to date',) if item.installed else ('Install',)
        for name in names:
            button=QPushButton(name)
            button.setObjectName('primary' if name in ('Update','Install') else 'secondary')
            button.setEnabled(name!='Up to date')
            button.clicked.connect(lambda checked=False, action=name:self.action_requested.emit(action,self.item.id))
            actions.addWidget(button)
        layout.addLayout(actions)


class UpdatePanel(QFrame):
    close_requested = Signal()

    def __init__(self, parent=None, items=None):
        super().__init__(parent)
        self.items=tuple(demo_items() if items is None else items)
        self.setObjectName('imageUpdatesPanel')
        self.setFixedWidth(400)
        self.setAccessibleName('Image Generator Updates')
        self.setStyleSheet(self.panel_style())
        root=QVBoxLayout(self);root.setContentsMargins(14,15,14,12);root.setSpacing(10)
        header=QHBoxLayout()
        header.addWidget(label('◇  Image Generator Updates','updateTitle'),1)
        self.close_button=QPushButton('×');self.close_button.setFixedSize(28,28)
        self.close_button.setObjectName('drawerClose')
        self.close_button.setAccessibleName('Close Image Generator Updates')
        self.close_button.setToolTip('Close updates (Esc)')
        self.close_button.clicked.connect(self.close_requested.emit)
        header.addWidget(self.close_button)
        root.addLayout(header)
        root.addWidget(label('Manage image generation models, check for updates, and install compatible models for your PC.','updateMuted'))
        notice=label('ⓘ  This panel shows updates for image generators only. Other AI models (e.g. audio) are managed separately.','updateNotice')
        root.addWidget(notice)
        root.addWidget(label('Demonstration data — no live update check.','demoNotice'))
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content=QWidget();layout=QVBoxLayout(content);layout.setContentsMargins(0,0,4,0);layout.setSpacing(10)
        self.cards=[]
        image_items=[item for item in self.items if item.category.casefold() in ('image generation','image editing')]
        groups=(
            ('Installed models','Example models ready to use.',[i for i in image_items if i.installed]),
            ('Updates available','Example installed models with newer versions.',[i for i in image_items if i.has_update]),
            ('Compatible models','Example models that could work on this PC.',[i for i in image_items if not i.installed and i.compatibility]),
        )
        for title,description,models in groups:
            layout.addWidget(SectionHeader(title,len(models),description))
            if not models: layout.addWidget(label('No models in this section.','updateMuted'))
            for item in models:
                card=ModelStatusCard(item);card.action_requested.connect(self.preview_action)
                self.cards.append(card);layout.addWidget(card)
        footer=QFrame();footer.setObjectName('modelStatusCard')
        foot=QVBoxLayout(footer);foot.setContentsMargins(12,11,12,11);foot.setSpacing(6)
        foot.addWidget(label('Find more models online','modelName'))
        foot.addWidget(label('Discover image generation models from the community. Compatibility must be checked separately.','updateMuted'))
        browse=QPushButton('Browse models ↗');browse.setObjectName('secondary')
        browse.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://huggingface.co/models?pipeline_tag=text-to-image')))
        foot.addWidget(browse,0,Qt.AlignmentFlag.AlignRight)
        layout.addWidget(footer);layout.addStretch(1)
        self.scroll.setWidget(content);root.addWidget(self.scroll,1)
        self.feedback=label('Example actions do not download or modify models.','updateFeedback')
        self.feedback.setAccessibleName('Model update action feedback')
        root.addWidget(self.feedback)
        self.close_requested.connect(self.hide)

    def preview_action(self, action, model_id):
        item=next(i for i in self.items if i.id==model_id)
        if action=='Keep current':
            self.feedback.setText(f'{item.name}: current version kept in this demonstration. No files changed.')
        else:
            self.feedback.setText(f'{item.name}: {action.lower()} preview only. Live model downloads are not connected to this drawer.')

    @staticmethod
    def panel_style():
        c=theme.colors()
        return f"""
QFrame#imageUpdatesPanel {{ background:{c['window']}; border:1px solid {c['border_strong']}; border-radius:12px; }}
QLabel#updateTitle {{ font-size:15px; font-weight:700; }}
QLabel#updateSection {{ font-size:13px; font-weight:700; }}
QLabel#modelName {{ font-weight:600; }}
QLabel#updateMuted {{ color:{c['muted']}; font-size:11px; }}
QLabel#updateNotice {{ background:{c['raised']}; border:1px solid {c['border']}; border-radius:9px; padding:10px; color:{c['muted']}; font-size:11px; }}
QLabel#demoNotice {{ color:{c['brand']}; font-size:11px; font-weight:600; }}
QFrame#modelStatusCard {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:10px; }}
QLabel#modelIcon {{ background:{c['accent']}; color:white; border-radius:8px; font-size:22px; }}
QLabel#modelBadge {{ border-radius:8px; padding:3px 7px; font-size:10px; }}
QLabel#modelBadge[tone="good"] {{ background:#23553b; color:#9ee5b5; }}
QLabel#modelBadge[tone="accent"] {{ background:{c['selection']}; color:{c['brand']}; }}
QLabel#modelStatus {{ font-size:11px; }}
QLabel#modelStatus[tone="good"] {{ color:{c['good']}; }}
QLabel#modelStatus[tone="warning"], QLabel#modelWarning {{ color:#eab05a; font-size:11px; }}
QLabel#modelStatus[tone="accent"] {{ color:{c['brand']}; }}
QLabel#updateFeedback {{ color:{c['muted']}; font-size:11px; padding-top:4px; }}
QPushButton#drawerClose {{ padding:0px; font-size:20px; background:transparent; }}
QPushButton#drawerClose:hover {{ background:{c['raised_hover']}; }}
"""
