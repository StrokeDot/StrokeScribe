"""Overlays: pictures and titles that appear on top of a scene at their own
time, with an entrance and an exit effect, at the same time as the hand draws
(like clips on extra tracks in a video editor).

An overlay belongs to a scene (it is drawn inside that scene's frame, so on the
board it flies with the camera). It is a dict:

    id        unique text
    kind      'image', 'text', 'eraser' or 'sticker' (exp.27: stickers.py)
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


def new_eraser(target, target_k, name, start=0., duration=3., mode='zigzag', track=0):
    """exp.186 (the user): an Eraser clip on the timeline, like a text: it rubs out one element
    (target: its uid) on its page, between start and start + duration, whether or not the
    camera shows it (eraser_clips.py)."""
    return dict(id=uuid.uuid4().hex[:10], kind='eraser', name=name, target=target, target_k=int(target_k),
                mode=mode, start=float(start), duration=float(duration), track=int(track))


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
    # exp.121: with no way out (None), it stays after its clip, like the drawings do, until
    # the camera moves to another page ('_until', worked out by the window from the timeline).
    until = start + length
    if item.get('effect_out', 'None') == 'None' and not item.get('cut_end'):   # exp.208: cut (Ctrl+B) ends there
        until = max(until, float(item.get('_until', until)))
    if t < start or t > until:
        return None
    if t > start + length:
        return 1., 0., 0., 1., 0.
    local = t - start
    tin = min(float(item.get('in_seconds', .5)), length / 2) if item.get('effect_in', 'None') != 'None' else 0
    tout = min(float(item.get('out_seconds', .4)), length / 2) if item.get('effect_out', 'None') != 'None' else 0
    if tin and local < tin:
        return _effect(item['effect_in'], local / tin)
    if tout and local > length - tout:
        return _effect(item['effect_out'], (length - local) / tout)
    return 1., 0., 0., 1., 0.


def on_screen(item, t):
    """exp.29: shown at t, or its hand is on its way to draw it / back (a sticker drawn by the hand)."""
    if state_at(item, t) is not None:
        return True
    if item.get('kind') == 'sticker' and item.get('drawing', 'Animated') != 'Animated':
        import stickers
        span = stickers.busy(item)
        return span is not None and span[0] <= t <= span[1]
    return False


def from_time(item):
    """exp.29: when it starts to matter on screen (a sticker's hand comes in before it)."""
    start = float(item.get('start', 0))
    if item.get('kind') == 'sticker' and item.get('drawing', 'Animated') != 'Animated':
        import stickers
        span = stickers.busy(item)
        if span is not None:
            return min(start, span[0])
    return start


def end_of(item):
    return float(item.get('start', 0)) + float(item.get('duration', 3))


def shown_until(item):
    """The clip's end, or later when it stays on screen (no way out: exp.121); exp.29: or until a
    sticker's hand has gone."""
    end = end_of(item)
    if item.get('kind') == 'sticker' and item.get('drawing', 'Animated') != 'Animated':
        import stickers
        span = stickers.busy(item)
        if span is not None:
            end = max(end, span[1])
    if item.get('effect_out', 'None') == 'None' and not item.get('cut_end'):
        end = max(end, float(item.get('_until', end)))
    return end


def cut(item, seconds, new_id):
    """exp.208 (the user, like Filmora's Ctrl+B): the clip in two at `seconds`: the first
    part ends there with no way out, the second goes on from there with no way in (so
    nothing changes on screen at the cut). None when `seconds` is not inside it."""
    start, end = float(item.get('start', 0)), end_of(item)
    if not start + .1 <= float(seconds) <= end - .1:
        return None
    first = dict(item, duration=round(float(seconds) - start, 3), effect_out='None', cut_end=True)
    second = dict(item, id=new_id, start=round(float(seconds), 3), duration=round(end - float(seconds), 3),
                  effect_in='None')
    second.pop('_until', None); first.pop('_until', None)
    return first, second


# ------------------------------------------------------------ pictures

_SOURCES = OrderedDict()           # sharp pictures at the size they are drawn
_LIMIT = 40


_DIGESTS = {}


def data_digest(raw):
    """exp.204: a short name for a picture's data, worked out once per picture (a picture is
    over a megabyte of text; hashing or printing it for every frame made StrokeScribe lag)."""
    key = (id(raw), len(raw))
    found = _DIGESTS.get(key)
    if found is None or found[0] is not raw:
        found = (raw, hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:16])
        if len(_DIGESTS) > 256:
            _DIGESTS.clear()
        _DIGESTS[key] = found
    return found[1]


