"""The board: every scene has a frame on one big board, and the camera flies
between them (like VideoScribe).

World units: a frame's width `w` is measured in "video widths" (1.0 = the
size of a normal scene); its height is w × (video height / width). A frame is
(cx, cy, w): its centre and its width. A scene draws exactly what it draws on
its own, inside its frame; the camera shows that frame while the scene is
drawn. Between scenes the camera moves (pans, zooms out and in) from one frame
to the next, and everything already drawn stays on the board.

Sharp at any zoom: pictures are re-drawn at the size the camera needs (SVG
lines are vectors), see World.

Frames: scenes the user placed on the board keep their own frame
(scene['board'] = {'cx', 'cy', 'w'}); the others are placed next to the scene
before them, in the direction of its transition (Camera move / Pan right: to
the right, Pan left: left, Pan up / down, Same page: on the same frame).
"""
from __future__ import annotations

import math
from collections import OrderedDict

GAP = .12                                    # space between frames placed next to each other
SAME_PAGE = 'Same page'
SHOW_ALL = 'Show everything'
CAMERA_KINDS = ('Camera move', 'Pan left', 'Pan right', 'Pan up', 'Pan down', SHOW_ALL)
SCREEN_KINDS = ('Fade', 'Zoom in')            # picture effects between two camera views
END_HOLD = 1.0                               # seconds the whole board stays at the end


# ------------------------------------------------------------ frames

def frame_of(scene):
    b = scene.get('board')
    if b and all(k in b for k in ('cx', 'cy', 'w')):
        return (float(b['cx']), float(b['cy']), max(.02, float(b['w'])))
    return None


def frames(scenes, aspect=9 / 16):
    """(cx, cy, w) of every scene."""
    out = []
    for k, scene in enumerate(scenes):
        own = frame_of(scene)
        if own is not None:
            out.append(own); continue
        if not out:
            out.append((0., 0., 1.)); continue
        cx, cy, w = out[-1]
        h = w * aspect
        kind = scenes[k - 1].get('transition')
        if kind == SAME_PAGE:
            out.append((cx, cy, w)); continue
        dx, dy = {'Pan left': (-w * (1 + GAP), 0.), 'Pan up': (0., -h * (1 + GAP)),
                  'Pan down': (0., h * (1 + GAP))}.get(kind, (w * (1 + GAP), 0.))
        # Never on top of an earlier element (Pan right, then Pan left would come back to
        # the first one): keep going in the same direction until the space is free.
        # (A frame the previous one sits inside, like a small frame zoomed into a big
        # picture, is not in the way: moving within it is what the user set up.)
        prev = out[-1]
        spot = (cx + dx, cy + dy, w)
        for _ in range(len(out) + 1):
            if not any(overlap(f, spot, aspect) > 1e-4 and overlap(f, prev, aspect) <= 1e-4 for f in out):
                break
            spot = (spot[0] + dx, spot[1] + dy, w)
        out.append(spot)
    return out


def rect(frame, aspect=9 / 16):
    """(left, top, right, bottom) of a frame in world units."""
    cx, cy, w = frame
    h = w * aspect
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def overlap(a, b, aspect=9 / 16):
    """Area of the overlap of two frames, as a fraction of frame b."""
    l1, t1, r1, b1 = rect(a, aspect)
    l2, t2, r2, b2 = rect(b, aspect)
    w, h = min(r1, r2) - max(l1, l2), min(b1, b2) - max(t1, t2)
    if w <= 0 or h <= 0:
        return 0.
    return w * h / max(1e-12, (r2 - l2) * (b2 - t2))


def has_base(all_frames, k, aspect=9 / 16):
    """True when pictures drawn before scene k can be seen in its frame."""
    return any(overlap(all_frames[j], all_frames[k], aspect) > 1e-4 for j in range(k))


def new_page(all_frames, k, aspect=9 / 16):
    """A scene on empty board space paints its own background (lettering background)."""
    return not has_base(all_frames, k, aspect)


def bounds(all_frames, aspect=9 / 16, margin=.06):
    """A view that shows every frame (the end of 'Show everything', and the Board view)."""
    rs = [rect(f, aspect) for f in all_frames]
    l, t = min(r[0] for r in rs), min(r[1] for r in rs)
    r, b = max(r[2] for r in rs), max(r[3] for r in rs)
    w = max(r - l, (b - t) / aspect) * (1 + 2 * margin)
    return ((l + r) / 2, (t + b) / 2, w)


