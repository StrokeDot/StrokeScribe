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
            rx = .47 - .025 * u
            ry = .44 + .03 * math.sin(u * 7) - .05 * u
            pts.append((.5 + rx * math.cos(ang), .52 + ry * math.sin(ang) - .03 * u * u))
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


def _ellipse(p, item, w, h, frame_h, a, t):
    """A marker line round something: drawn along, with a darker edge and a lighter middle."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    pts = [_pt(q, w, h, item.get('flip')) for q in main_line('Marker ellipse')]
    part = _partial(pts, ease(a) if a < 1 else 1.)
    if len(part) < 2:
        return
    width = _width(item, frame_h, THICKNESS['Marker ellipse'])
    base = QColor(item.get('color', COLOR['Marker ellipse']))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = _path(part)
    p.setPen(_pen(base.darker(160), width * 1.18)); p.drawPath(path)          # the edge
    p.setPen(_pen(base, width)); p.drawPath(path)                              # the ink
    light = QColor(base.lighter(125)); light.setAlpha(150)
    p.setPen(_pen(light, width * .38)); p.drawPath(path)                       # the wet middle


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
    glass = back_out(stage(a, .38, 1.))
    if glass > 0:
        p.setPen(_pen(color, width)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(*c), r * glass, r * glass)


ROMAN = ('XII', 'I', 'II', 'III', 'IIII', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI')


def _clock(p, item, w, h, frame_h, a, t):
    """It pops out of a dot into a disc, its rings and numerals appear round it, then the hands
    grow; the hands keep turning (the second hand ticks round)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont
    s = min(w, h)
    R = .48 * s
    face = QColor(item.get('color', COLOR['Clock']))
    ink = QColor('#1d1a17')
    line = max(.6, s * .006)
    disc = back_out(stage(a, 0., .28))
    if disc <= 0:
        return
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(face)
    p.drawEllipse(QPointF(0, 0), R * disc, R * disc)
    rings = ease(stage(a, .22, .45))
    if rings > 0:
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, rr in enumerate((.96, .62, .56)):
            col = QColor(ink); col.setAlphaF(rings * (.9 if k else .7))
            p.setPen(_pen(col, line * (1.4 if k == 0 else 1.)))
            p.drawEllipse(QPointF(0, 0), R * rr * (.85 + .15 * rings), R * rr * (.85 + .15 * rings))
        # the little ticks between the two inner rings
        col = QColor(ink); col.setAlphaF(rings * .8); p.setPen(_pen(col, line * .8, cap=False))
        for i in range(60):
            ang = 2 * math.pi * i / 60
            p.drawLine(QPointF(R * .56 * math.cos(ang), R * .56 * math.sin(ang)),
                       QPointF(R * .62 * math.cos(ang), R * .62 * math.sin(ang)))
    numerals = stage(a, .4, .78)
    if numerals > 0:
        font = QFont('Times New Roman'); font.setPixelSize(max(4, int(R * .2))); font.setBold(True)
        p.setFont(font)
        for i, text in enumerate(ROMAN):
            show = clamp(numerals * 12 - i)
            if show <= 0:
                continue
            col = QColor(ink); col.setAlphaF(show); p.setPen(col)
            ang = -math.pi / 2 + 2 * math.pi * i / 12
            cx, cy = R * .79 * math.cos(ang), R * .79 * math.sin(ang)
            p.save(); p.translate(cx, cy); p.rotate(math.degrees(ang) + 90)
            p.drawText(QRectF(-R * .2, -R * .13, R * .4, R * .26), Qt.AlignmentFlag.AlignCenter, text)
            p.restore()
    hands = back_out(stage(a, .74, 1.), 1.2)
    if hands > 0:
        run = (float(t) - float(item.get('start', 0))) if t is not None else 0.
        minute = math.radians(150 + run * 12)            # it moves while you watch
        hour = math.radians(300 + run * 1)
        second = math.radians(int(run) * 6 + 40)          # ticks once a second
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(ink)
        for ang, length, width in ((hour, .45, .05), (minute, .66, .035)):
            ang -= math.pi / 2
            tip = QPointF(R * length * hands * math.cos(ang), R * length * hands * math.sin(ang))
            side = QPointF(-math.sin(ang) * R * width, math.cos(ang) * R * width)
            from PySide6.QtGui import QPolygonF
            p.drawPolygon(QPolygonF([QPointF(-side.x() * .5, -side.y() * .5), tip,
                                     QPointF(side.x() * .5, side.y() * .5),
                                     QPointF(-R * .1 * math.cos(ang), -R * .1 * math.sin(ang))]))
        ang = second - math.pi / 2
        p.setPen(_pen(ink, line * .9))
        p.drawLine(QPointF(-R * .15 * math.cos(ang), -R * .15 * math.sin(ang)),
                   QPointF(R * .8 * hands * math.cos(ang), R * .8 * hands * math.sin(ang)))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(ink)
        p.drawEllipse(QPointF(0, 0), R * .04, R * .04)


