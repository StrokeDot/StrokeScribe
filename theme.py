"""StrokeScribe Studio colour themes (dark is the default) and stylesheet.

Editor look: neutral graphite panels with a single blue accent in Dark,
an airy white workspace in Light. Custom-painted widgets (monitor,
timeline) read their colours from `colors()` so both themes stay consistent.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_THEME = 'dark'

PALETTES = {
    'dark': dict(
        window='#101113', panel='#1A1B1E', header='#1A1B1E', raised='#26282C',
        raised_hover='#30333A', pressed='#22242A', input='#222428', border='#2A2C31',
        border_strong='#3D4048', text='#E6E7EA', muted='#9A9DA5', dim='#62666F',
        accent='#6E4FF2', accent_hover='#8468F6', accent_text='#FFFFFF',
        accent_a='#7444F0', accent_b='#4C42DE', brand='#9A82FF',
        selection='#2D2760', monitor='#0C0D0F', monitor_frame='#26282C',
        draw='#6E4FF2', paint='#22A88F', hold='#D4A044', erase='#E06A86', clip_text='#FFFFFF',
        ruler='#7C7C7C', track='#161616', overlay='#0E0E0ECC', tooltip='#2C2C2C',
        wordmark='#F2F2F2', checker_a='#E9ECEF', checker_b='#D3D8DD',
        preview_dark='#242B35', good='#3FB950', bad='#F06A6A',
    ),
    'light': dict(
        window='#E9EDF2', panel='#FFFFFF', header='#FFFFFF', raised='#EEF1F5',
        raised_hover='#E3E8EE', pressed='#D9DFE7', input='#F3F5F8', border='#E1E6EC',
        border_strong='#B8C1CD', text='#1C2430', muted='#5B6878', dim='#9AA4B1',
        accent='#5B3FE6', accent_hover='#7058EC', accent_text='#FFFFFF',
        accent_a='#7444F0', accent_b='#4C42DE', brand='#5B3FE6',
        selection='#E4DEFD', monitor='#DDE2EA', monitor_frame='#C9D1DB',
        draw='#6A4CF0', paint='#1F9F87', hold='#D49B33', erase='#D45C76', clip_text='#FFFFFF',
        ruler='#8592A2', track='#EEF1F5', overlay='#E8ECF1D9', tooltip='#FFFFFF',
        wordmark='#1C2430', checker_a='#F1F4F7', checker_b='#DDE3E9',
        preview_dark='#242B35', good='#1F8F3A', bad='#D03B3B',
    ),
}

_current = DEFAULT_THEME


def current():
    return _current


def colors(name=None):
    return PALETTES[name or _current]


def set_current(name):
    global _current
    _current = name if name in PALETTES else DEFAULT_THEME
    return _current


def load_saved():
    """Theme saved from the last session (dark when never chosen)."""
    try:
        from PySide6.QtCore import QSettings
        value = QSettings('StrokeScribe', 'Studio').value('theme', DEFAULT_THEME)
        return value if value in PALETTES else DEFAULT_THEME
    except Exception:
        return DEFAULT_THEME


def save(name):
    try:
        from PySide6.QtCore import QSettings
        QSettings('StrokeScribe', 'Studio').setValue('theme', name)
    except Exception:
        pass


def stylesheet(name, assets):
    c = PALETTES[name]
    light = name == 'light'

    check = (Path(assets) / 'check.png').as_posix()
    check_off = (Path(assets) / 'check_disabled.png').as_posix()

    def arrow(kind, disabled=False):
        stem = f'spin_{kind}' + ('_light' if light else '') + ('_disabled' if disabled else '')
        return (Path(assets) / f'{stem}.png').as_posix()

    return f"""
QWidget {{ background: {c['panel']}; color: {c['text']}; font-size: 12px; }}
QMainWindow, QWidget#root {{ background: {c['window']}; }}
QLabel {{ background: transparent; }}
QFrame#topBar {{ background: {c['panel']}; border: 0px; border-radius: 14px; }}
QFrame#updateBanner {{ background: {c['selection']}; border: 1px solid {c['accent']}; border-radius: 14px; margin-top: 6px; }}
QLabel#bannerText {{ color: {c['text']}; font-weight: 600; background: transparent; }}
QLabel#brandWordmark {{ background: transparent; }}
QFrame#assetPanel, QFrame#inspectorPanel, QFrame#monitorPanel, QFrame#timelinePanel {{
    background: {c['panel']}; border: 0px; border-radius: 14px; }}