def sub_view(frame, zoom, cx, cy, aspect=9 / 16):
    """Camera follow inside a frame: (zoom, centre as fractions of the frame) → a view."""
    fx, fy, w = frame
    if zoom <= 1.0001:
        return frame
    return (fx - w / 2 + cx * w, fy - w * aspect / 2 + cy * w * aspect, w / zoom)


# ------------------------------------------------------------ camera between frames

def _ease(t):
    t = max(0., min(1., t))
    return t * t * (3 - 2 * t)


def move_view(a, b, kind, t, aspect=9 / 16):
    """The camera view at t (0..1) of a move from view a to view b."""
    e = _ease(t)
    cx = a[0] + (b[0] - a[0]) * e
    cy = a[1] + (b[1] - a[1]) * e
    w = math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * e)
    if kind == 'Camera move':
        # Zoom out on the way (more for frames far apart), then in again.
        span = max(abs(b[0] - a[0]) + (a[2] + b[2]) / 2,
                   (abs(b[1] - a[1]) + (a[2] + b[2]) * aspect / 2) / aspect)
        middle = math.sqrt(a[2] * b[2])
        bump = min(1.6, max(0., span / middle - 1) * .75)
        w *= 1 + bump * math.sin(math.pi * t)
    return (cx, cy, w)


def transition_seconds(kind, seconds, last=False):
    if last:
        return max(0., float(seconds)) + END_HOLD if kind == SHOW_ALL else 0.
    return 0. if kind in ('Cut', SAME_PAGE) else max(0., float(seconds))


def locate(lengths, joins, seconds):
    """Where `seconds` falls: ('scene', k, fraction) or ('join', k, t). joins[-1] may be
    an end move (Show everything) after the last scene."""
    t = 0.
    n = len(lengths)
    for k, length in enumerate(lengths):
        if seconds <= t + length or (k == n - 1 and not joins[k]):
            return 'scene', k, max(0., min(1., (seconds - t) / max(1e-9, length)))
        t += length
        gap = joins[k]
        if gap > 0 and (seconds < t + gap or k == n - 1):
            return 'join', k, max(0., min(1., (seconds - t) / gap))
        t += gap
    return 'scene', n - 1, 1.


def join_view(all_frames, k, kind, t, aspect=9 / 16, move_seconds=1.):
    """Camera view during the join after scene k. After the last scene (Show
    everything) the camera moves out to the whole board, then holds."""
    a = all_frames[k]
    if k == len(all_frames) - 1:
        return move_view(a, bounds(all_frames, aspect), 'Pan right', end_split(t, move_seconds), aspect)
    return move_view(a, all_frames[k + 1], 'Camera move' if kind == SHOW_ALL else kind, t, aspect)


def end_split(t, move_seconds):
    """t over (move + hold) → fraction of the move (1 while holding)."""
    total = move_seconds + END_HOLD
    return min(1., t * total / max(1e-6, move_seconds))


# ------------------------------------------------------------ drawing the board

