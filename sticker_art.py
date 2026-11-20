"""exp.52 (the user: stickers like these Filmora ones, with an ending that undoes them the way they
appeared): the richer stickers, each built in stages from `a` (0..1: how much of it is built).
Their ending is the same build played backwards (stickers.built).

Each draw_* paints centred on the painter's origin, in a w × h box. They are our own drawings of
common things (an ellipse drawn with a marker, a magnifying glass, a clock, arrows).
"""
from __future__ import annotations

import math

RICH = ('Marker ellipse', 'Magnifier', 'Clock', 'Double arrow', 'Hook arrow')
ASPECT = {'Marker ellipse': .42, 'Magnifier': 1., 'Clock': 1., 'Double arrow': 1., 'Hook arrow': .72}
COLOR = {'Marker ellipse': '#5FB3A3', 'Magnifier': '#111111', 'Clock': '#B5AB98', 'Double arrow': '#D2D2D2',
         'Hook arrow': '#C9C9C9'}
THICKNESS = {'Marker ellipse': .016, 'Magnifier': .008, 'Clock': .004, 'Double arrow': .006, 'Hook arrow': .02}


def clamp(v, lo=0., hi=1.):
    return max(lo, min(hi, v))


def stage(a, start, end):
    """How far a stage running from `start` to `end` (shares of the build) is at `a`: 0..1."""
    return clamp((a - start) / max(1e-6, end - start))


def ease(p):
    p = clamp(p)
    return p * p * (3 - 2 * p)


def back_out(p, s=1.6):
    """Grows past its size a little, then settles (a pop)."""
    p = clamp(p) - 1
    return p * p * ((s + 1) * p + s) + 1


def main_line(shape):
    """The points (unit box) a hand follows to draw it, and that the line shapes draw along."""
    if shape == 'Marker ellipse':
        # a marker loop: starts top right, goes left round the bottom, and on past where it began
        pts = []
        start, turns = -math.pi * .38, 1.3
        for i in range(161):
            u = i / 160
            ang = start - 2 * math.pi * turns * u
            rx = .47 - .045 * u                           # exp.53: the second pass runs inside the
            ry = .44 + .03 * math.sin(u * 7) - .13 * u    # first, so the two strands cross apart
            pts.append((.5 + rx * math.cos(ang), .52 + ry * math.sin(ang) - .05 * u * u))
        return pts
    if shape == 'Hook arrow':
        pts = []
        for i in range(81):
            u = i / 80
            ang = math.radians(10 + 200 * u)            # from the right, under, and up on the left
            r = .4 + .05 * u
            pts.append((.52 + r * math.cos(ang), .42 + r * .9 * math.sin(ang)))
        return pts
    if shape == 'Double arrow':
        return [(.5, .5), (.06, .06)]
    if shape == 'Magnifier':
        c, r = (.4, .4), .3
        return [(c[0] + r * math.cos(math.radians(45) + 2 * math.pi * i / 72),
                 c[1] + r * math.sin(math.radians(45) + 2 * math.pi * i / 72)) for i in range(73)]
    if shape == 'Clock':
        return [(.5 + .48 * math.cos(-math.pi / 2 + 2 * math.pi * i / 72),
                 .5 + .48 * math.sin(-math.pi / 2 + 2 * math.pi * i / 72)) for i in range(73)]
    return [(.1, .5), (.9, .5)]


def by_hand(item):
    """exp.67: drawn by the hand (then every part is built the way one pen can draw it)."""
    import stickers
    return bool(stickers.hand_mode(item))


def _pt(q, w, h, flip=False):
    x, y = q
    return ((1 - x if flip else x) * w - w / 2, y * h - h / 2)


def _partial(points, share):
    import stickers
    return stickers._partial(points, share)


def draw(painter, item, w, h, frame_h, a, t=None):
    """Paint the sticker `item` built `a` (0..1); t: seconds (a clock's hands turn with it)."""
    if a <= 1e-3:                              # nothing left (the very end of its ending)
        return
    shape = item.get('shape')
    fn = {'Marker ellipse': _ellipse, 'Magnifier': _magnifier, 'Clock': _clock,
          'Double arrow': _double_arrow, 'Hook arrow': _hook}.get(shape)
    if fn:
        painter.save()
        fn(painter, item, w, h, frame_h, clamp(a), t)
        painter.restore()


