"""Overlays: pictures and titles that appear on top of a scene at their own
time, with an entrance and an exit effect, at the same time as the hand draws
(like clips on extra tracks in a video editor).

An overlay belongs to a scene (it is drawn inside that scene's frame, so on the
board it flies with the camera). It is a dict:

    id        unique text
    kind      'image' or 'text'
    name      shown in the lists
    data      image: PNG/JPG as base64, or SVG text (format 'svg'), kept in the project
    format    'png' / 'svg'
    text, font, color, bold      text overlays
    x, y      centre, as fractions of the frame (0..1)
    size      image: width as a fraction of the frame; text: height of a line as a
              fraction of the frame height
    start, duration              seconds within the scene
    effect_in, in_seconds        'None', 'Fade', 'Pop', 'Slide from left' / right / top / bottom,
    effect_out, out_seconds      'Zoom', 'Spin'   (out: the same, played backwards)
    track     row on the timeline

Sharp: SVG pictures and text are drawn at the size they appear (vectors); a
photo is scaled from its own pixels.
"""
from __future__ import annotations

import base64
import hashlib
import math
import uuid
from collections import OrderedDict

EFFECTS = ('None', 'Fade', 'Pop', 'Slide from left', 'Slide from right', 'Slide from top', 'Slide from bottom',
           'Zoom', 'Spin')
DEFAULT_IN, DEFAULT_OUT = 'Pop', 'Fade'


def new_image(data, fmt, name, start=0., duration=3.):
    return dict(id=uuid.uuid4().hex[:10], kind='image', name=name, data=data, format=fmt,
                x=.5, y=.5, size=.35, start=float(start), duration=float(duration),
                effect_in=DEFAULT_IN, in_seconds=.5, effect_out=DEFAULT_OUT, out_seconds=.4, track=0)


def new_text(text='Your title', start=0., duration=3.):
    return dict(id=uuid.uuid4().hex[:10], kind='text', name=text[:30], text=text, font='Segoe UI',
                color='#1E2A3A', bold=True, x=.5, y=.18, size=.09, start=float(start), duration=float(duration),
                effect_in='Slide from top', in_seconds=.5, effect_out=DEFAULT_OUT, out_seconds=.4, track=0)


def image_item_from_file(path, start=0., duration=3.):
    """An image overlay from a PNG / JPG / WebP / SVG file (the picture is kept in the project)."""
    from pathlib import Path
    path = Path(path)
    if path.suffix.lower() == '.svg':
        return new_image(path.read_text(encoding='utf-8', errors='replace'), 'svg', path.stem, start, duration)
    from PIL import Image
    import io
    with Image.open(path) as im:
        im = im.convert('RGBA')
        if max(im.size) > 2600:                         # keep projects small enough
            im.thumbnail((2600, 2600))
        buf = io.BytesIO(); im.save(buf, 'PNG')
    return new_image(base64.b64encode(buf.getvalue()).decode('ascii'), 'png', path.stem, start, duration)


# ------------------------------------------------------------ timing and effects

def _ease_out(p):
    return 1 - (1 - p) ** 3


def _back_out(p):
    c = 1.70158
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def _effect(kind, p):
    """(opacity, dx, dy in frames, scale, rotation) for an entrance at progress p (0..1)."""
    p = max(0., min(1., p))
    if kind == 'Fade':
        return p, 0., 0., 1., 0.
    if kind == 'Pop':
        return min(1., p * 3), 0., 0., max(0., _back_out(p)), 0.
    if kind == 'Zoom':
        return min(1., p * 2), 0., 0., _ease_out(p), 0.
    if kind == 'Spin':
        e = _ease_out(p)
        return min(1., p * 2), 0., 0., e, -180 * (1 - e)
    if kind.startswith('Slide from'):
        side = kind.rsplit(' ', 1)[-1]
        away = 1 - _ease_out(p)
        dx = {'left': -1.2, 'right': 1.2}.get(side, 0.) * away
        dy = {'top': -1.2, 'bottom': 1.2}.get(side, 0.) * away
        return 1., dx, dy, 1., 0.
    return 1., 0., 0., 1., 0.


def state_at(item, t):
    """How the overlay looks at time t (seconds in the scene), or None when it is not shown."""
    start, length = float(item.get('start', 0)), max(.05, float(item.get('duration', 3)))
    if t < start or t > start + length:
        return None
    local = t - start
    tin = min(float(item.get('in_seconds', .5)), length / 2) if item.get('effect_in', 'None') != 'None' else 0
    tout = min(float(item.get('out_seconds', .4)), length / 2) if item.get('effect_out', 'None') != 'None' else 0
    if tin and local < tin:
        return _effect(item['effect_in'], local / tin)
    if tout and local > length - tout:
        return _effect(item['effect_out'], (length - local) / tout)
    return 1., 0., 0., 1., 0.


def end_of(item):
    return float(item.get('start', 0)) + float(item.get('duration', 3))


# ------------------------------------------------------------ pictures