QFrame#panelHeader {{ background: transparent; border: 0px;
    border-top-left-radius: 14px; border-top-right-radius: 14px; }}
QLabel#panelTitle {{ color: {c['text']}; font-size: 13px; font-weight: 700; }}
QLabel#panelHint {{ color: {c['muted']}; font-size: 11px; }}
QFrame#monitorWell {{ background: {c['monitor']}; border: 0px; border-radius: 12px; }}
QFrame#transport {{ background: transparent; }}
QWidget#panelBody {{ background: {c['panel']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['panel']}; border: 0px; }}
QLabel#micro {{ color: {c['muted']}; font-size: 10px; font-weight: 700; }}
QLabel#section {{ color: {c['muted']}; font-size: 10px; font-weight: 700;
    padding-top: 6px; }}
QLabel#subtitle {{ color: {c['muted']}; font-size: 11px; }}
QLabel#timeCode {{ color: {c['accent']}; font-size: 15px; font-weight: 700;
    font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; }}
QLabel#timeTotal {{ color: {c['muted']}; font-size: 13px;
    font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; }}
QLabel#status {{ color: {c['muted']}; font-size: 11px; }}
QLabel#note {{ color: {c['muted']}; }}
QLabel#dialogTitle {{ font-size: 18px; font-weight: 700; }}
QLabel#good {{ color: {c['good']}; font-weight: 700; }}
QLabel#bad {{ color: {c['bad']}; font-weight: 700; }}
QLabel#muted {{ color: {c['muted']}; }}
QFormLayout QLabel {{ color: {c['muted']}; }}
QPushButton {{ background: {c['raised']}; color: {c['text']}; border: 1px solid transparent;
    border-radius: 9px; padding: 7px 13px; font-weight: 600; }}
QPushButton:hover {{ background: {c['raised_hover']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:disabled {{ color: {c['dim']}; background: {c['raised']}; border-color: transparent; }}
QPushButton:checked {{ background: {c['selection']}; border-color: {c['accent']}; color: {c['text']}; }}
QPushButton#primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent_a']}, stop:1 {c['accent_b']}); color: {c['accent_text']}; border: 0px; padding: 8px 16px; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#primary:disabled {{ background: {c['raised']}; color: {c['dim']}; }}
QPushButton#subtle, QToolButton#subtle {{ background: transparent; border: 1px solid transparent;
    border-radius: 9px; padding: 6px 10px; color: {c['muted']}; }}
QPushButton#subtle:hover, QToolButton#subtle:hover {{ background: {c['raised']}; color: {c['text']}; }}
QPushButton#transportButton {{ background: transparent; border: 0px; border-radius: 16px;
    min-width: 32px; min-height: 32px; max-height: 32px; padding: 0px; font-size: 15px; color: {c['text']}; }}
QPushButton#transportButton:hover {{ background: {c['raised']}; }}
QPushButton#playButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent_a']}, stop:1 {c['accent_b']}); color: {c['accent_text']}; border: 0px; border-radius: 20px;
    min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; padding: 0px; font-size: 15px; }}
QPushButton#playButton:hover {{ background: {c['accent_hover']}; }}
QPushButton#playButton:disabled {{ background: {c['raised']}; color: {c['dim']}; }}
QToolButton {{ background: {c['raised']}; color: {c['text']}; border: 1px solid transparent;
    border-radius: 9px; padding: 6px 10px; font-weight: 600; }}
QToolButton:hover {{ background: {c['raised_hover']}; }}
QFrame#iconRail {{ background: {c['panel']}; border: 0px; border-radius: 14px; }}
QToolButton#railButton {{ background: transparent; color: {c['muted']}; border: 1px solid transparent;
    border-radius: 8px; padding: 5px 0px; font-size: 9px; font-weight: 600; min-width: 44px; max-width: 44px; }}