def _pen(color, width, cap=True):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPen
    pen = QPen(QColor(color), max(.6, width))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap if cap else Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _path(points):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(x, y)
    return path


def _width(item, frame_h, default):
    return max(1., float(item.get('thickness', default) or default) * frame_h)


_NOISE = {}
_MARKER_CACHE = {}


def _noise(seed, size=256):
    """A fixed grain (0..1), the same every frame (the texture stays on the line, no flicker)."""
    key = (seed, size)
    if key not in _NOISE:
        import numpy as np
        _NOISE[key] = np.random.default_rng(seed).random((size, size), dtype=np.float32)
    return _NOISE[key]


def _blur(a, r):
    """A quick box blur (radius r pixels) of a 2-D array."""
    import numpy as np
    r = int(max(1, r))
    out = a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]; pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(out, pad, mode='edge'), axis=axis, dtype=np.float32)
        hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
        out = (hi - lo) / (2 * r + 1)
    return out


def _shift(a, dy, dx=0):
    import numpy as np
    out = np.zeros_like(a)
    h, w = a.shape
    dy, dx = int(round(dy)), int(round(dx))
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = a[ys, xs]
    return out


def textured_stroke(p, points, width, color, seed=7):
    """exp.53 (the user: the texture can be much better): a line drawn with a marker or chalk: a
    grainy body (light and dark specks), rough edges, a lighter top edge, a darker underside and
    a soft shadow under it. Rendered at the size it is shown (sharp in the export)."""
    import numpy as np
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    if len(points) < 2:
        return
    tr = p.worldTransform()
    scale = max(.25, math.sqrt(abs(tr.m11() * tr.m22() - tr.m12() * tr.m21())))
    xs = [q[0] for q in points]; ys = [q[1] for q in points]
    pad = width * 1.6
    left, top = min(xs) - pad, min(ys) - pad
    right, bottom = max(xs) + pad, max(ys) + pad + width * .6
    gw, gh = int(math.ceil((right - left) * scale)), int(math.ceil((bottom - top) * scale))
    if gw < 2 or gh < 2 or gw * gh > 6_000_000:
        return
    key = (tuple((round(x, 1), round(y, 1)) for x, y in points[::max(1, len(points) // 24)]), len(points),
           round(width, 2), color, round(scale, 3), seed)
    image = _MARKER_CACHE.get(key)
    if image is None:
        mask = QImage(gw, gh, QImage.Format.Format_Grayscale8); mask.fill(0)
        m = QPainter(mask); m.setRenderHint(QPainter.RenderHint.Antialiasing)
        m.scale(scale, scale); m.translate(-left, -top)
        m.setPen(_pen('white', width)); m.setBrush(Qt.BrushStyle.NoBrush)
        m.drawPath(_path(points)); m.end()
        stride = mask.bytesPerLine()
        A = np.frombuffer(mask.constBits(), np.uint8, count=stride * gh).reshape(gh, stride)[:, :gw].astype(np.float32) / 255.
        wpx = width * scale
        n = _noise(seed); n2 = _noise(seed + 1); n3 = _noise(seed + 2)
        ox, oy = int(left * scale), int(top * scale)
        yy = np.arange(gh)[:, None] + oy; xx = np.arange(gw)[None, :] + ox
        g = max(1, int(round(wpx / 16)))                                      # grain: about the line's
        N = n[(yy // g) % 256, (xx // g) % 256]                               # thickness / 16
        N2 = n2[(yy // g) % 256, (xx // g) % 256]
        if g > 1:                                                             # round grains, not squares
            N = _blur(N, g * .5); N2 = (_blur(N2, g * .5) - .5) * 1.9 + .5
        gc = max(2, int(wpx * .3))                                            # and slow lumps on the edges
        C = _blur(n3[(yy // gc) % 256, (xx // gc) % 256], gc * .6)
        soft = _blur(A, max(1, wpx * .06))
        body = np.clip((soft - .32 - .3 * (N - .5) - .5 * (C - .5)) / .22, 0, 1)   # rough, lumpy edges
        body *= soft > .14                                                    # no stray specks outside
        k = max(1., wpx * .3)
        light = np.clip(soft - _shift(soft, k), 0, 1)                        # the top edge
        dark = np.clip(soft - _shift(soft, -k), 0, 1)                         # the underside
        base = QColor(color)
        rgb = np.array([base.red(), base.green(), base.blue()], np.float32) / 255.
        tone = 1 + .22 * (N2 - .5)
        col = rgb[None, None, :] * tone[..., None]
        speck = (N2 > .82)[..., None]
        col = np.where(speck, col * .72 + .28 * np.array([1, 1, 1], np.float32), col)       # light specks
        col = np.where((N2 < .12)[..., None], col * .8, col)                                 # dark specks
        col = col + (1 - col) * (light[..., None] * .55)
        col = np.where(((N2 > .6) & (light > .25))[..., None], col + (1 - col) * .35, col)   # chalky top
        col = col * (1 - dark[..., None] * .42)
        shadow = _blur(_shift(A, wpx * .45, wpx * .12), max(1, wpx * .3)) * .55
        alpha = body + shadow * (1 - body)
        rgb_out = (col * body[..., None])                                      # shadow is black
        out = np.zeros((gh, gw, 4), np.uint8)
        out[..., 0] = np.clip(rgb_out[..., 2] * 255, 0, 255)                  # premultiplied BGRA
        out[..., 1] = np.clip(rgb_out[..., 1] * 255, 0, 255)
        out[..., 2] = np.clip(rgb_out[..., 0] * 255, 0, 255)
        out[..., 3] = np.clip(alpha * 255, 0, 255)
        image = QImage(out.tobytes(), gw, gh, gw * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        if len(_MARKER_CACHE) > 24:
            _MARKER_CACHE.clear()
        _MARKER_CACHE[key] = image
    p.drawImage(QRectF(left, top, gw / scale, gh / scale), image)


def _ellipse(p, item, w, h, frame_h, a, t):
    """A marker line round something (grainy, rough edged, shaded), drawn along its path."""
    pts = [_pt(q, w, h, item.get('flip')) for q in main_line('Marker ellipse')]
    part = _partial(pts, ease(a) if a < 1 else 1.)
    if len(part) < 2:
        return
    width = max(1.5, min(w, h) * .11 * float(item.get('thickness', THICKNESS['Marker ellipse']))
                / THICKNESS['Marker ellipse'])
    color = item.get('color', COLOR['Marker ellipse'])
    one = int(len(pts) / 1.3)                     # exp.53: each pass of the marker its own strand
    textured_stroke(p, part[:one + 1], width, color, seed=11)
    if len(part) > one:
        textured_stroke(p, part[one - 1:], width * .96, color, seed=11)


def _magnifier(p, item, w, h, frame_h, a, t):
    """A dot pops at the end of the handle, the handle draws to the glass, the glass grows."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor
    s = min(w, h)
    flip = item.get('flip')
    width = _width(item, frame_h, THICKNESS['Magnifier'])
    color = item.get('color', COLOR['Magnifier'])
    c = _pt((.4, .4), w, h, flip); r = .3 * s
    edge = _pt((.4 + .3 * math.cos(math.radians(45)), .4 + .3 * math.sin(math.radians(45))), w, h, flip)
    end = _pt((.9, .9), w, h, flip)
    dot = back_out(stage(a, 0., .18))
    if dot > 0:
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color))
        p.drawEllipse(QPointF(*end), width * 1.4 * dot, width * 1.4 * dot)
    handle = ease(stage(a, .14, .42))
    if handle > 0:
        p.setPen(_pen(color, width)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(*end), QPointF(end[0] + (edge[0] - end[0]) * handle, end[1] + (edge[1] - end[1]) * handle))
    if by_hand(item):                          # exp.67: the pen draws the glass round, from the handle
        sweep = stage(a, .42, 1.)
        if sweep > 0:
            from PySide6.QtCore import QRectF
            p.setPen(_pen(color, width * 1.45)); p.setBrush(Qt.BrushStyle.NoBrush)
            start = -45. if not flip else -135.            # Qt angles: from 3 o'clock, anticlockwise
            p.drawArc(QRectF(c[0] - r, c[1] - r, 2 * r, 2 * r), int(start * 16),
                      int((-360. if not flip else 360.) * sweep * 16))
        return
    glass = back_out(stage(a, .38, 1.))
    if glass > 0:
        p.setPen(_pen(color, width * 1.45)); p.setBrush(Qt.BrushStyle.NoBrush)   # exp.53: a heavier ring
        p.drawEllipse(QPointF(*c), r * glass, r * glass)


ROMAN = ('XII', 'I', 'II', 'III', 'IIII', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI')


def _clock(p, item, w, h, frame_h, a, t):
    """exp.53: an old station clock. It pops out of a dot into a disc; its rings (a railway track
    of little segments) and big thin Roman numerals appear round it; then the hands grow: an
    ornate hour hand, a minute hand with a teardrop, a thin second hand that ticks."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainterPath, QPolygonF
    s_ = min(w, h)
    R = .48 * s_
    face = QColor(item.get('color', COLOR['Clock']))
    ink = QColor('#1b1815')
    line = max(.6, s_ * .0045)
    hand = by_hand(item)
    disc = back_out(stage(a, 0., .28)) if not hand else (1. if a > 0 else 0.)
    if disc <= 0:
        return
    if hand and a < .28:                       # exp.67: the face appears as the pen goes round its rim
        sweep = stage(a, 0., .28)
        clip = QPainterPath(); clip.moveTo(0, 0)
        clip.arcTo(QRectF(-R * 1.05, -R * 1.05, 2.1 * R, 2.1 * R), 90., -360. * sweep); clip.closeSubpath()
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(face.darker(112)); p.drawEllipse(QPointF(0, 0), R * disc, R * disc)        # its rim
    p.setBrush(face); p.drawEllipse(QPointF(0, 0), R * .965 * disc, R * .965 * disc)
    rings = ease(stage(a, .22, .45)) if not hand else (1. if a > .28 else 0.)
    if rings > 0:
        p.save()
        if hand and a < .4:                    # exp.67: the rings appear as the pen goes round them
            sweep = stage(a, .28, .4)
            clip = QPainterPath(); clip.moveTo(0, 0)
            clip.arcTo(QRectF(-R * 1.05, -R * 1.05, 2.1 * R, 2.1 * R), 90., -360. * sweep); clip.closeSubpath()
            p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        grow = .85 + .15 * rings
        col = QColor(ink); col.setAlphaF(rings)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(_pen(col, line * 1.2))
        p.drawEllipse(QPointF(0, 0), R * .93 * grow, R * .93 * grow)                    # outer line
        for rr in (.6, .53):                                                           # the track
            p.drawEllipse(QPointF(0, 0), R * rr * grow, R * rr * grow)
        p.setPen(_pen(col, line * .8, cap=False))
        for i in range(60):
            ang = 2 * math.pi * i / 60
            r0, r1 = R * .53 * grow, R * .6 * grow
            p.drawLine(QPointF(r0 * math.cos(ang), r0 * math.sin(ang)), QPointF(r1 * math.cos(ang), r1 * math.sin(ang)))
        p.restore()
    numerals = stage(a, .4, .78)
    if numerals > 0:
        font = QFont('Times New Roman'); font.setPixelSize(max(4, int(R * .27)))
        font.setStretch(80); font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        for i, text in enumerate(ROMAN):
            # by hand: complete when the pen reaches it (the pen is at numeral k, k = numerals × 12)
            show = clamp((numerals * 12 - i) * 3 + 1) if hand else clamp(numerals * 12 - i)
            if show <= 0:
                continue
            col = QColor(ink); col.setAlphaF(show); p.setPen(col)
            ang = -math.pi / 2 + 2 * math.pi * i / 12
            cx, cy = R * .765 * math.cos(ang), R * .765 * math.sin(ang)
            p.save(); p.translate(cx, cy); p.rotate(math.degrees(ang) + 90)
            p.drawText(QRectF(-R * .25, -R * .16, R * .5, R * .32), Qt.AlignmentFlag.AlignCenter, text)
            p.restore()
    if hand:                                   # exp.67: the minute hand, then the hour hand, by the pen
        grow_minute, grow_hour = stage(a, .78, .9), stage(a, .9, 1.)
        grow_second = 1. if a >= .999 else 0.
    else:
        grow_minute = grow_hour = grow_second = back_out(stage(a, .74, 1.), 1.2)
    hands = max(grow_minute, grow_hour, grow_second)
    if hands <= 0:
        return
    run = (float(t) - float(item.get('start', 0))) if t is not None else 0.
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(ink)

    def along(ang, r, side=0.):
        ang -= math.pi / 2
        return QPointF(r * math.cos(ang) - side * math.sin(ang), r * math.sin(ang) + side * math.cos(ang))
    # the hour hand: a slim shaft, an open diamond and a spear tip
    hour = math.radians(300 + run * 1)
    L = R * .42 * grow_hour
    p.drawPolygon(QPolygonF([along(hour, -R * .06, R * .02), along(hour, L * .55, R * .012), along(hour, L * .62, R * .05),
                             along(hour, L * .72, R * .012), along(hour, L, 0), along(hour, L * .72, -R * .012),
                             along(hour, L * .62, -R * .05), along(hour, L * .55, -R * .012),
                             along(hour, -R * .06, -R * .02)]))
    hole = QPainterPath(); hole.addEllipse(along(hour, L * .62), R * .018, R * .018)
    p.setBrush(face); p.drawPath(hole); p.setBrush(ink)
    # the minute hand: thin, with a teardrop before its tip
    minute = math.radians(150 + run * 12)
    L = R * .7 * grow_minute
    p.drawPolygon(QPolygonF([along(minute, -R * .08, R * .014), along(minute, L * .7, R * .01), along(minute, L, 0),
                             along(minute, L * .7, -R * .01), along(minute, -R * .08, -R * .014)]))
    drop = QPainterPath()
    drop.moveTo(along(minute, L * .9))
    drop.cubicTo(along(minute, L * .82, R * .06), along(minute, L * .7, R * .05), along(minute, L * .7))
    drop.cubicTo(along(minute, L * .7, -R * .05), along(minute, L * .82, -R * .06), along(minute, L * .9))
    p.drawPath(drop)
    # the second hand: a hair with a little counterweight; it ticks once a second
    second = math.radians(int(run) * 6 + 40)
    p.setPen(_pen(ink, line * .8)); p.setBrush(Qt.BrushStyle.NoBrush)
    if grow_second > 0:
        p.drawLine(along(second, -R * .2), along(second, R * .82 * grow_second))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(ink)
    p.drawEllipse(along(second, -R * .16), R * .025, R * .025)
    p.drawEllipse(QPointF(0, 0), R * .045, R * .045)


def _head(p, tip, back, size, color, width, square=False):
    """An open arrowhead (two strokes meeting at `tip`), pointing away from `back`."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainterPath
    ang = math.atan2(tip[1] - back[1], tip[0] - back[0])
    pen = _pen(color, width)
    if square:                                             # exp.53: crisp corners and ends
        pen.setCapStyle(Qt.PenCapStyle.SquareCap); pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
    a1, a2 = ang + math.pi - math.radians(40), ang + math.pi + math.radians(40)
    path = QPainterPath(QPointF(tip[0] + size * math.cos(a1), tip[1] + size * math.sin(a1)))
    path.lineTo(*tip)
    path.lineTo(tip[0] + size * math.cos(a2), tip[1] + size * math.sin(a2))
    p.drawPath(path)


def _double_arrow(p, item, w, h, frame_h, a, t):
    """Two arrows growing out from the middle (↖ ↘): thick bars with square ends, then their
    heads."""
    from PySide6.QtCore import QPointF, Qt
    flip = item.get('flip')
    s_ = min(w, h)
    width = s_ * .045 * float(item.get('thickness', THICKNESS['Double arrow'])) / THICKNESS['Double arrow']
    color = item.get('color', COLOR['Double arrow'])
    size = s_ * .13
    for i, (near, far) in enumerate(DOUBLE_ARMS):
        n, f = _pt(near, w, h, flip), _pt(far, w, h, flip)
        if by_hand(item):                      # exp.67: one pen: an arm and its head, then the other
            grow = stage(a, DOUBLE_STAGES[i][0], DOUBLE_STAGES[i][1])
            head = stage(a, DOUBLE_STAGES[i][1], DOUBLE_STAGES[i][2])
        else:
            grow = ease(stage(a, 0., .7)); head = back_out(stage(a, .62, 1.))
        tip = (n[0] + (f[0] - n[0]) * grow, n[1] + (f[1] - n[1]) * grow)
        if grow > 0:
            pen = _pen(color, width); pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen); p.drawLine(QPointF(*n), QPointF(*tip))
        if head > 0:
            _head(p, tip, n, size * head, color, width, square=True)


DOUBLE_ARMS = (((.43, .43), (.07, .07)), ((.57, .57), (.93, .93)))
DOUBLE_STAGES = ((0., .36, .5), (.5, .86, 1.))     # by hand: arm, its head; then the other


def _hook(p, item, w, h, frame_h, a, t):
    """exp.53 (the user: the curved arrow was the weakest): one solid crescent, needle-sharp at
    its tail and full-bodied near the head, drawn along from the tail; then a thick, round-ended
    chevron for its head."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainterPath
    flip = bool(item.get('flip'))
    color = QColor(item.get('color', COLOR['Hook arrow']))
    s_ = min(w, h)
    fat = s_ * .2 * float(item.get('thickness', THICKNESS['Hook arrow'])) / THICKNESS['Hook arrow']
    cx, cy = .5 * w - w / 2, .4 * h - h / 2
    rx, ry = .42 * w, .5 * h
    a0, a1 = math.radians(-18), math.radians(172)         # from the right, under it, up on the left
    body = ease(stage(a, 0., .8))
    if body <= 0:
        return

    def at(u, off=0.):
        ang = a0 + (a1 - a0) * u
        # the centre line, and a point `off` outward of it
        nx, ny = math.cos(ang), math.sin(ang)
        x = cx + (rx + off) * nx
        y = cy + (ry + off) * ny
        return ((-x if flip else x), y)

    def half(u):                                          # thin at the tail, full from about half way
        return fat / 2 * min(1., (u / .55)) ** .75

    n = 72
    us = [body * i / n for i in range(n + 1)]
    outer = [at(u, half(u)) for u in us]
    inner = [at(u, -half(u)) for u in reversed(us)]
    path = QPainterPath(QPointF(*outer[0]))
    for q in outer[1:] + inner:
        path.lineTo(*q)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
    p.drawPath(path)
    end = at(body)
    if body >= .999:                                       # a round end under the head
        p.drawEllipse(QPointF(*end), half(1.) , half(1.))
    head = back_out(stage(a, .74, 1.)) if not by_hand(item) else stage(a, .8, 1.)
    if head > 0:
        before = at(.97)
        ang = math.atan2(end[1] - before[1], end[0] - before[0])
        tip = (end[0] + math.cos(ang) * fat * .55, end[1] + math.sin(ang) * fat * .55)
        arm = fat * 1.75 * head
        p.setPen(_pen(color, fat * .92 * max(.3, head))); p.setBrush(Qt.BrushStyle.NoBrush)
        for side in (-1, 1):
            q = ang + math.pi - side * math.radians(52)
            p.drawLine(QPointF(*tip), QPointF(tip[0] + arm * math.cos(q), tip[1] + arm * math.sin(q)))


def pen_at(item, w, h, frame_h, a, t=None):
    """exp.67 (the user: the sticker and the hand were not together): where the pen is (box
    points, centred, as draw paints) when the sticker is built `a` (0..1) by the hand: the same
    geometry and stages as its drawing."""
    shape = item.get('shape')
    flip = bool(item.get('flip'))
    a = clamp(a)
    s_ = min(w, h)
    if shape == 'Marker ellipse':
        pts = [_pt(q, w, h, flip) for q in main_line(shape)]
        return _partial(pts, ease(a) if a < 1 else 1.)[-1]
    if shape == 'Magnifier':
        c = _pt((.4, .4), w, h, flip); r = .3 * s_
        edge = _pt((.4 + .3 * math.cos(math.radians(45)), .4 + .3 * math.sin(math.radians(45))), w, h, flip)
        end = _pt((.9, .9), w, h, flip)
        if a < .14:
            return end                                     # the dot
        if a < .42:
            k = ease(stage(a, .14, .42))
            return (end[0] + (edge[0] - end[0]) * k, end[1] + (edge[1] - end[1]) * k)
        sweep = stage(a, .42, 1.)
        ang = math.radians(45.) + (2 * math.pi * sweep) * (1 if not flip else -1)   # screen y down
        if flip:
            ang = math.radians(135.) - 2 * math.pi * sweep
        return (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))
    if shape == 'Clock':
        R = .48 * s_
        if a < .28:                                        # round the rim, from 12 o'clock clockwise
            ang = -math.pi / 2 + 2 * math.pi * stage(a, 0., .28)
            return (R * math.cos(ang), R * math.sin(ang))
        if a < .4:                                         # the rings: round the track
            ang = -math.pi / 2 + 2 * math.pi * stage(a, .28, .4)
            return (R * .6 * math.cos(ang), R * .6 * math.sin(ang))
        if a < .78:                                        # each numeral as it appears
            k = min(11., stage(a, .4, .78) * 12)
            ang = -math.pi / 2 + 2 * math.pi * k / 12
            return (R * .765 * math.cos(ang), R * .765 * math.sin(ang))
        run = (float(t) - float(item.get('start', 0))) if t is not None else 0.
        if a < .9:                                         # out along the minute hand, then the hour hand
            ang, L = math.radians(150 + run * 12), R * .7 * stage(a, .78, .9)
        else:
            ang, L = math.radians(300 + run * 1), R * .42 * stage(a, .9, 1.)
        ang -= math.pi / 2
        return (L * math.cos(ang), L * math.sin(ang))
    if shape == 'Double arrow':
        for i, (near, far) in enumerate(DOUBLE_ARMS):
            g0, g1, g2 = DOUBLE_STAGES[i]
            if a <= g2 or i == 1:
                n, f = _pt(near, w, h, flip), _pt(far, w, h, flip)
                grow = stage(a, g0, g1)
                tip = (n[0] + (f[0] - n[0]) * grow, n[1] + (f[1] - n[1]) * grow)
                head = stage(a, g1, g2)
                if head <= 0:
                    return tip
                size = s_ * .13
                ang = math.atan2(tip[1] - n[1], tip[0] - n[0]) + math.pi - math.radians(40)
                return (tip[0] + size * head * math.cos(ang), tip[1] + size * head * math.sin(ang))
    if shape == 'Hook arrow':
        cx, cy = .5 * w - w / 2, .4 * h - h / 2
        rx, ry = .42 * w, .5 * h
        a0, a1 = math.radians(-18), math.radians(172)
        fat = s_ * .2 * float(item.get('thickness', THICKNESS['Hook arrow'])) / THICKNESS['Hook arrow']

        def at(u):
            ang = a0 + (a1 - a0) * u
            x, y = cx + rx * math.cos(ang), cy + ry * math.sin(ang)
            return ((-x if flip else x), y)
        body = ease(stage(a, 0., .8))
        if a < .8:
            return at(body)
        end, before = at(1.), at(.97)
        ang = math.atan2(end[1] - before[1], end[0] - before[0])
        tip = (end[0] + math.cos(ang) * fat * .55, end[1] + math.sin(ang) * fat * .55)
        head = stage(a, .8, 1.)
        q = ang + math.pi + math.radians(52)
        arm = fat * 1.75 * head
        return (tip[0] + arm * math.cos(q), tip[1] + arm * math.sin(q))
    pts = [_pt(q, w, h, flip) for q in main_line(shape)]
    return _partial(pts, a)[-1]
