"""One frame of the final video, exactly as preview and export show it.

Order: render the artwork (larger when the camera is zoomed in), apply Artwork
size, put the hand on its own layer, crop the camera view, then the optional
lettering background.
"""
from __future__ import annotations


RENDER_KEYS = {'width', 'height', 'duration', 'fade_duration', 'hold_duration', 'final_image', 'thickness',
               'hand', 'hand_scale', 'anchor', 'reveal_mode', 'brush_width', 'painting_hand',
               'stroke_spacing', 'artwork_scale'}


# What a frame shows (Export tab -> Export): everything, only the moving hand
# (to put over your own text or picture in a video editor), or only the
# artwork without any hand.
LAYERS = {'Drawing and hand': 'all', 'Hand only (no drawing)': 'hand', 'Drawing only (no hand)': 'art'}


def _blank(like):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    out = QImage(like.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    return out


def offset_of(opts):
    """(dx, dy) of the picture's position on the page, as fractions of the frame."""
    dx, dy = opts.get('offset') or (0., 0.)
    return float(dx), float(dy)


def shift(frame, dx, dy):
    """The frame moved by (dx, dy) fractions of its size (Position on the page)."""
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return frame
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainter
    out = _blank(frame)
    p = QPainter(out)
    p.drawImage(QPointF(round(dx * frame.width()), round(dy * frame.height())), frame)
    p.end()
    return out


def _ghosted(art, top, opacity):
    """`top` over a faint copy of `art` (preview of Hand only: you still see what is written)."""
    from PySide6.QtGui import QPainter
    out = _blank(top)
    p = QPainter(out)
    p.setOpacity(opacity); p.drawImage(0, 0, art)
    p.setOpacity(1.); p.drawImage(0, 0, top)
    p.end()
    return out


def _core(drawing, fraction, opts, camera_path=None):
    """Artwork + hand, without the erase stage or lettering background."""
    from camera import crop, render_size
    from engine import render, scale_animation_frame
    from hand_layer import capture
    layers = opts.get('layers', 'all')
    ghost = float(opts.get('ghost', 0) or 0)
    dx, dy = offset_of(opts)
    items = opts.get('overlays') if layers != 'hand' else None
    seconds = opts.get('_seconds')
    opts = {k: v for k, v in opts.items() if k in RENDER_KEYS}
    scale = opts.pop('artwork_scale', 1.0)
    width, height = opts['width'], opts['height']
    zoom, cx, cy = camera_path.at(fraction) if camera_path is not None else (1., .5, .5)
    big_w, big_h = render_size(width, height, zoom)
    opts['width'], opts['height'] = big_w, big_h
    with capture() as hands:
        if opts.get('final_image') is not None and not opts['final_image'].isNull():
            from color_reveal import render_color_timeline
            frame = render_color_timeline(drawing, fraction, **opts)
        else:
            frame = render(drawing, fraction, big_w, big_h, opts.get('thickness', 1.),
                           opts.get('hand'), opts.get('hand_scale', .18), opts.get('anchor', (.1, .1)))
    if layers == 'hand':
        hand_only = scale_animation_frame(_blank(frame), scale, hands)
        if ghost > 0:
            hand_only = _ghosted(scale_animation_frame(frame, scale, None), hand_only, ghost)
        frame = hand_only
    elif items and seconds is not None:
        # Overlays go over the drawing and under the hand.
        import overlays
        from hand_layer import draw_captured
        from PySide6.QtCore import QRectF
        frame = shift(scale_animation_frame(frame, scale, None), dx, dy)
        if frame is not None:
            frame = frame.copy()
        overlays.paint(frame, items, seconds)
        if layers != 'art' and hands:
            f = float(scale) or 1.
            moved = [(QRectF(r.x() + dx * big_w / f, r.y() + dy * big_h / f, r.width(), r.height()), h)
                     for r, h in hands]
            frame = draw_captured(frame, moved, scale)
        return crop(frame, width, height, zoom, cx, cy)
    elif layers == 'art':
        frame = scale_animation_frame(frame, scale, None)
    else:
        frame = scale_animation_frame(frame, scale, hands)
    frame = shift(frame, dx, dy)
    return crop(frame, width, height, zoom, cx, cy)


def split_erase(drawing, fraction, options):
    """(base options, erase settings or None, base fraction or None, erase progress or None)."""
    opts = dict(options)
    erase = opts.pop('erase', None)
    if not erase or not erase.get('mode'):
        return opts, None, fraction, None
    base = timeline_seconds(drawing, opts)
    total = base + max(.1, float(erase.get('seconds', 3)))
    t = max(0., min(1., float(fraction))) * total
    if t <= base:
        return opts, erase, t / base if base > 0 else 1., None
    return opts, erase, None, (t - base) / (total - base)


_ERASE_CACHE = {}


def _erase_key(drawing, opts, erase):
    def simple(v):
        if hasattr(v, 'cacheKey'):
            return ('img', v.cacheKey())
        if isinstance(v, (int, float, str, bool, tuple)) or v is None:
            return v
        return id(v)
    return (id(drawing), tuple(id(s) for s in drawing.strokes),
            tuple(sorted((k, simple(v)) for k, v in opts.items())),
            erase.get('mode'), round(float(erase.get('size', .08)), 4))


def erase_setup(drawing, opts, erase):
    """(finished frame, ErasePlan) for these options, cached."""
    import eraser
    import motion
    opts = dict(opts, offset=(0., 0.))      # planned in place; compose_frame moves the result
    if erase.get('mode') in EXITS:
        return finished_picture(drawing, opts), None        # an effect, no eraser route
    key = _erase_key(drawing, opts, erase)
    if key in _ERASE_CACHE:
        return _ERASE_CACHE[key]
    hold = _core(drawing, 1., dict(opts, layers='all', ghost=0))     # the real picture
    size = float(erase.get('size', .08))
    if erase.get('mode') == 'lines':
        strokes = motion.strokes_on_canvas(drawing, opts['width'], opts['height'],
                                           float(opts.get('artwork_scale', 1.)))
        plan = eraser.plan_lines(hold, strokes, size)
    else:
        plan = eraser.plan_zigzag(hold, size)
    if len(_ERASE_CACHE) > 6:
        _ERASE_CACHE.clear()
    _ERASE_CACHE[key] = (hold, plan)
    return hold, plan


# How an element comes in (instead of being drawn by the hand) and goes out (instead of
# being erased): the same effects as the overlays (overlays._effect).
ENTRANCES = {'Draw with the hand': 'draw', 'Fade in': 'Fade', 'Pop in': 'Pop', 'Zoom in': 'Zoom',
             'Spin in': 'Spin', 'Slide in from the left': 'Slide from left',
             'Slide in from the right': 'Slide from right', 'Slide in from the top': 'Slide from top',
             'Slide in from the bottom': 'Slide from bottom'}
EXITS = {'fade': 'Fade', 'pop': 'Pop', 'zoom': 'Zoom', 'spin': 'Spin', 'out-left': 'Slide from left',
         'out-right': 'Slide from right', 'out-top': 'Slide from top', 'out-bottom': 'Slide from bottom'}

_FINISHED = {}


def finished_picture(drawing, opts):
    """The finished element (no hand, no overlays, in place), cached."""
    clean = {k: v for k, v in opts.items() if k not in ('overlays', '_seconds', 'erase')}
    clean.update(offset=(0., 0.), ghost=0, pause=0, entrance='draw')
    layers = clean.get('layers', 'all')
    clean['layers'] = 'hand' if layers == 'hand' else 'art'
    key = _erase_key(drawing, clean, {'mode': 'finished', 'size': 0})
    if key in _FINISHED:
        _FINISHED[key] = _FINISHED.pop(key)          # most recently used last
        return _FINISHED[key]
    while len(_FINISHED) >= 24:                       # several elements at several sizes
        _FINISHED.pop(next(iter(_FINISHED)))
    _FINISHED[key] = _core(drawing, 1., clean)
    return _FINISHED[key]


def effect_frame(image, kind, p):
    """`image` (a whole frame) with an entrance effect at progress p (0..1); p=1: unchanged."""
    import overlays
    if p >= 1:
        return image.copy()
    opacity, dx, dy, scale, rotation = overlays._effect(kind, p)
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainter
    out = _blank(image)
    if opacity <= 0 or scale <= 0:
        return out
    w, h = image.width(), image.height()
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(min(1., opacity))
    painter.translate(QPointF(w / 2 + dx * w, h / 2 + dy * h))
    if rotation:
        painter.rotate(rotation)
    painter.scale(scale, scale)
    painter.drawImage(QRectF(-w / 2, -h / 2, w, h), image)
    painter.end()
    return out


def _entering(drawing, fraction, opts, kind):
    """The element comes in with an effect during its animation time, then stays."""
    plain = timeline_seconds(drawing, dict(opts, pause=0))
    length = float(opts.get('duration', 4) or 0) or float(opts.get('fade_duration', .4) or .4)
    p = fraction * plain / max(.05, length)
    finished = finished_picture(drawing, opts)
    frame = effect_frame(finished, kind, min(1., p))
    frame = shift(frame, *offset_of(opts))
    items = opts.get('overlays') if opts.get('layers', 'all') != 'hand' else None
    if items and opts.get('_seconds') is not None:
        import overlays
        overlays.paint(frame, items, opts['_seconds'])
    return frame


def compose_frame(drawing, fraction, options, camera_path=None):
    """options: render_color_timeline keywords plus artwork_scale, duration and erase."""
    from engine import apply_lettering_background
    opts, erase, base_fraction, progress = split_erase(drawing, fraction, options)
    items = opts.get('overlays') if opts.get('layers', 'all') != 'hand' else None
    if items:
        opts['_seconds'] = max(0., min(1., float(fraction))) * timeline_seconds(drawing, options)
    if progress is None:
        pause = float(opts.get('pause', 0) or 0)
        if pause > 0:                              # the pause after the element: stays finished
            whole = timeline_seconds(drawing, opts)
            plain = whole - pause
            base_fraction = min(1., base_fraction * whole / plain) if plain > 0 else 1.
        entrance = opts.get('entrance') or 'draw'
        if entrance != 'draw':
            frame = _entering(drawing, base_fraction, opts, entrance)
        else:
            frame = _core(drawing, base_fraction, opts, camera_path)
    elif erase.get('mode') in EXITS:
        # Goes out with an effect (fade, pop, zoom, spin, move out) instead of an eraser.
        hold = finished_picture(drawing, opts)
        frame = effect_frame(hold, EXITS[erase['mode']], 1. - progress)
        frame = shift(frame, *offset_of(opts))
        if items:
            import overlays
            overlays.paint(frame, items, opts['_seconds'])
        if camera_path is not None:
            frame = _camera_view(frame, *camera_path.at(fraction))
    else:
        import eraser
        hold, plan = erase_setup(drawing, {k: v for k, v in opts.items() if k not in ('overlays', '_seconds')}, erase)
        frame = eraser.erase_frame(hold, plan, progress)
        point, _ = plan.state(progress)
        if frame is hold:
            frame = hold.copy()
        layers = opts.get('layers', 'all')
        if layers == 'hand':
            ghost = float(opts.get('ghost', 0) or 0)
            frame = _ghosted(frame, _blank(frame), ghost) if ghost > 0 else _blank(frame)
        if layers != 'art':
            frame = eraser.draw_eraser(frame, point, erase.get('image'), erase.get('anchor', eraser.ERASER_TIP),
                                       float(erase.get('width', .18)))
        frame = shift(frame, *offset_of(opts))
        if items:
            import overlays
            if frame is hold:
                frame = hold.copy()
            overlays.paint(frame, items, opts['_seconds'])     # overlays keep their own timing
        if camera_path is not None:
            frame = _camera_view(frame, *camera_path.at(fraction))
    if opts.get('layers', 'all') == 'hand' or opts.get('background') is False:
        return frame                  # stays transparent (hand only, or a picture added to a page)
    return apply_lettering_background(frame, drawing)


def _camera_view(frame, zoom, cx, cy):
    """Camera view of an already composed frame (used while erasing)."""
    if zoom <= 1.0001:
        return frame
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    w, h = frame.width(), frame.height()
    vw, vh = w / zoom, h / zoom
    left = min(max(0., cx * w - vw / 2), w - vw)
    top = min(max(0., cy * h - vh / 2), h - vh)
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, w, h), frame, QRectF(left, top, vw, vh))
    p.end()
    return out