def light(item):
    """exp.204: the item for fingerprints: its picture data replaced by a short name."""
    if not item or not item.get('data'):
        return item
    return dict(item, data=data_digest(item['data']))


def _key(item, *extra):
    raw = (item.get('data') or item.get('text') or '')
    digest = data_digest(raw)
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
    if item.get('kind') == 'sticker':
        return float(item.get('aspect', .4))
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
    if item.get('kind') == 'eraser':
        return 0., 0., 0., 0.                     # exp.186: nothing on the screen to pick
    if item.get('kind') == 'text':
        line = float(item.get('size', .09)) * height
        img = text_picture(item, line)
        w, h = img.width(), img.height()
    elif item.get('kind') == 'sticker':          # exp.27: its own shape (stickers.py)
        w = float(item.get('size', .3)) * width
        h = max(w * float(item.get('aspect', .4)), float(item.get('thickness', .012)) * height * 3)
    else:
        w = float(item.get('size', .35)) * width
        h = w * natural_aspect(item)
    cx, cy = float(item.get('x', .5)) * width, float(item.get('y', .5)) * height
    return cx - w / 2, cy - h / 2, w, h


# exp.60 (the user: stickers with shadows): a soft shadow under the sticker. distance and blur
# are shares of the video height; angle: where the shadow falls (0 right, 90 down).
SHADOW = dict(color='#000000', opacity=.45, distance=.012, angle=60., blur=.01)


def shadow_of(item):
    """The sticker's shadow settings (with the defaults), or None when it has none."""
    sh = item.get('shadow')
    if not sh or not sh.get('on', True):
        return None
    return dict(SHADOW, **{k: v for k, v in sh.items() if k != 'on'})


def _blur_alpha(alpha, radius):
    """Three box blurs (close to a Gaussian) of a float alpha array."""
    import numpy as np
    r = int(max(0, round(radius)))
    if r < 1:
        return alpha
    out = alpha
    for _ in range(3):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]; pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(out, pad, mode='constant'), axis=axis, dtype=np.float32)
            n = out.shape[axis]
            if axis == 0:
                out = (c[2 * r + 1:2 * r + 1 + n] - c[:n]) / (2 * r + 1)
            else:
                out = (c[:, 2 * r + 1:2 * r + 1 + n] - c[:, :n]) / (2 * r + 1)
    return out