def _head(p, tip, back, size, color, width):
    """An open arrowhead (two strokes) at `tip`, pointing away from `back`."""
    from PySide6.QtCore import QPointF
    ang = math.atan2(tip[1] - back[1], tip[0] - back[0])
    p.setPen(_pen(color, width))
    for side in (-1, 1):
        q = ang + math.pi - side * math.radians(38)
        p.drawLine(QPointF(*tip), QPointF(tip[0] + size * math.cos(q), tip[1] + size * math.sin(q)))


def _double_arrow(p, item, w, h, frame_h, a, t):
    """Two arrows growing out from the middle (↖ ↘), then their heads."""
    from PySide6.QtCore import QPointF
    flip = item.get('flip')
    width = _width(item, frame_h, THICKNESS['Double arrow'])
    color = item.get('color', COLOR['Double arrow'])
    grow = ease(stage(a, 0., .7))
    size = max(width * 3, min(w, h) * .12)
    for near, far in (((.42, .42), (.06, .06)), ((.58, .58), (.94, .94))):
        n, f = _pt(near, w, h, flip), _pt(far, w, h, flip)
        tip = (n[0] + (f[0] - n[0]) * grow, n[1] + (f[1] - n[1]) * grow)
        if grow > 0:
            p.setPen(_pen(color, width)); p.drawLine(QPointF(*n), QPointF(*tip))
        head = back_out(stage(a, .62, 1.))
        if head > 0:
            _head(p, tip, n, size * head, color, width)


def _hook(p, item, w, h, frame_h, a, t):
    """A curved arrow drawn from its thin tail, thickening, and its head pops on at the end."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPolygonF
    pts = [_pt(q, w, h, item.get('flip')) for q in main_line('Hook arrow')]
    width = _width(item, frame_h, THICKNESS['Hook arrow'])
    color = QColor(item.get('color', COLOR['Hook arrow']))
    body = ease(stage(a, 0., .78))
    part = _partial(pts, body)
    p.setBrush(Qt.BrushStyle.NoBrush)
    n = len(part)
    for i in range(1, n):                               # thin at the tail, full width near the head
        u = i / max(1, len(pts) - 1)
        p.setPen(_pen(color, width * (.15 + .85 * min(1., u * 1.6))))
        p.drawLine(QPointF(*part[i - 1]), QPointF(*part[i]))
    head = back_out(stage(a, .72, 1.))
    if head > 0 and n >= 2:
        tip = pts[-1]
        back = pts[-6]
        ang = math.atan2(tip[1] - back[1], tip[0] - back[0])
        size = width * 3.2 * head
        nose = (tip[0] + math.cos(ang) * size, tip[1] + math.sin(ang) * size)
        wing = [(tip[0] + math.cos(ang + side * math.pi / 2) * size * .9,
                 tip[1] + math.sin(ang + side * math.pi / 2) * size * .9) for side in (-1, 1)]
        p.setPen(_pen(color, width * .3)); p.setBrush(color)
        p.drawPolygon(QPolygonF([QPointF(*nose), QPointF(*wing[0]), QPointF(*tip), QPointF(*wing[1])]))