def camera_for(drawing, options, zoom, rate=30.):
    """Plan the camera path for these options (None when the camera is off)."""
    import camera
    import motion
    if zoom <= 1.0001 or drawing is None:
        return None
    total = timeline_seconds(drawing, options)
    w, h = options.get('width', 1920), options.get('height', 1080)
    samples = motion.track(drawing, dict(options, width=w, height=h), total, rate)
    path = camera.plan(samples, total, w, h, zoom)
    dx, dy = offset_of(options)
    if path is not None and (dx or dy):
        path = camera.ShiftedPath(path, dx, dy)     # follow the picture where it was moved to
    return path


def timeline_seconds(drawing, options):
    """Length of the animation in seconds for these options (erase stage included)."""
    from color_reveal import timeline_duration
    erase = options.get('erase')
    if erase and erase.get('mode'):
        base = {k: v for k, v in options.items() if k != 'erase'}
        return timeline_seconds(drawing, base) + max(.1, float(erase.get('seconds', 3)))
    pause = max(0., float(options.get('pause', 0) or 0))      # the element stays, finished
    image = options.get('final_image')
    if image is None or image.isNull():
        return max(.001, float(options.get('duration', 4))) + pause
    if getattr(drawing, 'source_kind', None) == 'image' and getattr(drawing, 'image_animation', None) == 'paint_only':
        return (max(.001, float(options.get('fade_duration', .4))) + max(0., float(options.get('hold_duration', .6)))
                + pause)
    return timeline_duration(options.get('duration', 4), image, options.get('fade_duration', .4),
                             options.get('hold_duration', .6)) + pause
