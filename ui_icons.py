"""Outline icons for the rails and panel headers (drawn from inline SVG).

Simple 24x24 stroke icons in the same spirit as the panel mockups. They are
tinted at runtime, so they follow light and dark mode.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

_PATHS = {
    # A framed picture: Source.
    'source': '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="15.5" cy="8.5" r="1.8"/>'
              '<path d="M3 17l5.5-5.5 4.5 4.5 2.5-2.5L21 19"/>',
    # Play in a circle: Animation.
    'animation': '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l5.5-3.5z"/>',
    # An open hand: Hand.
    'hand': '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11"/><path d="M11 10.5V4a1.5 1.5 0 0 1 3 0v6.5"/>'
            '<path d="M14 10.5V5.5a1.5 1.5 0 0 1 3 0V12"/>'
            '<path d="M17 9.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-1.2a6 6 0 0 1-4.7-2.3L3.6 15.4'
            'a1.6 1.6 0 0 1 2.4-2.1L8 15"/>',
    # A speaker with waves: Sound (drawing sounds).
    'sound': '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6"/>'
             '<path d="M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    # Two notes: Music (voiceover / music track).
    'music': '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    # A big T: Text.
    'text': '<path d="M5 6.5V4.5h14v2"/><path d="M12 4.5v15"/><path d="M9 19.5h6"/>',
    # A camera: Camera.
    'camera': '<path d="M3.5 8.5a2 2 0 0 1 2-2h2.2l1.6-2h5.4l1.6 2h2.2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13'
              'a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="3.6"/>',
    # Sparkles: AI.
    'ai': '<path d="M11 3.5l1.6 4.4 4.4 1.6-4.4 1.6L11 15.5l-1.6-4.4L5 9.5l4.4-1.6z"/>'
          '<path d="M18 14l.8 2.2 2.2.8-2.2.8L18 20l-.8-2.2-2.2-.8 2.2-.8z"/>',
    # Arrow out of a tray: Export.
    'export': '<path d="M12 15V3"/><path d="M7 8l5-5 5 5"/><path d="M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/>',
    # A pencil: Handwriting.
    'handwriting': '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/><path d="M14.5 5.5l3 3"/>',
    # A trash can: remove.
    'trash': '<path d="M4 7h16"/><path d="M9.5 7V4.5h5V7"/><path d="M6 7l1 13h10l1-13"/>'
             '<path d="M10 11v6M14 11v6"/>',
    # Close, collapse, fullscreen, eyedropper, image placeholder.
    'close': '<path d="M6 6l12 12M18 6L6 18"/>',
    'collapse-left': '<path d="M13 6l-6 6 6 6"/><path d="M19 6l-6 6 6 6"/>',
    'collapse-right': '<path d="M11 6l6 6-6 6"/><path d="M5 6l6 6-6 6"/>',
    'fullscreen': '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    'exit-fullscreen': '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
    'eyedropper': '<path d="M14.5 4.5l5 5"/><path d="M17 2.5a2.1 2.1 0 0 1 3 3l-2 2-3-3z"/>'
                  '<path d="M15 7.5L6 16.5 5 20l3.5-1 9-9"/>',
    'image': '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="15.5" cy="8.5" r="1.8"/>'
             '<path d="M3 17l5.5-5.5 4.5 4.5 2.5-2.5L21 19"/>',
}

NAMES = tuple(_PATHS)


def svg(name, color='#E8E6F0', width=1.7):
    body = _PATHS[name]
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>')


def pixmap(name, color='#E8E6F0', size=24, ratio=2.0):
    """A crisp (HiDPI) pixmap of an icon in one colour."""
    from PySide6.QtSvg import QSvgRenderer
    px = max(1, round(size * ratio))
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, color).encode('utf-8')))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    out = QPixmap.fromImage(image)
    out.setDevicePixelRatio(ratio)
    return out


def icon(name, color='#E8E6F0', active=None, size=24):
    """QIcon with a normal colour and (optionally) a colour for the checked/active state."""
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, active or color, size), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(pixmap(name, active or color, size), QIcon.Mode.Active, QIcon.State.On)
    return result
