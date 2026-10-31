"""Live model updates panel: one card per registered image model.

The dialog supplies actual filesystem/publisher scan results. Actions are
signals routed to its existing worker/download controls, never fake previews.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QSizePolicy,
)
from model_updates_live import ModelState
import theme


def label(text, name="", wrap=True):
    widget = QLabel(str(text))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    if name:
        widget.setObjectName(name)
    return widget


class StatusBadge(QLabel):
    def __init__(self, text, tone="muted"):
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setProperty("tone", tone)
        self.setObjectName("modelBadge")


class SectionHeader(QWidget):
    def __init__(self, title, count, description):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(label(f"{title} ({count})", "updateSection"))
        layout.addWidget(label(description, "updateMuted"))


class ModelStatusCard(QFrame):
    action_requested = Signal(str, str)

    def __init__(self, item):
        super().__init__()
        self.item = item
        self.setObjectName("modelStatusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(7)
        status_text = {
            "update_available": "Different official revision available",
            "up_to_date": "Matches published weights",
            "unverified": "Couldn’t check for updates",
            "incomplete": "Installation incomplete",
            "not_installed": "Optional model — not installed",
            "backup_pending": "Previous revision retained",
        }.get(item.status, "Unknown")
        head = QHBoxLayout()
        head.addWidget(label(item.name, "modelName"), 1)
        head.addWidget(StatusBadge(
            "Installed" if item.installed else "Optional",
            "good" if item.installed else "accent"))
        layout.addLayout(head)
        status = label("● " + status_text, "modelStatus")
        status.setProperty(
            "tone", "warning" if item.status in ("update_available", "incomplete", "backup_pending")
            else "good" if item.status == "up_to_date" else "accent")
        layout.addWidget(status)
        layout.addWidget(label(f"{item.provider}  |  {item.variant_label}", "updateMuted"))
        note=item.note
        if item.status=='unverified':
            note='Your installed model is unchanged. We couldn’t confirm whether an update is available. Try again later.'
        elif not item.installed:
            import ai_models
            model=next((m for m in ai_models.MODELS if m.id==item.model_id),None)
            variant=next((v for v in model.variants if v.id==item.variant_id),None) if model else None
            size=ai_models.gb(ai_models.download_size(model,variant)) if variant else (
                ai_models.gb(item.file.size) if item.file else 'Size shown before download')
            note=f'Optional download: {size}. This is a separate model, not a required update. Keep your current model if you’re happy with it.'
        details = label(note, "updateMuted")
        layout.addWidget(details)
        if item.status=='unverified':
            technical=QPushButton('Technical details')
            technical.setCheckable(True)
            extra=label(item.note,"updateMuted");extra.hide()
            technical.toggled.connect(extra.setVisible)
            layout.addWidget(technical);layout.addWidget(extra)
        if item.remote:
            layout.addWidget(label(
                f"Publisher SHA-256: {item.remote.sha256[:12]}…  |  "
                f"File: {item.remote.size / 1e9:.1f} GB",
                "updateMuted"))
        actions = QHBoxLayout()
        actions.setSpacing(7)
        actions.addStretch(1)
        action = {
            "update_available": ("Update", "update"),
            "not_installed": ("Install", "install"),
            "incomplete": ("Repair", "repair"),
            "backup_pending": ("Manage", "manage"),
            "unverified": ("Check again", "rescan"),
        }.get(item.status)
        if action:
            caption, key = action
            button = QPushButton(caption)
            button.setObjectName("primary" if key in ("update", "install") else "secondary")
            button.clicked.connect(lambda checked=False, a=key: self.action_requested.emit(a, self.item.model_id))
            actions.addWidget(button)
        layout.addLayout(actions)


class UpdatePanel(QFrame):
    close_requested = Signal()
    action_requested = Signal(str, str)
    cancel_requested = Signal()

    def __init__(self, parent=None, items=None):
        super().__init__(parent)
        self.items = tuple(items or ())
        self.setObjectName("imageUpdatesPanel")
        self.setFixedWidth(400)
        self.setAccessibleName("Image Generator Updates")
        self.setStyleSheet(self.panel_style())
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 15, 14, 12)
        root.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("◇  Image Generator Updates", "updateTitle"), 1)
        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setObjectName("drawerClose")
        self.close_button.setAccessibleName("Close Image Generator Updates")
        self.close_button.clicked.connect(self.close_requested.emit)
        head.addWidget(self.close_button)
        root.addLayout(head)
        root.addWidget(label(
            "Check official model files and manage the models installed on this computer.",
            "updateMuted"))
        self.scan_notice = label(
            "Open Check for updates to inspect your installed models.", "updateNotice")
        root.addWidget(self.scan_notice)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)
        self.feedback = label("No model files changed.", "updateFeedback")
        self.feedback.setAccessibleName("Model update action feedback")
        root.addWidget(self.feedback)
        self.cancel_button = QPushButton("Cancel current check or download")
        self.cancel_button.setObjectName("secondary")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        root.addWidget(self.cancel_button)
        self.set_items(self.items)

    def set_items(self, items):
        self.items = tuple(items)
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(10)
        self.cards = []
        if not self.items:
            layout.addWidget(label("No model results yet.", "updateMuted"))
        groups = (
            ("Updates available",
             "Verified official file differs from the local installed file.",
             [i for i in self.items if i.status == "update_available"]),
            ("Installed models", "Real models in the configured AI folder.",
             [i for i in self.items if i.installed and i.status != "update_available"]),
            ("Optional models", "Other models you can choose; no download is required.",
             [i for i in self.items if not i.installed]),
        )
        for title, description, items in groups:
            layout.addWidget(SectionHeader(title, len(items), description))
            for item in items:
                card = ModelStatusCard(item)
                card.action_requested.connect(self.action_requested.emit)
                self.cards.append(card)
                layout.addWidget(card)
        layout.addStretch(1)
        self.scroll.setWidget(content)

    def show_feedback(self, message):
        self.feedback.setText(str(message))

    def set_busy(self, busy):
        self.cancel_button.setVisible(bool(busy))

    @staticmethod
    def panel_style():
        c = theme.colors()
        return f"""
QFrame#imageUpdatesPanel {{ background:{c['window']}; border:1px solid {c['border_strong']}; border-radius:12px; }}
QLabel#updateTitle {{ font-size:15px; font-weight:700; }}
QLabel#updateSection {{ font-size:13px; font-weight:700; }}
QLabel#modelName {{ font-weight:600; }}
QLabel#updateMuted {{ color:{c['muted']}; font-size:11px; }}
QLabel#updateNotice {{ background:{c['raised']}; border:1px solid {c['border']}; border-radius:9px; padding:10px; color:{c['muted']}; font-size:11px; }}
QFrame#modelStatusCard {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:10px; }}
QLabel#modelBadge {{ border-radius:8px; padding:3px 7px; font-size:10px; }}
QLabel#modelBadge[tone="good"] {{ background:#23553b; color:#9ee5b5; }}
QLabel#modelBadge[tone="accent"] {{ background:{c['selection']}; color:{c['brand']}; }}
QLabel#modelStatus[tone="good"] {{ color:{c['good']}; }}
QLabel#modelStatus[tone="warning"] {{ color:#eab05a; }}
QLabel#modelStatus[tone="accent"] {{ color:{c['brand']}; }}
QLabel#updateFeedback {{ color:{c['muted']}; font-size:11px; padding-top:4px; }}
QPushButton#drawerClose {{ padding:0px; font-size:20px; background:transparent; }}
QPushButton#drawerClose:hover {{ background:{c['raised_hover']}; }}
"""