def _sticker_with_shadow(p, item, x, y, w, h, W, H, t, opacity, dx, dy, scale, rotation):
    """Draw the sticker on its own layer, then its blurred shadow under it."""
    import math
    import numpy as np
    import stickers
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter
    sh = shadow_of(item)
    dist = float(sh['distance']) * H
    blur = max(0., float(sh['blur']) * H)
    angle = math.radians(float(sh['angle']))
    ox, oy = math.cos(angle) * dist, math.sin(angle) * dist
    draw_h = w * float(item.get('aspect', .4))
    radius = .5 * math.hypot(w, max(h, draw_h)) * max(1., scale) + float(item.get('thickness', .012)) * H * 3 + 4
    margin = int(math.ceil(radius + blur * 2 + 2))
    size = 2 * margin
    if size > 4096:                               # very big: no shadow rather than a huge layer
        margin = 2048; size = 4096
    cx, cy = x + w / 2 + dx * W, y + h / 2 + dy * H
    layer = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied); layer.fill(0)
    lp = QPainter(layer)
    lp.setRenderHint(QPainter.RenderHint.Antialiasing); lp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    lp.translate(QPointF(margin, margin))
    if rotation or item.get('rotation'):
        lp.rotate(rotation + float(item.get('rotation', 0) or 0))
    lp.scale(scale, scale)
    stickers.draw(lp, item, w, draw_h, H, t=t)
    lp.end()
    a = np.frombuffer(layer.constBits(), np.uint8).reshape(size, layer.bytesPerLine() // 4, 4)[:, :size, 3]
    if a.any():
        alpha = _blur_alpha(a.astype(np.float32) / 255., blur / 2.)
        col = QColor(sh['color'])
        shade = np.empty((size, size, 4), np.uint8)
        al = np.clip(alpha, 0, 1)
        shade[..., 3] = (al * 255).astype(np.uint8)
        shade[..., 2] = (al * col.red()).astype(np.uint8)       # premultiplied BGRA
        shade[..., 1] = (al * col.green()).astype(np.uint8)
        shade[..., 0] = (al * col.blue()).astype(np.uint8)
        shadow = QImage(shade.tobytes(), size, size, size * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        p.save()
        p.setOpacity(opacity * max(0., min(1., float(sh['opacity']))))
        p.drawImage(QPointF(cx - margin + ox, cy - margin + oy), shadow)
        p.restore()
    p.save()
    p.setOpacity(opacity)
    p.drawImage(QPointF(cx - margin, cy - margin), layer)
    p.restore()


def paint(frame, items, t, hands=True):
    """Draw the overlays visible at t (seconds) onto `frame` (in place) and return it.
    exp.29: hands=False: no hand drawing a sticker (the Drawing only export)."""
    if not items:
        return frame
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainter
    W, H = frame.width(), frame.height()
    p = None
    for item in sorted(items, key=lambda i: (int(i.get('track', 0)), float(i.get('start', 0)))):
        if item.get('kind') == 'eraser':          # exp.186: not drawn on the screen (eraser_clips)
            continue
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
        if item.get('kind') == 'sticker' and shadow_of(item):      # exp.60: with its shadow
            _sticker_with_shadow(p, item, x, y, w, h, W, H, t, opacity, dx, dy, scale, rotation)
            continue
        if item.get('kind') == 'sticker':         # exp.27: drawn as lines, as much as is drawn by now
            import stickers
            p.save()
            p.setOpacity(opacity)
            p.translate(QPointF(x + w / 2 + dx * W, y + h / 2 + dy * H))
            if rotation or item.get('rotation'):
                p.rotate(rotation + float(item.get('rotation', 0) or 0))
            p.scale(scale, scale)
            stickers.draw(p, item, w, w * float(item.get('aspect', .4)), H, t=t)
            p.restore()
            continue
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
    if hands:                                     # exp.29: the hand drawing a sticker, on top
        paint_hands(frame, items, t)
    return frame


def hand_items(items, t, W, H):
    """exp.30: the stickers whose hand is on screen at t."""
    import stickers
    return [i for i in items or () if i.get('kind') == 'sticker' and i.get('drawing', 'Animated') != 'Animated'
            and not i.get('off') and stickers.hand_tip(i, t, W, H) is not None]


def paint_hands(out, items, t, size=None, to_screen=None):
    """exp.30: the hands drawing stickers, painted on `out` (the screen). size: (W, H) of the frame
    the stickers are on (a page the camera zooms; default: out), to_screen maps its points onto
    `out`. The hand has the screen's size, like the elements' hands."""
    W, H = size if size is not None else (out.width(), out.height())
    drawn = hand_items(items, t, W, H)
    if not drawn:
        return out
    import stickers
    from PySide6.QtGui import QPainter
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for item in drawn:
        stickers.paint_hand(p, item, t, W, H, out.width(), to_screen)
    p.end()
    return out
