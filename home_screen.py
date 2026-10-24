"""The Home screen: what you see when StrokeScribe opens (exp.107).

Instead of dropping you straight into an empty project, StrokeScribe starts on
Home: start a new project, open one from disk, or pick one of your projects
(recent ones, and every project in the projects folder) from a grid of cards with
a small preview, its name and when it was last changed.

Previews: a project file can be large, so Home never reads the projects to show
them. When a project is saved (or opened and its pictures are ready), a small
preview picture is kept in StrokeScribe's settings folder, keyed by the project's
path. A project without one shows its initials until it is opened once.

File > Home (Ctrl+H) brings Home back at any time; Esc or "Back to project" leaves it.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from pathlib import Path

SUFFIX = '.strokescribe'
PREVIEW_W, PREVIEW_H = 320, 180


# ---------------------------------------------------------------- places

def projects_folder():
    """Documents/StrokeScribe Projects (where new projects are saved by default)."""
    override = os.environ.get('STROKESCRIBE_PROJECTS_FOLDER')
    if override:
        return Path(override)
    home = Path.home()
    docs = home / 'Documents'
    return (docs if docs.is_dir() else home) / 'StrokeScribe Projects'


def _settings_folder():
    from preflight import config_path
    return config_path().parent


def preview_path(project):
    key = hashlib.sha1(os.path.normcase(str(Path(project).resolve())).encode('utf-8')).hexdigest()[:20]
    return _settings_folder() / 'home-previews' / f'{key}.png'


def store_preview(project, image):
    """Keep a small preview (a QImage) of `project` for its card on Home."""
    from PySide6.QtCore import Qt
    if image is None or image.isNull() or not project:
        return False
    try:
        target = preview_path(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        small = image.scaled(PREVIEW_W, PREVIEW_H, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        return bool(small.save(str(target), 'PNG'))
    except Exception:
        return False


def needs_preview(project):
    """No preview yet, or the project was changed after its preview was made."""
    try:
        pic = preview_path(project)
        return not pic.is_file() or pic.stat().st_mtime + 2 < Path(project).stat().st_mtime
    except OSError:
        return True


def make_preview(project, hand=None):
    """Read a project file and keep a preview of its first element (for projects saved
    before exp.107, or changed elsewhere). True when a preview was made."""
    import projects
    from scenes import job_from_state, scenes_from_project, thumbnail
    data = projects.load(project)
    states = [s.get('state') for s in scenes_from_project(data) if s.get('state')]
    state = states[0] if states else data
    drawing, options, _ = job_from_state(state, hand)
    if not drawing.strokes:
        return False
    return store_preview(project, thumbnail(drawing, options, width=PREVIEW_W))


def list_projects():
    """Every project to show: recent ones and those in the projects folder, newest first.
    [{'path', 'name', 'modified', 'recent'}]"""
    seen, out = set(), []

    def add(path, recent):
        p = Path(path)
        try:
            key = os.path.normcase(str(p.resolve()))
            if key in seen or not p.is_file():
                return
            seen.add(key)
            out.append(dict(path=str(p), name=p.stem, modified=p.stat().st_mtime, recent=recent))
        except OSError:
            pass
    try:
        import autosave
        for p in autosave.recent():
            add(p, True)
    except Exception:
        pass
    folder = projects_folder()
    try:
        if folder.is_dir():
            for p in folder.glob('*' + SUFFIX):
                add(p, False)
    except OSError:
        pass
    out.sort(key=lambda d: -d['modified'])
    return out


def when(stamp, now=None):
    """'Just now', '5 minutes ago', 'Today 14:02', 'Yesterday', '3 Oct 2026'."""
    now = time.time() if now is None else now
    gap = max(0., now - stamp)
    if gap < 60:
        return 'Just now'
    if gap < 3600:
        m = int(gap // 60)
        return f'{m} minute{"s" if m != 1 else ""} ago'
    day = datetime.fromtimestamp(stamp)
    today = datetime.fromtimestamp(now)
    if day.date() == today.date():
        return 'Today ' + day.strftime('%H:%M')
    if (today.date() - day.date()).days == 1:
        return 'Yesterday ' + day.strftime('%H:%M')
    return f'{day.day} {day.strftime("%b %Y")}'


def show_in_folder(path):
    import subprocess
    import sys
    path = Path(path)
    try:
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', '/select,', str(path)] if path.is_file() else ['explorer', str(path)])
        else:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if path.is_file() else path)))
    except Exception:
        pass


def forget_recent(path):
    import json
    import autosave
    try:
        target = autosave._folder() / 'recent.json'
        paths = json.loads(target.read_text()) if target.is_file() else []
        key = os.path.normcase(str(Path(path)))
        paths = [p for p in paths if os.path.normcase(str(Path(p))) != key]
        target.write_text(json.dumps(paths, indent=1))
    except Exception:
        pass


# ---------------------------------------------------------------- widgets

def _widgets():
    from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
                                   QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
    import theme
    import ui_icons

    def c(key):
        return QColor(theme.colors()[key])

    class Card(QWidget):
        """One project: preview, name, when it was changed. Click opens it."""
        opened = Signal(str)
        menu = Signal(str, object)
        W, H = 236, 196

        def __init__(self, info=None, new=False, parent=None):
            super().__init__(parent)
            self.info, self.new, self.hover = info or {}, new, False
            self.setFixedSize(self.W, self.H)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setMouseTracking(True)
            self.preview = None
            if info:
                self.load_preview()
                self.setToolTip(info['path'])
            else:
                self.setToolTip('Start a new, empty project')

        def load_preview(self):
            p = preview_path(self.info['path'])
            if p.is_file():
                img = QImage(str(p))
                self.preview = None if img.isNull() else img
            self.update()

        def enterEvent(self, e):
            self.hover = True; self.update()

        def leaveEvent(self, e):
            self.hover = False; self.update()

        def mouseReleaseEvent(self, e):
            if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
                self.opened.emit('' if self.new else self.info['path'])
            elif e.button() == Qt.MouseButton.RightButton and not self.new:
                self.menu.emit(self.info['path'], e.globalPosition().toPoint())

        def keyPressEvent(self, e):
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self.opened.emit('' if self.new else self.info['path'])
            else:
                super().keyPressEvent(e)

        def paintEvent(self, e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            outer = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            body = QPainterPath(); body.addRoundedRect(outer, 12, 12)
            p.fillPath(body, c('raised_hover') if self.hover else c('raised'))
            pen = QPen(c('accent') if self.hover else c('border_strong'), 1.6 if self.hover else 1.)
            p.setPen(pen); p.drawPath(body)
            thumb = QRectF(outer.left() + 8, outer.top() + 8, outer.width() - 16, 126)
            clip = QPainterPath(); clip.addRoundedRect(thumb, 8, 8)
            p.save(); p.setClipPath(clip)
            if self.new:
                g = QLinearGradient(thumb.topLeft(), thumb.bottomRight())
                g.setColorAt(0, c('accent_a')); g.setColorAt(1, c('accent_b'))
                p.fillRect(thumb, g)
                p.drawPixmap(int(thumb.center().x() - 22), int(thumb.center().y() - 22),
                             ui_icons.pixmap('plus', '#FFFFFF', 44))
            elif self.preview is not None:
                p.fillRect(thumb, QColor('#F4F1EA'))
                img = self.preview.scaled(int(thumb.width() * 2), int(thumb.height() * 2),
                                          Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
                img.setDevicePixelRatio(2.)
                iw, ih = img.width() / 2., img.height() / 2.
                p.drawImage(QPointF(thumb.center().x() - iw / 2, thumb.center().y() - ih / 2), img)
            else:
                g = QLinearGradient(thumb.topLeft(), thumb.bottomRight())
                g.setColorAt(0, c('input')); g.setColorAt(1, c('pressed'))
                p.fillRect(thumb, g)
                words = [w for w in self.info.get('name', '?').replace('_', ' ').replace('-', ' ').split() if w]
                letters = ''.join(w[0] for w in words[:2]).upper() or '?'
                f = QFont('Segoe UI', 26, QFont.Weight.DemiBold); p.setFont(f)
                p.setPen(c('brand'))
                p.drawText(thumb, Qt.AlignmentFlag.AlignCenter, letters)
            p.restore()
            p.setPen(QPen(c('border'), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(thumb, 8, 8)
            text = QRectF(outer.left() + 12, thumb.bottom() + 9, outer.width() - 24, 20)
            f = QFont('Segoe UI', 10, QFont.Weight.DemiBold); p.setFont(f); p.setPen(c('text'))
            name = 'New project' if self.new else self.info.get('name', '')
            p.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(text.width())))
            sub = QRectF(text.left(), text.bottom() + 1, text.width(), 18)
            p.setFont(QFont('Segoe UI', 8)); p.setPen(c('muted'))
            line = 'Empty page, ready for artwork' if self.new else when(self.info.get('modified', 0))
            p.drawText(sub, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)

    class SideButton(QPushButton):
        def __init__(self, text, icon_name, primary=False):
            super().__init__('  ' + text)
            self.setObjectName('primary' if primary else 'homeSide')
            self.setIcon(ui_icons.icon(icon_name, '#FFFFFF' if primary else theme.colors()['text'], size=18))
            self.setIconSize(QSize(18, 18))
            self.setMinimumHeight(42)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    class HomeScreen(QWidget):
        """Covers the whole window under the menu bar."""
        new_requested = Signal()
        open_requested = Signal(str)        # '' = choose a file
        back_requested = Signal()

        def __init__(self, parent=None, version=''):
            super().__init__(parent)
            self.setObjectName('homeScreen')
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setAutoFillBackground(True)
            self.cards = []
            self.failed = set()             # projects whose preview could not be made
            self.hand = None                # the drawing hand (set by the window)
            self._preview_token = None
            row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0)

            side = QFrame(); side.setObjectName('homeSide'); side.setFixedWidth(280)
            s = QVBoxLayout(side); s.setContentsMargins(26, 30, 26, 24); s.setSpacing(10)
            from studio_workspace import wordmark_html
            logo = QLabel(wordmark_html()); logo.setObjectName('homeLogo')
            logo.setTextFormat(Qt.TextFormat.RichText)
            s.addWidget(logo)
            tag = QLabel('Whiteboard animation studio'); tag.setObjectName('homeMuted')
            s.addWidget(tag)
            s.addSpacing(26)
            self.new_button = SideButton('New project', 'plus', primary=True)
            self.open_button = SideButton('Open project…', 'open')
            self.folder_button = SideButton('Projects folder', 'folder')
            self.back_button = SideButton('Back to project', 'home')
            for b in (self.new_button, self.open_button, self.folder_button):
                s.addWidget(b)
            s.addSpacing(8)
            s.addWidget(self.back_button)
            s.addStretch(1)
            self.folder_label = QLabel(); self.folder_label.setObjectName('homeMuted')
            self.folder_label.setWordWrap(True)
            s.addWidget(self.folder_label)
            ver = QLabel(f'Version {version}' if version else ''); ver.setObjectName('homeDim')
            s.addWidget(ver)
            row.addWidget(side)

            main = QWidget(); main.setObjectName('homeMain')
            m = QVBoxLayout(main); m.setContentsMargins(36, 30, 24, 0); m.setSpacing(14)
            head = QHBoxLayout()
            title = QLabel('Your projects'); title.setObjectName('homeTitle')
            head.addWidget(title); head.addStretch(1)
            self.search = QLineEdit(); self.search.setPlaceholderText('Search projects')
            self.search.setClearButtonEnabled(True); self.search.setFixedWidth(240)
            self.search.textChanged.connect(self._filter)
            head.addWidget(self.search)
            m.addLayout(head)
            self.count_label = QLabel(); self.count_label.setObjectName('homeMuted')
            m.addWidget(self.count_label)
            self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.grid_host = QWidget(); self.grid_host.setObjectName('homeMain')
            self.grid = QGridLayout(self.grid_host)
            self.grid.setContentsMargins(0, 4, 12, 24); self.grid.setSpacing(18)
            self.grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.scroll.setWidget(self.grid_host)
            m.addWidget(self.scroll, 1)
            self.empty = QLabel('No projects yet. Start a new one — when you save it, it shows up here.')
            self.empty.setObjectName('homeMuted'); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            m.addWidget(self.empty)
            row.addWidget(main, 1)

            self.new_button.clicked.connect(self.new_requested)
            self.open_button.clicked.connect(lambda: self.open_requested.emit(''))
            self.folder_button.clicked.connect(self._open_folder)
            self.back_button.clicked.connect(self.back_requested)
            self.restyle()

        def restyle(self):
            k = theme.colors()
            self.setStyleSheet(
                f"QWidget#homeScreen {{ background: {k['window']}; }}"
                f"QFrame#homeSide {{ background: {k['panel']}; border-right: 1px solid {k['border']}; }}"
                f"QWidget#homeMain {{ background: {k['window']}; }}"
                f"QLabel#homeMuted {{ color: {k['muted']}; }}"
                f"QLabel#homeDim {{ color: {k['dim']}; font-size: 8pt; }}"
                f"QLabel#homeTitle {{ color: {k['text']}; font-size: 20pt; font-weight: 600; }}"
                f"QLabel#homeLogo {{ font-size: 22pt; font-weight: 700; }}"
                f"QPushButton#homeSide {{ text-align: left; padding: 8px 14px; border-radius: 9px;"
                f" background: {k['raised']}; border: 1px solid {k['border']}; color: {k['text']}; }}"
                f"QPushButton#homeSide:hover {{ background: {k['raised_hover']}; border-color: {k['border_strong']}; }}"
                f"QPushButton#primary {{ text-align: left; padding: 8px 14px; border-radius: 9px; }}")

        def set_can_go_back(self, can):
            self.back_button.setVisible(bool(can))

        def refresh(self):
            for card in self.cards:
                card.setParent(None); card.deleteLater()
            self.cards = []
            projects = list_projects()
            self.cards.append(self._card(None))
            for info in projects:
                self.cards.append(self._card(info))
            folder = projects_folder()
            self.folder_label.setText(f'New projects are saved in\n{folder.parent.name} › {folder.name}')
            self.folder_label.setToolTip(str(folder))
            self._projects = projects
            self._filter(self.search.text())
            self.fill_previews()

        def fill_previews(self):
            """Make the missing previews one by one, without freezing Home (exp.109)."""
            from PySide6.QtCore import QTimer
            todo = [c for c in self.cards if not c.new and c.info['path'] not in self.failed
                    and needs_preview(c.info['path'])]
            if not todo:
                return
            token = object(); self._preview_token = token

            def step():
                if self._preview_token is not token or not self.isVisible():
                    return
                left = [c for c in todo if c in self.cards and c.info['path'] not in self.failed
                        and needs_preview(c.info['path'])]
                if not left:
                    return
                card = left[0]
                try:
                    if make_preview(card.info['path'], self.hand):
                        card.load_preview()
                    else:
                        self.failed.add(card.info['path'])
                except Exception as exc:
                    self.failed.add(card.info['path'])
                    try:
                        import applog; applog.error('Home preview ' + card.info['path'], exc)
                    except Exception:
                        pass
                QTimer.singleShot(40, step)
            QTimer.singleShot(60, step)

        def _card(self, info):
            card = Card(info, new=info is None)
            card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            card.opened.connect(self._card_opened)
            card.menu.connect(self._card_menu)
            return card

        def _card_opened(self, path):
            if path:
                self.open_requested.emit(path)
            else:
                self.new_requested.emit()

        def _card_menu(self, path, where):
            menu = QMenu(self)
            menu.addAction('Open', lambda: self.open_requested.emit(path))
            menu.addAction('Show in folder', lambda: show_in_folder(path))
            menu.addSeparator()
            menu.addAction('Remove from list', lambda: (forget_recent(path), self.refresh()))
            menu.exec(where)

        def _open_folder(self):
            folder = projects_folder()
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            show_in_folder(folder)

        def visible_cards(self):
            return [c for c in self.cards if not c.isHidden()]

        def _filter(self, text=''):
            text = (text or '').strip().lower()
            shown = [c for c in self.cards if c.new and not text or (not c.new and text in c.info['name'].lower())]
            for card in self.cards:
                card.setVisible(card in shown)
            self._lay_out(shown)
            n = len(getattr(self, '_projects', []))
            self.count_label.setText('' if not n else f'{n} project{"s" if n != 1 else ""}'
                                     + (f' · {len([c for c in shown if not c.new])} match' if text else ''))
            self.empty.setVisible(n == 0)

        def _lay_out(self, shown=None):
            shown = self.visible_cards() if shown is None else shown
            while self.grid.count():
                self.grid.takeAt(0)
            width = max(Card.W, self.scroll.viewport().width() - 12)
            cols = max(1, (width + 18) // (Card.W + 18))
            for i, card in enumerate(shown):
                self.grid.addWidget(card, i // cols, i % cols)

        def resizeEvent(self, e):
            super().resizeEvent(e)
            self._lay_out()

        def keyPressEvent(self, e):
            if e.key() == Qt.Key.Key_Escape and self.back_button.isVisible():
                self.back_requested.emit()
            else:
                super().keyPressEvent(e)

    return HomeScreen, Card


def HomeScreen(*a, **k):
    return _widgets()[0](*a, **k)
