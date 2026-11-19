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
# exp.29 (the user): how it appears: by itself, or drawn by the hand, only its main shape
# (the outline: an arrow's line, its head pops in) or every stroke (the head too)
DRAWING = ('Animated', 'Hand: outline', 'Hand: everything')
# where the hand comes from and goes back to: its resting corner (taking over from the waiting
# hand), or in from the bottom and out again, gone
HAND_WAYS = ('Rests in its corner', 'Comes in and leaves')
GLIDE = .5            # seconds the hand takes to come to the line and to go back
HEAD_POP = .2         # Hand: outline: the arrowhead pops in after the hand's line
ASPECT = {'Arrow': .32, 'Curved arrow': .55, 'Circle': .62, 'Hand-drawn circle': .62, 'Line': .08,
          'Wavy line': .16}
HEAD_SHARE = .18          # arrows: the last part of the drawing time draws the head


def new(shape='Arrow', start=0., duration=3., color='#E0463C'):
    shape = shape if shape in SHAPES else 'Arrow'
    return dict(id=uuid.uuid4().hex[:10], kind='sticker', name=shape, shape=shape, color=color,
                thickness=.012, x=.5, y=.5, size=.3, aspect=ASPECT[shape], rotation=0., flip=False,
                draw_seconds=.8, start=float(start), duration=float(duration),
                drawing='Animated', hand_way='Rests in its corner',
                hand_in=GLIDE, hand_out=GLIDE, hand_in_style='Smooth', hand_out_style='Smooth',
                hand_in_bend='Auto', hand_out_bend='Auto', hand_in_path=None, hand_out_path=None,
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


def hand_mode(item):
    """None (it draws itself), 'outline' or 'all' (the hand draws it)."""
    return {'Hand: outline': 'outline', 'Hand: everything': 'all'}.get(item.get('drawing'))


def ways(item):
    """exp.31: (way in, way back) seconds of the sticker's hand (its Hand dialog, like an element's)."""
    return (max(.05, float(item.get('hand_in', GLIDE) or GLIDE)), max(.05, float(item.get('hand_out', GLIDE) or GLIDE)))


def busy(item):
    """(from, to) seconds the hand is busy with this sticker (coming, drawing, going), or None."""
    if not hand_mode(item):
        return None
    start = float(item.get('start', 0))
    lead, tail = ways(item)
    return start - lead, start + max(.05, float(item.get('draw_seconds', .8))) + tail


def phases(item, t):
    """(line 0..1, head strokes [0..1, 0..1]) drawn at t."""
    seconds = max(.05, float(item.get('draw_seconds', .8)))
    start = float(item.get('start', 0))
    e = _ease((t - start) / seconds)
    mode = hand_mode(item)
    u = max(0., min(1., (t - start) / seconds))
    if mode == 'outline':                   # the hand's line over the whole time; the head pops in
        # exp.35 (the user: one movement, the hand stopped at the start of the line): a hand draws
        # at a steady pace; its way in arrives at that speed and its way back leaves at it
        pop = max(0., min(1., (t - start - seconds) / HEAD_POP))
        return u, [pop, pop]
    if mode == 'all':                       # the line, then each stroke of the head, by the hand
        line = min(1., u / .76)
        # the first stroke of the head, the pen back to the tip (no ink), the second stroke
        return line, [max(0., min(1., (u - .76) / .1)), max(0., min(1., (u - .9) / .1))]
    line = min(1., e / (1 - HEAD_SHARE))
    grow = max(0., (e - (1 - HEAD_SHARE)) / HEAD_SHARE)
    return line, [grow, grow]


def _geometry(item, w, h, frame_h):
    """(points of the line, the two head strokes [(from, to), ...] or [], pen width) in a w × h box
    centred on 0, 0."""
    points, head = stroke(item.get('shape', 'Arrow'))
    pts = _scaled(points, w, h, bool(item.get('flip')))
    width = max(1., float(item.get('thickness', .012)) * frame_h)
    strokes = []
    if head:
        tip = pts[-1]
        back = next((p for p in reversed(pts[:-1]) if math.dist(p, tip) > width * .5), pts[0])
        angle = math.atan2(tip[1] - back[1], tip[0] - back[0])
        size = max(width * 3.2, min(math.hypot(w, h) * .16, width * 7))
        for side in (-1, 1):
            a = angle + math.pi - side * math.radians(32)
            strokes.append((tip, (tip[0] + size * math.cos(a), tip[1] + size * math.sin(a))))
    return pts, strokes, width


def pen_point(item, w, h, frame_h, t):
    """Where the pen is on the sticker (box coordinates) at t while the hand draws it, or None."""
    mode = hand_mode(item)
    if not mode:
        return None
    pts, heads, _ = _geometry(item, w, h, frame_h)
    line, head = phases(item, t)
    if mode == 'all' and heads and line >= 1:
        for (a, b), share in zip(heads, head):
            if 0 < share < 1:
                return (a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share)
        if head[0] >= 1 and head[1] <= 0:       # lifted, back to the tip for the second stroke
            u = (t - float(item.get('start', 0))) / max(.05, float(item.get('draw_seconds', .8)))
            k = _ease((u - .86) / .04)
            end, tip = heads[0][1], heads[1][0]
            return (end[0] + (tip[0] - end[0]) * k, end[1] + (tip[1] - end[1]) * k)
        return heads[-1][1] if head[1] >= 1 else heads[0][0]
    part = _partial(pts, line)
    return part[-1]


def draw(painter, item, w, h, frame_h, amount=1., t=None):
    """Draw the sticker centred on the painter's origin, in a w × h box: `amount` (0..1) of it,
    or, with t, as much as is drawn at t (exp.29: by the hand, stroke by stroke)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainterPath, QPen
    pts, heads, width = _geometry(item, w, h, frame_h)
    if t is not None:
        line, head = phases(item, t)
    else:
        if amount <= 0:
            return
        line = min(1., amount / (1 - HEAD_SHARE)) if heads else amount
        grow = max(0., (amount - (1 - HEAD_SHARE)) / HEAD_SHARE)
        head = [grow, grow]
    if line <= 0:
        return
    pen = QPen(QColor(item.get('color', '#E0463C')), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
    part = _partial(pts, min(1., line))
    if len(part) >= 2:
        path = QPainterPath(QPointF(*part[0]))
        for x, y in part[1:]:
            path.lineTo(x, y)
        painter.drawPath(path)
    for (a, b), share in zip(heads, head):
        if share > 0:
            painter.drawLine(QPointF(*a), QPointF(a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share))


# ------------------------------------------------------------ exp.29: the hand that draws stickers
_HAND = {}


def set_hand(image, scale, anchor, corner):
    """The window's drawing hand (picture as written, size as a share of the video width, its
    pen tip as a share of the picture, its resting corner): stickers drawn by the hand use it."""
    _HAND.clear()
    if image is not None and not image.isNull():
        _HAND.update(image=image, scale=float(scale), anchor=(float(anchor[0]), float(anchor[1])),
                     corner=corner or 'Bottom right')


def hand_tip(item, t, W, H, home=None):
    """Where the hand's pen tip is on a W × H frame at t (seconds), or None (not there).
    exp.43: home, where its ways start and end (the waiting hand's real spot), in the frame's
    points; default: its corner."""
    span = busy(item)
    if span is None or not _HAND or not span[0] <= t <= span[1]:
        return None
    import overlays
    bx, by, bw, bh = overlays.box(item, W, H)
    w = float(item.get('size', .3)) * W
    h = w * float(item.get('aspect', .4))

    def on_frame(pt):
        a = math.radians(float(item.get('rotation', 0) or 0))
        x, y = pt
        return (bx + bw / 2 + x * math.cos(a) - y * math.sin(a), by + bh / 2 + x * math.sin(a) + y * math.cos(a))
    start = float(item.get('start', 0)); seconds = max(.05, float(item.get('draw_seconds', .8)))
    if home is not None and item.get('hand_way') != 'Comes in and leaves':
        pass
    elif item.get('hand_way') == 'Comes in and leaves':
        home = (W * .86, H * 1.12)          # below the bottom edge, on the hand's side
    else:
        from frame_render import REST_CORNERS
        fx, fy = REST_CORNERS.get(_HAND['corner'], REST_CORNERS['Bottom right'])
        home = (fx * W, fy * H)
    pts, heads, _ = _geometry(item, w, h, H)
    first = on_frame(pts[0])
    last = on_frame(heads[-1][1] if heads and hand_mode(item) == 'all' else pts[-1])
    from frame_render import glide_point, split_style
    lead, tail = ways(item)
    centre = (W / 2., H / 2.)
    if t < start:                         # exp.31: its way in, as the element hands go (How, Turn, Path)
        style = item.get('hand_in_style') or 'Smooth'
        bend, keys = item.get('hand_in_bend') or 'Auto', item.get('hand_in_path') or None
        p = max(0., min(1., (t - span[0]) / lead))
        if (split_style(style)[1] or 'Smooth') == 'Smooth':   # exp.35/37: one movement, any shape
            return _flowing(home, first, p, bend, keys, centre, _pen_speed(item, w, h, H, 'start') * lead, True, style)
        return glide_point(home, first, p, style, centre, bend, keys)
    if t > start + seconds:
        style = item.get('hand_out_style') or 'Smooth'
        bend, keys = item.get('hand_out_bend') or 'Auto', item.get('hand_out_path') or None
        p = max(0., min(1., (t - start - seconds) / tail))
        if (split_style(style)[1] or 'Smooth') == 'Smooth':   # exp.35/37: it leaves at the drawing's speed
            return _flowing(last, home, p, bend, keys, centre, _pen_speed(item, w, h, H, 'end') * tail, False, style)
        return glide_point(last, home, p, style, centre, bend, keys)
    return on_frame(pen_point(item, w, h, H, t))


def _pen_speed(item, w, h, frame_h, where):
    """exp.35: how fast (pixels a second) the pen moves on the line at its start / end."""
    pts, heads, _ = _geometry(item, w, h, frame_h)
    seconds = max(.05, float(item.get('draw_seconds', .8)))
    length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    if hand_mode(item) == 'all' and heads:
        if where == 'end':
            return math.dist(*heads[-1]) / (.1 * seconds)
        return length / (.76 * seconds)
    return length / seconds


def _flowing(a, b, p, bend, keys, centre, reach, arriving, style='Smooth'):
    """exp.35: the Smooth way from a to b at p (0..1) without stopping at the line: arriving, it
    starts from rest and reaches b at the pen's speed; leaving, it starts at that speed and comes to
    rest at b. reach: the pen's speed × the way's seconds (pixels)."""
    from frame_render import glide_point, _inverse_ease
    line = [glide_point(a, b, _inverse_ease(i / 24., style), style, centre, bend, keys) for i in range(25)]
    way = sum(math.dist(x, y) for x, y in zip(line, line[1:])) or 1.
    v = max(0., reach / way)                 # its speed at the line, in ways a second × seconds

    def h(x):                                # from rest to speed v
        if v <= 3:
            return (v - 2) * x ** 3 + (3 - v) * x ** 2      # a smooth cubic
        return x ** v        # exp.36: faster than a cubic can reach (it slowed down at the line before)
    q = h(p) if arriving else 1 - h(1 - p)
    return glide_point(a, b, _inverse_ease(max(0., min(1., q)), style), style, centre, bend, keys)


def way_ends(item, W, H):
    """exp.31: (home, first point, last point) of the hand's ways on a W × H frame (Edit path)."""
    import overlays
    bx, by, bw, bh = overlays.box(item, W, H)
    w = float(item.get('size', .3)) * W
    h = w * float(item.get('aspect', .4))
    a = math.radians(float(item.get('rotation', 0) or 0))

    def on_frame(pt):
        x, y = pt
        return (bx + bw / 2 + x * math.cos(a) - y * math.sin(a), by + bh / 2 + x * math.sin(a) + y * math.cos(a))
    if item.get('hand_way') == 'Comes in and leaves':
        home = (W * .86, H * 1.12)
    else:
        from frame_render import REST_CORNERS
        fx, fy = REST_CORNERS.get(_HAND.get('corner', 'Bottom right'), REST_CORNERS['Bottom right'])
        home = (fx * W, fy * H)
    pts, heads, _ = _geometry(item, w, h, H)
    return home, on_frame(pts[0]), on_frame(heads[-1][1] if heads and hand_mode(item) == 'all' else pts[-1])


def home_on_frame(item, W, H, screen_w=None, painter=None, to_screen=None):
    """exp.43: the sticker's home (_home_screen: shares of the screen, set by the window from
    where the waiting hand is) in the points of its W × H frame, or None (its corner)."""
    spot = item.get('_home_screen')
    if not spot:
        return None
    if to_screen is None:
        return (float(spot[0]) * W, float(spot[1]) * H)
    sw = float(screen_w or W)
    try:
        sh = float(painter.device().height()) if painter is not None else sw * H / max(1., W)
    except Exception:
        sh = sw * H / max(1., W)
    x, y = float(spot[0]) * sw, float(spot[1]) * sh
    x0, y0 = to_screen(0., 0.)
    x1, y1 = to_screen(float(W), float(H))
    kx, ky = (x1 - x0) / max(1e-9, W), (y1 - y0) / max(1e-9, H)
    return ((x - x0) / kx, (y - y0) / ky)


def paint_hand(painter, item, t, W, H, screen_w=None, to_screen=None):
    """The hand drawing this sticker at t (its pen tip on the line). W × H: the frame the sticker
    is drawn on; exp.30 (the user: the hand was huge): when that frame is a page the camera
    zooms, to_screen maps its points to the screen and the hand has the screen's size
    (screen_w wide), like the elements' hands, which the camera never zooms."""
    tip = hand_tip(item, t, W, H, home_on_frame(item, W, H, screen_w, painter, to_screen))
    if tip is None:
        return False
    if to_screen is not None:
        tip = to_screen(*tip)
    from PySide6.QtCore import QRectF
    from frame_render import draw_hand_picture
    image = _HAND['image']
    hw = float(screen_w or W) * _HAND['scale']; hh = hw * image.height() / max(1, image.width())
    ax, ay = _HAND['anchor']
    painter.save(); painter.setOpacity(1.)
    draw_hand_picture(painter, QRectF(tip[0] - ax * hw, tip[1] - ay * hh, hw, hh), image)
    painter.restore()
    return True


def busy_spans(items):
    """[(from, to)] while stickers drawn by the hand from its corner use it (the waiting hand is
    not in its corner then)."""
    out = []
    for item in items or ():
        if item.get('kind') == 'sticker' and not item.get('off') and item.get('hand_way') != 'Comes in and leaves':
            span = busy(item)
            if span is not None:
                out.append(span)
    return out


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
