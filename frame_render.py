"""One frame of the final video, exactly as preview and export show it.

Order: render the artwork (larger when the camera is zoomed in), apply Artwork
size, put the hand on its own layer, crop the camera view, then the optional
lettering background.
"""
from __future__ import annotations


RENDER_KEYS = {'width', 'height', 'duration', 'fade_duration', 'hold_duration', 'final_image', 'thickness',
               'hand', 'hand_scale', 'anchor', 'reveal_mode', 'brush_width', 'painting_hand',
               'stroke_spacing', 'artwork_scale'}


def _core(drawing, fraction, opts, camera_path=None):
    """Artwork + hand, without the erase stage or lettering background."""
    from camera import crop, render_size
    from engine import render, scale_animation_frame
    from hand_layer import capture
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
    frame = scale_animation_frame(frame, scale, hands)
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
    key = _erase_key(drawing, opts, erase)
    if key in _ERASE_CACHE:
        return _ERASE_CACHE[key]
    hold = _core(drawing, 1., opts)
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


def compose_frame(drawing, fraction, options, camera_path=None):
    """options: render_color_timeline keywords plus artwork_scale, duration and erase."""
    from engine import apply_lettering_background
    opts, erase, base_fraction, progress = split_erase(drawing, fraction, options)
    if progress is None:
        frame = _core(drawing, base_fraction, opts, camera_path)
    else:
        import eraser
        hold, plan = erase_setup(drawing, opts, erase)
        frame = eraser.erase_frame(hold, plan, progress)
        point, _ = plan.state(progress)
        if frame is hold:
            frame = hold.copy()
        frame = eraser.draw_eraser(frame, point, erase.get('image'), erase.get('anchor', eraser.ERASER_TIP),
                                   float(erase.get('width', .18)))
        if camera_path is not None:
            frame = _camera_view(frame, *camera_path.at(fraction))
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
    return camera.plan(samples, total, w, h, zoom)


def timeline_seconds(drawing, options):
    """Length of the animation in seconds for these options (erase stage included)."""
    from color_reveal import timeline_duration
    erase = options.get('erase')
    if erase and erase.get('mode'):
        base = {k: v for k, v in options.items() if k != 'erase'}
        return timeline_seconds(drawing, base) + max(.1, float(erase.get('seconds', 3)))
    image = options.get('final_image')
    if image is None or image.isNull():
        return max(.001, float(options.get('duration', 4)))
    if getattr(drawing, 'source_kind', None) == 'image' and getattr(drawing, 'image_animation', None) == 'paint_only':
        return max(.001, float(options.get('fade_duration', .4))) + max(0., float(options.get('hold_duration', .6)))
    return timeline_duration(options.get('duration', 4), image, options.get('fade_duration', .4),
                             options.get('hold_duration', .6))