_SOURCES = OrderedDict()           # sharp pictures at the size they are drawn
_LIMIT = 40


def _key(item, *extra):
    raw = (item.get('data') or item.get('text') or '')
    digest = hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:16]
    return (item.get('kind'), digest, item.get('font'), item.get('color'), bool(item.get('bold'))) + extra


def _remember(key, image):
    _SOURCES[key] = image
    while len(_SOURCES) > _LIMIT:
        _SOURCES.popitem(last=False)
    return image


def natural_aspect(item):
    """Height / width of the picture (text: of the whole text block)."""
    if item.get('kind') == 'text':
        img = picture(item, 400)
        return img.height() / max(1, img.width())
    key = _key(item, 'aspect')
    if key in _SOURCES:
        return _SOURCES[key]
    if item.get('format') == 'svg':
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(item['data'].encode('utf-8')))
        size = r.defaultSize()
        aspect = size.height() / max(1, size.width()) if size.width() > 0 else 1.
    else:
        img = _raster(item)
        aspect = img.height() / max(1, img.width())
    _SOURCES[key] = aspect
    return aspect


def _raster(item):
    key = _key(item, 'raster')
    if key in _SOURCES:
        return _SOURCES[key]
    from PySide6.QtGui import QImage
    img = QImage()
    img.loadFromData(base64.b64decode(item.get('data') or ''))
    return _remember(key, img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))


def picture(item, width_px):
    """The overlay's picture, at least `width_px` wide (text: see text_picture)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    width_px = max(4, int(round(width_px)))
    if item.get('kind') == 'text':
        return text_picture(item, width_px)
    step = int(round(2 ** (math.ceil(math.log2(width_px) * 4) / 4)))   # a few sizes, kept
    key = _key(item, 'pic', step)
    if key in _SOURCES:
        _SOURCES.move_to_end(key); return _SOURCES[key]
    if item.get('format') == 'svg':
        from PySide6.QtCore import QByteArray, QRectF
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(item['data'].encode('utf-8')))
        h = max(1, round(step * natural_aspect(item)))
        img = QImage(step, h, QImage.Format.Format_ARGB32_Premultiplied); img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p, QRectF(0, 0, step, h)); p.end()
    else:
        src = _raster(item)
        img = src.scaledToWidth(step, Qt.TransformationMode.SmoothTransformation)
    return _remember(key, img)


def text_picture(item, line_px):
    """The text drawn with a line height of `line_px` pixels (several lines are centred)."""
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
    line_px = max(4, int(round(line_px)))
    key = _key(item, 'text', line_px)
    if key in _SOURCES:
        _SOURCES.move_to_end(key); return _SOURCES[key]
    font = QFont(item.get('font') or 'Segoe UI')
    font.setPixelSize(line_px)
    font.setBold(bool(item.get('bold', True)))
    fm = QFontMetricsF(font)
    lines = (item.get('text') or ' ').split('\n')
    w = max(1., max(fm.horizontalAdvance(l) for l in lines)) + line_px * .2
    h = fm.lineSpacing() * len(lines) + line_px * .1
    img = QImage(int(math.ceil(w)), int(math.ceil(h)), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(font); p.setPen(QColor(item.get('color') or '#1E2A3A'))
    p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, '\n'.join(lines))
    p.end()
    return _remember(key, img)


def box(item, width, height):
    """(x, y, w, h) of the overlay in a width × height frame, without effects."""
    if item.get('kind') == 'text':
        line = float(item.get('size', .09)) * height
        img = text_picture(item, line)
        w, h = img.width(), img.height()
    else:
        w = float(item.get('size', .35)) * width
        h = w * natural_aspect(item)
    cx, cy = float(item.get('x', .5)) * width, float(item.get('y', .5)) * height
    return cx - w / 2, cy - h / 2, w, h


def paint(frame, items, t):
    """Draw the overlays visible at t (seconds) onto `frame` (in place) and return it."""
    if not items:
        return frame
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainter
    W, H = frame.width(), frame.height()
    p = None
    for item in sorted(items, key=lambda i: (int(i.get('track', 0)), float(i.get('start', 0)))):
        state = state_at(item, t)
        if state is None:
            continue
        opacity, dx, dy, scale, rotation = state
        if opacity <= 0 or scale <= 0:
            continue
        x, y, w, h = box(item, W, H)
        if w < 1 or h < 1:
            continue
        if p is None:
            p = QPainter(frame)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        img = text_picture(item, float(item.get('size', .09)) * H) if item.get('kind') == 'text' \
            else picture(item, w * max(1., scale))
        p.save()
        p.setOpacity(opacity)
        p.translate(QPointF(x + w / 2 + dx * W, y + h / 2 + dy * H))
        if rotation:
            p.rotate(rotation)
        p.scale(scale, scale)
        p.drawImage(QRectF(-w / 2, -h / 2, w, h), img)
        p.restore()
    if p is not None:
        p.end()
    return frame
