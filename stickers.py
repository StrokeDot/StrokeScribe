"""Stickers (exp.27): arrows, circles and lines that draw themselves, like Filmora's animated
stickers (the user marks things in a video: an arrow pointing, a circle around something, a line
under it).

A sticker is an overlay (overlays.py) with kind 'sticker': it has its own time on the timeline, is
moved on the preview like a text, and is painted on top in the preview and the export. It is drawn
as lines at the size it is shown (sharp at any export size), and its drawing follows the clock,
not the frames: smooth at the preview's frame rate and at 60 fps in the export.

    shape         one of SHAPES
    color         '#RRGGBB'
    thickness     line width as a share of the video height
    size          width as a share of the video width; aspect: height / width
    rotation      degrees; flip: mirrored left-right
    draw_seconds  how long it takes to draw itself (then it stays until its clip ends)
"""
from __future__ import annotations

import math
import uuid

SHAPES = ('Arrow', 'Curved arrow', 'Circle', 'Hand-drawn circle', 'Line', 'Wavy line')
ASPECT = {'Arrow': .32, 'Curved arrow': .55, 'Circle': .62, 'Hand-drawn circle': .62, 'Line': .08,
          'Wavy line': .16}
HEAD_SHARE = .18          # arrows: the last part of the drawing time draws the head


def new(shape='Arrow', start=0., duration=3., color='#E0463C'):
    shape = shape if shape in SHAPES else 'Arrow'
    return dict(id=uuid.uuid4().hex[:10], kind='sticker', name=shape, shape=shape, color=color,
                thickness=.012, x=.5, y=.5, size=.3, aspect=ASPECT[shape], rotation=0., flip=False,
                draw_seconds=.8, start=float(start), duration=float(duration),
                effect_in='None', in_seconds=.4, effect_out='Fade', out_seconds=.4, track=0)


def _ease(p):
    """A hand draws slower at the start and the end."""
    p = max(0., min(1., p))
    return p * p * (3 - 2 * p)


def progress(item, t):
    """How much of the sticker is drawn at t (seconds of its timeline): 0..1."""
    seconds = max(.05, float(item.get('draw_seconds', .8)))
    return _ease((t - float(item.get('start', 0))) / seconds)


def _bezier(p0, p1, p2, p3, n=64):
    out = []
    for i in range(n + 1):
        u = i / n
        a, b, c, d = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def stroke(shape):
    """(points of the main line in the unit box, arrowhead at its end?)."""
    if shape == 'Arrow':
        return [(.04, .5), (.96, .5)], True
    if shape == 'Curved arrow':
        return _bezier((.05, .88), (.2, .1), (.65, .02), (.95, .42)), True
    if shape == 'Circle':
        start = -math.pi * .6
        return [(.5 + .47 * math.cos(start + 2 * math.pi * i / 96),
                 .5 + .47 * math.sin(start + 2 * math.pi * i / 96)) for i in range(97)], False
    if shape == 'Hand-drawn circle':
        # a loop drawn by hand: a little past where it began, the radius wandering slightly
        start, turns = -math.pi * .55, 1.12
        pts = []
        for i in range(121):
            a = start + 2 * math.pi * turns * i / 120
            r = .45 + .03 * math.sin(a * 2.3 + .7) - .025 * i / 120
            pts.append((.5 + r * math.cos(a), .5 + r * math.sin(a) * 1.02))
        return pts, False
    if shape == 'Wavy line':
        return [(.03 + .94 * i / 96, .5 + .38 * math.sin(i / 96 * math.pi * 5)) for i in range(97)], False
    return [(.03, .5), (.97, .5)], False          # Line


def _scaled(points, w, h, flip):
    return [((1 - x if flip else x) * w - w / 2, y * h - h / 2) for x, y in points]


def _partial(points, share):
    """The first `share` of the line (by its length)."""
    if share >= 1:
        return points
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    goal = sum(lengths) * max(0., share)
    out, run = [points[0]], 0.
    for (a, b), d in zip(zip(points, points[1:]), lengths):
        if run + d >= goal:
            f = (goal - run) / d if d else 0
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            return out
        out.append(b); run += d
    return out


def draw(painter, item, w, h, frame_h, amount=1.):
    """Draw the sticker centred on the painter's origin, in a w × h box, `amount` (0..1) of it."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainterPath, QPen
    if amount <= 0:
        return
    points, head = stroke(item.get('shape', 'Arrow'))
    pts = _scaled(points, w, h, bool(item.get('flip')))
    width = max(1., float(item.get('thickness', .012)) * frame_h)
    pen = QPen(QColor(item.get('color', '#E0463C')), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
    shaft = amount / (1 - HEAD_SHARE) if head else amount
    line = _partial(pts, min(1., shaft))
    if len(line) >= 2:
        path = QPainterPath(QPointF(*line[0]))
        for x, y in line[1:]:
            path.lineTo(x, y)
        painter.drawPath(path)
    if head and amount > 1 - HEAD_SHARE:
        grow = (amount - (1 - HEAD_SHARE)) / HEAD_SHARE
        tip = pts[-1]
        back = next((p for p in reversed(pts[:-1]) if math.dist(p, tip) > width * .5), pts[0])
        angle = math.atan2(tip[1] - back[1], tip[0] - back[0])
        size = max(width * 3.2, min(math.hypot(w, h) * .16, width * 7)) * grow
        for side in (-1, 1):
            a = angle + math.pi - side * math.radians(32)
            painter.drawLine(QPointF(*tip), QPointF(tip[0] + size * math.cos(a), tip[1] + size * math.sin(a)))


def preview(shape, size=64, color='#E0463C', background=None):
    """A small finished picture of a shape (the Stickers panel's library)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    image = QImage(size * 2, size * 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(background) if background else Qt.GlobalColor.transparent)
    p = QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(QPointF(size, size))
    w = size * 1.6
    item = dict(shape=shape, color=color, thickness=.045)
    draw(p, item, w, w * min(.8, max(.22, ASPECT.get(shape, .4))), size * 2)
    p.end()
    pix = QPixmap.fromImage(image); pix.setDevicePixelRatio(2.)
    return pix