class World:
    """Draws camera views of the board at any size, sharply.

    items: per scene {'drawing', 'options' (compose_frame options), 'frame', 'key'}.
    Finished pictures (no hand) are drawn at the size the camera needs, on a
    ladder of sizes (√√2 apart), and kept: a camera move redraws nothing, and a
    zoom of 3× draws the pictures 3× bigger instead of stretching them."""

    LADDER = 2 ** .25
    MAX_SIDE = 6144                          # sharp up to about 3× zoom at 1080p
    BUDGET = 500 * 1024 * 1024

    def __init__(self, items, aspect, cache=None):
        self.items = items
        self.aspect = aspect
        self.frames = [it['frame'] for it in items]
        self.cache = cache if cache is not None else OrderedDict()

    def _size(self, width):
        q = self.LADDER ** math.ceil(math.log(max(8., width), self.LADDER))
        return int(min(self.MAX_SIDE, max(16, round(q))))

    def finished(self, j, width):
        """Scene j's finished picture (no hand), about `width` pixels wide."""
        q = self._size(width)
        key = (self.items[j]['key'], q)
        image = self.cache.get(key)
        if image is not None:
            self.cache.move_to_end(key)
            return image
        from frame_render import compose_frame
        it = self.items[j]
        opts = {k: v for k, v in it['options'].items() if k not in ('fps', 'audio', 'workers')}
        opts.update(width=q, height=max(2, round(q * self.aspect)), layers='art', ghost=0,
                    background=new_page(self.frames, j, self.aspect))
        special=(opts.get('blend_mode','Normal')!='Normal' or
                 float(opts.get('artwork_opacity',100))!=100)
        if special:
            # Titles/other independent overlays cannot inherit an artwork mode.
            opts['overlays']=[]
            opts['artwork_opacity']=100  # World.view applies opacity after caching the raw art.
            # First-page lettering background is drawn separately in World.view
            # so neither a blend mode nor opacity can alter the page itself.
            opts['background']=False
        image = compose_frame(it['drawing'], 1., opts)
        size = image.sizeInBytes()
        used = sum(i.sizeInBytes() for i in self.cache.values())
        while self.cache and used + size > self.BUDGET:
            _, old = self.cache.popitem(last=False); used -= old.sizeInBytes()
        self.cache[key] = image
        return image

    def finished_extras(self, j, width):
        """Finished independent overlays of element j, cached at matching size."""
        q=self._size(width)
        key=(self.items[j]['key'],'extras',q)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        from frame_render import independent_overlays
        it=self.items[j]
        opts=dict(it['options'],width=q,height=max(2,round(q*self.aspect)),
                  background=False,layers='art')
        extras=independent_overlays(it['drawing'],1.,opts)
        if extras is not None:
            used=sum(cached.sizeInBytes() for cached in self.cache.values())
            while self.cache and used+extras.sizeInBytes()>self.BUDGET:
                _,old=self.cache.popitem(last=False)
                used-=old.sizeInBytes()
            self.cache[key]=extras
        return extras

    def place(self, frame, view, out_w, out_h):
        """Where a frame lands in an out_w × out_h picture of `view` (x, y, w, h in pixels)."""
        vx, vy, vw = view
        scale = out_w / vw
        l, t, r, b = rect(frame, self.aspect)
        left = vx - vw / 2; top = vy - vw * self.aspect / 2
        return ((l - left) * scale, (t - top) * scale, (r - l) * scale, (b - t) * scale)

    def view(self, view, out_w, out_h, upto, skip=()):
        """The board seen by the camera: finished pictures of scenes 0..upto-1."""
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        out = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for j in range(min(upto, len(self.items))):
            if j in skip:
                continue
            x, y, w, h = self.place(self.frames[j], view, out_w, out_h)
            if w < 2 or x > out_w or y > out_h or x + w < 0 or y + h < 0:
                continue
            from blend_modes import composition_mode
            settings=self.items[j]['options']
            mode=settings.get('blend_mode','Normal')
            opacity=float(settings.get('artwork_opacity',100))
            special=mode!='Normal' or opacity!=100
            if special and new_page(self.frames,j,self.aspect):
                bg=getattr(self.items[j]['drawing'],'lettering_background',None)
                if bg is not None:
                    from PySide6.QtGui import QColor
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                    p.fillRect(QRectF(x,y,w,h),QColor(bg))
            p.setCompositionMode(composition_mode(mode))
            p.setOpacity(max(0.,min(1.,opacity/100.)))
            p.drawImage(QRectF(x, y, w, h), self.finished(j, w))
            p.setOpacity(1.)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if special:
                extras=self.finished_extras(j,w)
                if extras is not None:
                    p.drawImage(QRectF(x,y,w,h),extras)
        p.end()
        return out

    def put(self, under, image, frame, view, blend_mode='Normal', opacity=100., hand=None):
        """`image` (a frame of one scene, the frame's own picture) placed into a view picture."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter
        out = under.copy()
        x, y, w, h = self.place(frame, view, out.width(), out.height())
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        from blend_modes import composition_mode
        p.setCompositionMode(composition_mode(blend_mode))
        p.setOpacity(max(0.,min(1.,float(opacity)/100.)))
        p.drawImage(QRectF(x, y, w, h), image)
        p.setOpacity(1.)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if hand is not None:
            p.drawImage(QRectF(x,y,w,h),hand)
        p.end()
        return out
