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
    # Track buttons (exp.107): sound on / off, shown / hidden, timeline zoom.
    'volume': '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9.2a4 4 0 0 1 0 5.6"/>'
              '<path d="M18.2 6.8a7.5 7.5 0 0 1 0 10.4"/>',
    'volume-off': '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
    'eye': '<path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/>'
           '<circle cx="12" cy="12" r="2.8"/>',
    'eye-off': '<path d="M9.9 5.7A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.6 3.3"/>'
               '<path d="M6.4 7.1C3.9 8.8 2.5 12 2.5 12s3.5 6.5 9.5 6.5a9.3 9.3 0 0 0 4.4-1.1"/>'
               '<path d="M9.9 10a2.8 2.8 0 0 0 4 4"/><path d="M3.5 3.5l17 17"/>',
    'zoom-in': '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/><path d="M8.5 11h5M11 8.5v5"/>',
    'zoom-out': '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/><path d="M8.5 11h5"/>',
    'zoom-fit': '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/><path d="M9 12h6"/>',
    'folder': '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'open': '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v1"/>'
            '<path d="M3.5 7v10a2 2 0 0 0 2 2h12.3a2 2 0 0 0 1.9-1.4l1.8-5.6H8.2a2 2 0 0 0-1.9 1.4L3.5 19"/>',
    'home': '<path d="M4 11l8-6.5 8 6.5"/><path d="M6 9.5V19h12V9.5"/><path d="M10 19v-5h4v5"/>',
    # A curved arrow back: reset a setting.
    'reset': '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4v4h4"/>',
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
