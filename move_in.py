"""Moving an element in instead of drawing it ("Comes in" in the Animation tab).

Two things on top of the plain entrance effects (frame_render.ENTRANCES):

* What moves in: the whole picture (lines and colours together), or only the
  lines, after which the painting hand paints the colours as usual.
* The move-in hand: on the Slide effects a hand carries the picture in, holding
  the edge it comes from, lets go and leaves the way it came.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

PART_ALL, PART_LINES = 'all', 'lines'
PARTS = {'The whole picture': PART_ALL, 'Only the lines, then paint the colours': PART_LINES}

CARRY = .72          # share of the move-in time the hand carries the picture; then it lets go and leaves
SIDES = {'Slide from left': 'left', 'Slide from right': 'right',
         'Slide from top': 'top', 'Slide from bottom': 'bottom'}
# The hand picture is drawn for "comes from below" (its arm hangs down); turn it for other sides.
ANGLES = {'bottom': 0., 'top': 180., 'left': 90., 'right': -90.}
AWAY = {'bottom': (0., 1.), 'top': (0., -1.), 'left': (-1., 0.), 'right': (1., 0.)}

BUILTIN_HAND = 'Built-in hand (placeholder)'
DEFAULT_GRIP = (.08, .13)          # where the built-in hand holds things (its pen tip)


def part_of(opts):
    """'lines' only when there are colours to paint afterwards."""
    if (opts.get('entrance_part') or PART_ALL) != PART_LINES:
        return PART_ALL
    image = opts.get('final_image')
    if image is None or image.isNull():
        return PART_ALL
    return PART_LINES


def carried(opts, kind):
    """The side the hand carries the picture in from, or None (no hand for this effect)."""
    if opts.get('move_hand') is None or opts.get('layers', 'all') == 'art':
        return None
    return SIDES.get(kind)


def picture_progress(p, side):
    """Progress of the picture's effect: with a hand it arrives early, then the hand leaves."""
    if side is None:
        return p
    return min(1., p / CARRY)


_BOXES = OrderedDict()


def alpha_box(image):
    """(left, top, right, bottom) of the visible part of `image`, as fractions; whole frame if empty."""
    key = image.cacheKey()
    if key in _BOXES:
        return _BOXES[key]
    box = (0., 0., 1., 1.)
    try:
        import numpy as np
        from PySide6.QtGui import QImage
        im = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        w, h = im.width(), im.height()
        a = np.frombuffer(im.constBits(), np.uint8, im.bytesPerLine() * h).reshape(h, im.bytesPerLine())
        alpha = a[:, 3:w * 4:4] > 8
        rows, cols = np.flatnonzero(alpha.any(1)), np.flatnonzero(alpha.any(0))
        if rows.size and cols.size:
            box = (cols[0] / w, rows[0] / h, (cols[-1] + 1) / w, (rows[-1] + 1) / h)
    except Exception:
        pass
    while len(_BOXES) > 32:
        _BOXES.popitem(last=False)
    _BOXES[key] = box
    return box


def grip_point(box, side):
    """Where the hand holds the picture: the middle of the edge it comes from."""
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    return {'bottom': (cx, bottom), 'top': (cx, top), 'left': (left, cy), 'right': (right, cy)}[side]


def hand_position(box, side, p, picture_offset):
    """(x, y) of the hand's grip in frame fractions at move-in progress p (0..1).

    `picture_offset` is where the picture is at this moment (dx, dy fractions)."""
    gx, gy = grip_point(box, side)
    x, y = gx + picture_offset[0], gy + picture_offset[1]
    if p > CARRY:                                   # let go: back the way it came, off the frame
        q = (p - CARRY) / (1 - CARRY)
        q = q * q * (3 - 2 * q)
        ax, ay = AWAY[side]
        x, y = x + ax * 1.4 * q, y + ay * 1.4 * q
    return x, y


def draw_hand(frame, hand, grip, share, point, side):
    """The move-in hand on `frame`, its grip at `point` (fractions), sized `share` of the width."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainter
    if hand is None or hand.isNull():
        return frame
    w, h = frame.width(), frame.height()
    hw = max(1., share * w)
    hh = hw * hand.height() / max(1, hand.width())
    painter = QPainter(frame)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.translate(QPointF(point[0] * w, point[1] * h))
    painter.rotate(ANGLES[side])
    painter.drawImage(QRectF(-grip[0] * hw, -grip[1] * hh, hw, hh), hand)
    painter.end()
    return frame


# ------------------------------------------------------------ the hand picture

_HANDS = {}


def builtin_hand_path():
    return Path(__file__).resolve().parent / 'assets' / 'default_hand.png'


def move_hand(settings):
    """(image, grip) for the move-in hand chosen in the Hand tab, or (None, None) when it is off.

    Cached, so the same settings give the very same image (frame caches compare cacheKey)."""
    s = settings
    if not s.get('move_hand', False):
        return None, None
    path = str(s.get('move_hand_path') or '') or str(builtin_hand_path())
    try:
        stamp = Path(path).stat().st_mtime
    except OSError:
        path = str(builtin_hand_path())
        try:
            stamp = Path(path).stat().st_mtime
        except OSError:
            return None, None
    grip = (float(s.get('move_hand_gx', DEFAULT_GRIP[0])), float(s.get('move_hand_gy', DEFAULT_GRIP[1])))
    left = bool(s.get('left_handed'))
    key = (path, stamp, grip, left)
    if key not in _HANDS:
        from PySide6.QtGui import QImage
        image = QImage(path)
        if image.isNull():
            return None, None
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        if left:
            from tools_kit import mirrored
            image = mirrored(image)
        if len(_HANDS) > 8:
            _HANDS.clear()
        _HANDS[key] = image
    image = _HANDS[key]
    return image, ((1 - grip[0]) if left else grip[0], grip[1])