QToolButton#railButton:hover {{ background: {c['raised']}; color: {c['text']}; }}
QToolButton#railButton:checked {{ background: {c['accent']}; border-color: {c['accent_hover']}; color: {c['accent_text']}; }}
QFrame#sectionHeader {{ background: transparent; border: 0px; border-bottom: 1px solid {c['border']}; border-radius: 0px; }}
QFrame#sectionHeader:hover {{ background: {c['raised']}; }}
QLabel#sectionHeaderTitle {{ color: {c['text']}; font-size: 12px; font-weight: 700; background: transparent; }}
QWidget#sectionBody {{ background: transparent; }}
QToolButton#panelClose {{ background: transparent; border: 0px; border-radius: 8px; padding: 4px; }}
QToolButton#panelClose:hover {{ background: {c['raised']}; }}
QLabel#panelIcon {{ background: transparent; }}
QFrame#sourcePreview {{ background: {c['raised']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QToolButton::menu-indicator, QPushButton::menu-indicator {{ image: none; width: 0px; }}
QMenu {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border_strong']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 20px; border-radius: 7px; }}
QMenu::item:selected {{ background: {c['selection']}; }}
QMenu::item:disabled {{ color: {c['dim']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 6px; border-radius: 3px; }}
QMenu::indicator:checked {{ background: {c['accent']}; image: url({check}); }}
QMenu::indicator:unchecked {{ background: transparent; }}
QMenuBar {{ background: {c['window']}; color: {c['text']}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {c['selection']}; }}
QComboBox, QDoubleSpinBox, QSpinBox, QPlainTextEdit, QListWidget, QLineEdit {{
    background: {c['input']}; color: {c['text']}; border: 1px solid transparent;
    border-radius: 9px; padding: 5px 9px; selection-background-color: {c['selection']};
    selection-color: {c['text']}; }}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover, QPlainTextEdit:hover, QLineEdit:hover {{ border-color: {c['border_strong']}; }}
QPushButton:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QListWidget:focus,
QPlainTextEdit:focus, QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
QComboBox::drop-down {{ border: 0px; width: 22px; }}
QComboBox::down-arrow {{ image: url("{arrow('down')}"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border_strong']}; border-radius: 8px; padding: 4px;
    selection-background-color: {c['selection']}; selection-color: {c['text']}; outline: 0px; }}
QComboBox QAbstractItemView::item:disabled {{ color: {c['dim']}; }}
QListWidget::item {{ padding: 6px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
QListWidget::item:hover {{ background: {c['raised']}; }}
QToolTip {{ background: {c['tooltip']}; color: {c['text']}; border: 1px solid {c['border_strong']}; border-radius: 8px; padding: 7px; }}
QCheckBox {{ spacing: 9px; padding: 4px 0px; background: transparent; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 6px; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; image: url({check}); }}
QCheckBox::indicator:checked:disabled {{ background: {c['border_strong']}; border: 1px solid {c['border_strong']}; image: url({check_off}); }}
QCheckBox::indicator:unchecked {{ background: {c['input']}; border: 1px solid {c['border_strong']}; }}
QCheckBox:disabled {{ color: {c['dim']}; }}
QSlider::groove:horizontal {{ background: {c['border']}; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['accent']}; width: 14px; margin: -5px 0; border-radius: 7px; }}
QTabWidget::pane {{ border: 0px; background: {c['panel']}; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabWidget::tab-bar {{ left: 4px; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 7px 13px; margin: 4px 2px;
    border: 0px; border-radius: 9px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {c['text']}; background: {c['raised']}; }}
QTabBar::tab:selected {{ color: {c['text']}; background: {c['selection']}; }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 3px; }}
QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 3px; }}
QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 4px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QProgressBar {{ border: 0px; border-radius: 5px; background: {c['input']};
    color: {c['text']}; text-align: center; height: 14px; font-size: 10px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent_a']}, stop:1 {c['accent_b']}); border-radius: 5px; }}
QSplitter::handle {{ background: {c['window']}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QSplitter::handle:hover {{ background: {c['accent']}; }}
QDialog, QMessageBox {{ background: {c['panel']}; }}
QAbstractSpinBox {{ padding-right: 28px; min-height: 22px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 22px; background: transparent; border: 0px; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 9px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 9px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c['raised_hover']}; }}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{ background: {c['accent']}; }}
QAbstractSpinBox::up-arrow {{ image: url("{arrow('up')}"); width: 10px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url("{arrow('down')}"); width: 10px; height: 6px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url("{arrow('up', True)}"); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url("{arrow('down', True)}"); }}
"""
