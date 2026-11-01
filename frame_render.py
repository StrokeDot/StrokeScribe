"""One frame of the final video, exactly as preview and export show it.

Order: render the artwork (larger when the camera is zoomed in), apply Artwork
size, put the hand on its own layer, crop the camera view, then the optional
lettering background.
"""
from __future__ import annotations


RENDER_KEYS = {'width', 'height', 'duration', 'fade_duration', 'hold_duration', 'final_image', 'thickness',
               'hand', 'hand_scale', 'anchor', 'reveal_mode', 'brush_width', 'painting_hand',
               'stroke_spacing', 'artwork_scale', 'paper_cleanup','paper_tolerance','paper_softness',
               'paint_look'}


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


def _core(drawing, fraction, opts, camera_path=None, camera_fraction=None):
    """Artwork without the erase stage or lettering background. exp.149 (the user): the hand
    is not drawn into the picture any more: where it is goes to `last_hand_spec()` and the
    caller draws it on the screen, at the same size whatever the camera does (it grew with
    the zooms, and it hid under other pictures). The hand travelling to / from its corner
    (opts['_travel']) and hiding (Hand row) are in the spec too."""
    travel = opts.get('_travel')
    got = {}
    frame = _core_body(drawing, fraction, opts, camera_path, camera_fraction, got)
    if travel is not None and travel[0] == 'in':
        # Nothing drawn yet: the picture at 0 (the pen's first point came from a tiny step in).
        frame = _core_body(drawing, 0., opts, camera_path, camera_fraction, {})
    elif travel is not None and not got.get('hands') and len(travel) > 3 and travel[3] is not None:
        # exp.148: no hand where it stopped painting: it goes back from the last point of the lines.
        last = {}
        _core_body(drawing, travel[3], opts, camera_path, camera_fraction, last)
        if last.get('hands'):
            got = last
    _set_spec(_spec_from(got, opts, frame, travel))
    return frame


def _core_body(drawing, fraction, opts, camera_path=None, camera_fraction=None, moving=None):
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
    if camera_path is not None and camera_fraction is not None and getattr(camera_path, 'clips', None):
        # exp.126: the camera clips run on the video's clock. `fraction` here is the drawing's
        # own (faster when the element has a pause or a way out), so a zoom ran ahead of the
        # pictures under it and jumped back at the end: the picture moved during a zoom-in.
        fraction_for_camera = camera_fraction
    else:
        fraction_for_camera = fraction
    zoom, cx, cy = camera_path.at(fraction_for_camera) if camera_path is not None else (1., .5, .5)
    big_w, big_h = render_size(width, height, zoom)
    opts['width'], opts['height'] = big_w, big_h
    with capture() as hands:
        if opts.get('final_image') is not None and not opts['final_image'].isNull():
            from color_reveal import render_color_timeline
            frame = render_color_timeline(drawing, fraction, **opts)
        else:
            frame = render(drawing, fraction, big_w, big_h, opts.get('thickness', 1.),
                           opts.get('hand'), opts.get('hand_scale', .18), opts.get('anchor', (.1, .1)))
    if moving is not None:          # exp.143: the hand is drawn later, on its way
        moving.update(hands=list(hands), big=(big_w, big_h), scale=float(scale or 1.), offset=(dx, dy),
                      zoom=zoom, centre=(cx, cy))
        hands.clear()
    from hand_layer import draw_captured
    # The hand goes on after the picture is scaled AND moved to its place on the page
    # (exp.102): moved with the picture, it was cut where the moved frame ended (a
    # straight edge through the arm when Position X / Y was not 0).
    if layers == 'hand':
        hand_only = _blank(frame)
        if ghost > 0:
            hand_only = _ghosted(shift(scale_animation_frame(frame, scale, None), dx, dy), hand_only, ghost)
        frame = draw_captured(hand_only, hands, scale, (dx, dy))
        return crop(frame, width, height, zoom, cx, cy)
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
        frame = shift(scale_animation_frame(frame, scale, None), dx, dy)
    else:
        frame = shift(scale_animation_frame(frame, scale, None), dx, dy)
        frame = draw_captured(frame, hands, scale, (dx, dy))
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
        if isinstance(v, (int, float, str, bool)) or v is None:
            return v
        # Lists and dicts made again for every frame must give the same key (by value,
        # not by id), or the finished picture is drawn again each frame: playback lags.
        if isinstance(v, (tuple, list)):
            return tuple(simple(x) for x in v)
        if isinstance(v, dict):
            return tuple(sorted((str(k), simple(x)) for k, x in v.items()))
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
             'Slide in from the bottom': 'Slide from bottom', 'Ink appearance': 'Ink'}
EXITS = {'fade': 'Fade', 'pop': 'Pop', 'zoom': 'Zoom', 'spin': 'Spin', 'out-left': 'Slide from left',
         'out-right': 'Slide from right', 'out-top': 'Slide from top', 'out-bottom': 'Slide from bottom'}

_FINISHED = {}


def finished_picture(drawing, opts, lines_only=False):
    """The finished element (no hand, no overlays, in place), cached.

    lines_only: the lines drawn but no colours yet (Comes in: only the lines)."""
    clean = {k: v for k, v in opts.items() if k not in ('overlays', '_seconds', 'erase', 'move_hand',
                                                        'move_hand_grip', 'move_hand_size', 'entrance_part')}
    clean.update(offset=(0., 0.), ghost=0, pause=0, entrance='draw')
    layers = clean.get('layers', 'all')
    clean['layers'] = 'hand' if layers == 'hand' else 'art'
    key = _erase_key(drawing, clean, {'mode': 'lines' if lines_only else 'finished', 'size': 0})
    if key in _FINISHED:
        _FINISHED[key] = _FINISHED.pop(key)          # most recently used last
        return _FINISHED[key]
    while len(_FINISHED) >= 24:                       # several elements at several sizes
        _FINISHED.pop(next(iter(_FINISHED)))
    fraction = 1.
    if lines_only:
        plain = timeline_seconds(drawing, clean)
        fraction = min(1., max(.001, float(clean.get('duration', 4))) / max(.001, plain))
    _FINISHED[key] = _core(drawing, fraction, clean)
    return _FINISHED[key]


def effect_frame(image, kind, p):
    """`image` (a whole frame) with an entrance effect at progress p (0..1); p=1: unchanged."""
    import overlays
    if p >= 1:
        return image.copy()
    if kind == 'Ink':                 # exp.178: soaks into the paper like ink (ink_appearance.py)
        import ink_appearance
        return ink_appearance.frame(image, p)
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


def _entering(drawing, fraction, opts, kind, lines_only=False):
    """The element comes in with an effect during its animation time, then stays.

    On the Slide effects a move-in hand can carry it in (move_in.py)."""
    import move_in
    plain = timeline_seconds(drawing, dict(opts, pause=0))
    length = move_seconds(opts)
    p = min(1., fraction * plain / max(.05, length))
    layers = opts.get('layers', 'all')
    # The picture moves the same way in every layer (exp.102: the "art" layer of the whole
    # video moved it without the hand's timing, so picture and hand were out of step).
    side = move_in.carried(dict(opts, layers='all'), kind)
    pp = move_in.picture_progress(p, side)
    if layers == 'art':
        side = None                                  # the hand itself is not drawn here
    art = finished_picture(drawing, dict(opts, layers='art'), lines_only)
    frame = effect_frame(art, kind, pp)
    if layers == 'hand':            # Hand only: nothing of the picture (a faint copy in the preview)
        ghost = float(opts.get('ghost', 0) or 0)
        frame = _ghosted(frame, _blank(frame), ghost) if ghost > 0 else _blank(frame)
    dx, dy = offset_of(opts)
    frame = shift(frame, dx, dy)
    items = opts.get('overlays') if layers != 'hand' else None
    if items and opts.get('_seconds') is not None:
        import overlays
        overlays.paint(frame, items, opts['_seconds'])
    if side is not None and p < 1:
        import overlays
        _, ex, ey, _, _ = overlays._effect(kind, pp)
        point = move_in.hand_position(move_in.alpha_box(art), side, p, (ex + dx, ey + dy))
        if frame is art:
            frame = art.copy()
        # exp.152: the move-in hand is a screen hand too (the camera zoomed it with the
        # picture): recorded here, painted on the screen at its own size.
        _set_spec(dict(frame=(frame.width(), frame.height()), kind='move',
                       tip=(point[0] * frame.width(), point[1] * frame.height()),
                       tip_plain=(point[0] * frame.width(), point[1] * frame.height()),
                       image=opts['move_hand'], anchor=tuple(opts.get('move_hand_grip') or move_in.DEFAULT_GRIP),
                       share=float(opts.get('move_hand_size', .35)), side=side, phase=None, p=0.,
                       seconds=opts.get('_video_t')))
    return frame


def _lines_part(opts):
    import move_in
    return move_in.part_of(opts) == move_in.PART_LINES


def _compose_raw_frame(drawing, fraction, options, camera_path=None):
    """Raw animation frames; does not apply element opacity to the moving hand."""
    from engine import apply_lettering_background
    plan = travel_plan(drawing, options) if options.get('hand_travel') else None
    if plan is not None:
        # exp.143: the hand comes from its corner before drawing and goes back after it.
        lead, hand_end, tail, inner_total, inner, hand_start = plan
        t = max(0., min(1., float(fraction))) * (inner_total - hand_start + lead + tail)
        inner_t, phase, p = travel_phase(t, lead, hand_end, tail, hand_start)
        if phase == 'in':
            # the pen on the first point it really paints (exp.151)
            inner_t = hand_start + (hand_end - hand_start) * TRAVEL_EPS
        elif phase == 'out':
            # exp.182 (the user: the hand vanished, then the last lines went when it reached
            # its corner): the moment of the last stroke itself. A hair before it the pen was
            # often still on a lift to its last spot, and the painting was not finished.
            inner_t = hand_end
        video_t = float(options.get('hand_video_start', 0) or 0) + t
        inner['_video_t'] = video_t
        if phase:
            lines_end = max(.001, float(options.get('duration', 4) or 4)) * (1 - TRAVEL_EPS)
            inner['_travel'] = (phase, p, video_t,
                                min(1., lines_end / max(1e-9, inner_total)) if phase == 'out' else None)
        camera = _FixedCamera(camera_path, fraction) if camera_path is not None else None
        return _compose_raw_frame(drawing, inner_t / max(1e-9, inner_total), inner, camera)
    if options.get('hand_away') and '_video_t' not in options:
        # exp.148: the moment in the video (the Hand row can hide the hand while it draws).
        options = dict(options, _video_t=float(options.get('hand_video_start', 0) or 0)
                       + max(0., min(1., float(fraction))) * timeline_seconds(drawing, options))
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
        lines_only = entrance != 'draw' and _lines_part(opts)
        if lines_only and base_fraction * timeline_seconds(drawing, dict(opts, pause=0)) >= \
                float(opts.get('duration', 4) or 0):
            frame = _core(drawing, base_fraction, opts, camera_path, fraction)    # the colours are painted
        elif entrance != 'draw':
            _set_spec(None)
            frame = _entering(drawing, base_fraction, opts, entrance, lines_only)
            if camera_path is not None and getattr(camera_path, 'clips', None):
                # exp.126: an element that moves in follows the camera clips too (it stayed
                # unzoomed while everything around it zoomed in).
                view = camera_path.at(fraction)
                frame = _camera_view(frame, *view)
                _set_spec(_crop_spec(last_hand_spec(), frame, *view))
        else:
            frame = _core(drawing, base_fraction, opts, camera_path, fraction)
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


def compose_frame(drawing, fraction, options, camera_path=None):
    """Apply artwork opacity before the independent hand for all render callers."""
    _set_spec(None)
    if (options.get('layers','all')=='all' and
            options.get('artwork_opacity',100)!=100):
        from artwork_compositor import composite_element
        frame = composite_element(None,drawing,fraction,options,camera_path)   # with its hand
    else:
        frame = _compose_raw_frame(drawing,fraction,options,camera_path)
        if not options.get('_hand_later'):         # exp.149: the hand on top, its own size
            frame = paint_hand_spec(frame, last_hand_spec(), options)
    if options.get('hand_rest_here') and options.get('hand_travel') and resting(drawing, options, fraction):
        window = hand_window(drawing, options)
        seconds = float(options.get('hand_video_start', 0) or 0) + float(fraction) * (window[1] if window else 0.)
        frame = paint_rest_hand(frame, options, seconds)     # exp.143: waiting in its corner
    return frame


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
    """Plan the camera path for these options (None when the camera is off).

    exp.119: options['video_camera'] (whole video): the camera clips of the Camera track
    on top of the element's own camera (camera_clips.py)."""
    base = _own_camera(drawing, options, zoom, rate)
    if options.get('video_camera') and drawing is not None:
        import camera_clips
        return camera_clips.from_options(base, options, timeline_seconds(drawing, options))
    return base


def _own_camera(drawing, options, zoom, rate=30.):
    import camera
    import motion
    if options.get('cam_plan') and drawing is not None:      # exp.115: start → end framing
        from camera import zoom_path
        return zoom_path(options['cam_plan'], timeline_seconds(drawing, options))
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


def move_seconds(options):
    """Length of a move-in effect: the element's animation time."""
    return float(options.get('duration', 4) or 0) or float(options.get('fade_duration', .4) or .4)


def timeline_seconds(drawing, options):
    """Length of the animation in seconds for these options (erase stage included)."""
    from color_reveal import timeline_duration
    if options.get('hand_travel'):
        plan = travel_plan(drawing, options)
        if plan is not None:                 # exp.143: + the hand's way there and back
            return plan[3] - plan[5] + plan[0] + plan[2]
        options = {k: v for k, v in options.items() if k not in ('hand_travel', 'hand_travel_out')}
    erase = options.get('erase')
    if erase and erase.get('mode'):
        base = {k: v for k, v in options.items() if k != 'erase'}
        return timeline_seconds(drawing, base) + max(.1, float(erase.get('seconds', 3)))
    pause = max(0., float(options.get('pause', 0) or 0))      # the element stays, finished
    if (options.get('entrance') or 'draw') != 'draw':
        import move_in
        if move_in.part_of(options) == move_in.PART_ALL:
            # The whole picture moves in: only the move (no drawing, painting or colour hold).
            return move_seconds(options) + pause
    image = options.get('final_image')
    if image is None or image.isNull():
        return max(.001, float(options.get('duration', 4))) + pause
    if getattr(drawing, 'source_kind', None) == 'image' and getattr(drawing, 'image_animation', None) == 'paint_only':
        return (max(.001, float(options.get('fade_duration', .4))) + max(0., float(options.get('hold_duration', .6)))
                + pause)
    return timeline_duration(options.get('duration', 4), image, options.get('fade_duration', .4),
                             options.get('hold_duration', .6)) + pause


# ------------------------------------------------------------ the hand's corner (exp.143)
# The user: the hand waits in a corner of the video when it is not drawing, comes from
# there smoothly to the first line, and goes back after the drawing. The way there and
# back is added to the element's time (the drawing keeps its speed).

REST_CORNERS = {'Bottom right': (.74, .80), 'Right': (.86, .55), 'Bottom': (.55, .88),
                'Bottom left': (.26, .86)}   # exp.149: more of the hand in the picture
TRAVEL_EPS = 1e-3


def hand_seconds(drawing, options):
    """When the hand stops (seconds of the element without the travel): the end of the
    painting when a hand paints the colours, else the end of the lines."""
    base = {k: v for k, v in options.items() if k not in ('erase', 'hand_travel', 'hand_travel_out')}
    base['pause'] = 0
    image = options.get('final_image')
    paints = (image is not None and not image.isNull() and options.get('painting_hand') is not None
              and options.get('reveal_mode') not in (None, 'fade'))
    if paints:
        return max(.001, timeline_seconds(drawing, base) - max(0., float(options.get('hold_duration', .6))))
    if getattr(drawing, 'source_kind', None) == 'image' and getattr(drawing, 'image_animation', None) == 'paint_only':
        return max(.001, float(options.get('fade_duration', .4)))
    return max(.001, float(options.get('duration', 4) or 4))


def travel_plan(drawing, options):
    """(lead, hand_end, tail, element seconds without the travel, options without it), or
    None when this element has no travelling hand."""
    travel = float(options.get('hand_travel', 0) or 0)
    hand = options.get('hand')
    if travel <= 0 or hand is None or (options.get('entrance') or 'draw') != 'draw':
        return None
    inner = {k: v for k, v in options.items() if k not in ('hand_travel', 'hand_travel_out', 'hand_rest_here')}
    inner_total = timeline_seconds(drawing, inner)
    hand_end = min(hand_seconds(drawing, inner), inner_total)
    hand_start = 0.
    window = _paint_window(drawing, inner)
    if window is not None:
        # exp.151 (the user: the hand moved before anything appeared): a painting starts
        # where the brush first really paints (its first move to the picture is the glide),
        # and ends where it last paints.
        first, last = window
        if getattr(drawing, 'image_animation', None) == 'paint_only' and getattr(drawing, 'source_kind', None) == 'image':
            hand_start = max(0., min(first, hand_end * .9))
        hand_end = max(hand_start + .05, min(hand_end, last))
    back = float(options.get('hand_travel_out', 0) or 0) or travel     # exp.163: its own way back
    return travel, hand_end, back, inner_total, inner, hand_start


_WINDOW = {}


def _paint_window(drawing, options):
    """(first, last): seconds of the element (without the travel) when the painting hand
    first and last really paints, for the planned paintings (adaptive, painter, rows...)."""
    image = options.get('final_image')
    mode = options.get('reveal_mode')
    if image is None or image.isNull() or mode not in ('adaptive', 'zigzag', 'rows', 'columns', 'short_zigzag', 'painter'):
        return None
    if options.get('painting_hand') is None:
        return None
    key = (id(drawing), image.cacheKey(), mode, options.get('brush_width'), options.get('stroke_spacing'),
           options.get('duration'), options.get('fade_duration'))
    if key in _WINDOW:
        return _WINDOW[key]
    try:
        from adaptive_hand import plan_for
        drawing.paint_method = mode
        bw, sp = float(options.get('brush_width', .14)), float(options.get('stroke_spacing', .55))
        plan = plan_for(drawing, image, bw, sp)     # made once (the painting needs it anyway)
        painting = [s for s in plan.segments if s.painting]
        if not painting or plan.total <= 0:
            return None
        paint_only = getattr(drawing, 'image_animation', None) == 'paint_only' and \
            getattr(drawing, 'source_kind', None) == 'image'
        base = 0. if paint_only else max(.001, float(options.get('duration', 4) or 4))
        fade = max(.001, float(options.get('fade_duration', .4)))
        first = base + painting[0].start / plan.total * .98 * fade
        last = base + painting[-1].end / plan.total * .98 * fade
    except Exception:
        return None
    if len(_WINDOW) > 64:
        _WINDOW.clear()
    _WINDOW[key] = (first, last)
    return first, last


def travel_phase(t, lead, hand_end, tail, hand_start=0.):
    """(element time without the travel, 'in' / 'out' / None, 0..1 through the travel).
    hand_start: the element's own time where the hand starts (exp.151: before it, a
    painting's first glide to the picture, skipped: the travel is the glide)."""
    if t < lead:
        return hand_start, 'in', t / max(1e-9, lead)
    t = t - lead + hand_start
    if t < hand_end:
        return t, None, 0.
    if t < hand_end + tail:
        return hand_end, 'out', (t - hand_end) / max(1e-9, tail)
    return t - tail, None, 0.


def hand_window(drawing, options):
    """(seconds from the element's start to when the hand is back in its corner, element
    seconds), or None."""
    plan = travel_plan(drawing, options)
    if plan is None:
        return None
    lead, hand_end, tail, inner_total, _, hand_start = plan
    return lead + hand_end - hand_start + tail, inner_total - hand_start + lead + tail


def hand_busy(drawing, options, fraction):
    """exp.146: True while this element's hand draws, paints, travels or carries the
    picture in. exp.152: an element that slides/fades in without a hand is NOT busy (it
    used to count as busy for its whole time, so a sliding book on a higher track took the
    hand away from the nun being drawn under it: the nun's lines appeared with no hand)."""
    if options.get('hand') is None and options.get('move_hand') is None:
        return False
    try:
        entrance = options.get('entrance') or 'draw'
        if entrance != 'draw':
            import move_in
            plain = timeline_seconds(drawing, dict(options, pause=0))
            t = float(fraction) * timeline_seconds(drawing, options)
            length = move_seconds(options)
            if t < length:
                return 0. < t and move_in.carried(dict(options, layers='all'), ENTRANCES.get(entrance, entrance)
                                                  if entrance in ENTRANCES else entrance) is not None
            if move_in.part_of(options) == move_in.PART_LINES and options.get('hand') is not None:
                return t < min(plain, hand_seconds(drawing, options))
            return False
        if options.get('hand') is None:
            return False
        if options.get('hand_travel'):
            window = hand_window(drawing, options)
            if window is not None:
                return float(fraction) * window[1] < window[0] - 1e-9
        total = timeline_seconds(drawing, options)
        return 0. < float(fraction) * total < hand_seconds(drawing, options)
    except Exception:
        return False


def hand_busy_at(drawing, options, local_seconds):
    """hand_busy at `local_seconds` from the element's start."""
    total = timeline_seconds(drawing, options)
    if total <= 0 or local_seconds < 0 or local_seconds > total:
        return False
    return hand_busy(drawing, options, local_seconds / total)


def resting(drawing, options, fraction):
    """True when, in this element, the hand is back in its corner."""
    window = hand_window(drawing, options)
    if window is None:
        return False
    back, total = window
    return float(fraction) * total >= back - 1e-9


class _FixedCamera:
    """The element's camera at the element's real moment (the travel freezes the drawing,
    not the camera)."""

    def __init__(self, camera, fraction):
        self.camera, self.fraction = camera, float(fraction)

    def at(self, _fraction):
        return self.camera.at(self.fraction)

    def at_seconds(self, _seconds):
        return self.camera.at(self.fraction)

    def __getattr__(self, name):
        if name == 'camera':
            raise AttributeError(name)
        return getattr(self.camera, name)


def rest_rect(width, height, options, seconds=None, place=None):
    """Where the waiting hand is on a frame of this size (exp.147: at `seconds` of the
    video it may be sliding out of the picture, Hand row)."""
    from PySide6.QtCore import QRectF
    hand = options.get('hand')
    if hand is None or hand.isNull():
        return None
    hw = width * float(options.get('hand_scale', .18)) * float(options.get('artwork_scale', 1.) or 1.)
    hh = hw * hand.height() / max(1, hand.width())
    ax, ay = options.get('anchor', (.1, .1))
    fx, fy = REST_CORNERS.get(options.get('hand_rest_corner') or 'Bottom right', REST_CORNERS['Bottom right'])
    # exp.161 (the user): the corner belongs to the page, not to the screen: when the camera
    # zooms, the waiting hand stays at its spot of the page (it can leave the picture), at its
    # own size. place = (x, y, w, h) of the page on the screen (None: the whole screen).
    place = place if place is not None else options.get('_rest_place')
    px, py, pw, ph = place if place is not None else (0., 0., float(width), float(height))
    rect = QRectF(px + fx * pw - float(ax) * hw, py + fy * ph - float(ay) * hh, hw, hh)
    e, side = 0., 'Bottom'
    if options.get('hand_away') and seconds is not None:
        import camera_clips
        e, side = camera_clips.away_at(camera_clips.from_hand_signature(options['hand_away']), seconds)
    out = float(options.get('_rest_out', 0) or 0)      # exp.153: making way for another hand
    if out > e:
        e, side = out, 'Bottom'
    if e > 0:
        dx = dy = 0.
        if side == 'Bottom':
            dy = (height - rect.y() + 4) * e
        elif side == 'Left':
            dx = -(rect.right() + 4) * e
        else:
            dx = (width - rect.x() + 4) * e
        rect.translate(dx, dy)
    return rect


REST_SLIDE = .45     # seconds the waiting hand takes to slide out of the picture and back


def rest_out(items, seconds):
    """exp.153 (the user: the hand vanished and popped back, it should move out of the
    picture and back in): 0..1, how far the waiting hand has slid out of the picture to make
    way for another hand (a hand carrying a picture in) at `seconds` of the video.

    items: (drawing, options, start seconds) of the elements whose hand does not travel
    from the corner (those use the waiting hand itself)."""
    best = 0.
    steps = 9
    for drawing, opts, start in items:
        local = seconds - start
        total = timeline_seconds(drawing, opts)
        if local < -REST_SLIDE or local > total + REST_SLIDE:
            continue
        if hand_busy_at(drawing, opts, local):
            return 1.
        for i in range(1, steps + 1):
            d = REST_SLIDE * i / steps
            if hand_busy_at(drawing, opts, local + d) or hand_busy_at(drawing, opts, local - d):
                e = 1. - d / REST_SLIDE
                best = max(best, e * e * (3 - 2 * e))
                break
    return best


def paint_rest_hand(frame, options, seconds=None, place=None):
    """The hand waiting in its corner, painted on (a copy of) the frame (place: the page on
    the screen, exp.161)."""
    if frame is None or options.get('layers', 'all') == 'art':
        return frame
    rect = rest_rect(frame.width(), frame.height(), options, seconds, place)
    shown = 1. - _hidden(options, seconds)
    if rect is None or shown <= 0:
        return frame
    from PySide6.QtGui import QPainter
    out = frame.copy()
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setOpacity(shown)
    p.drawImage(rect, options['hand'])
    p.end()
    return out


import threading as _threading
_HAND = _threading.local()


def _set_spec(spec):
    _HAND.spec = spec


def last_hand_spec():
    """exp.149: where the hand was in the last frame drawn on this thread (None: no hand)."""
    return getattr(_HAND, 'spec', None)


def _spec_from(got, opts, frame, travel):
    """The hand of this frame, in the frame's own pixels: its pen tip, its picture, how big
    it is next to a plain hand, and its way to / from the corner."""
    if frame is None:
        return None
    w, h = frame.width(), frame.height()
    spec = dict(frame=(w, h), tip=None, image=None, anchor=None, ratio=1.,
                phase=travel[0] if travel else None, p=travel[1] if travel else 0.,
                seconds=(travel[2] if travel and len(travel) > 2 else opts.get('_video_t')))
    if got.get('hands'):
        r, image = got['hands'][-1]
        bw, bh = got['big']
        f = got['scale']
        ox, oy = got['offset']
        x = bw / 2 + (r.x() - bw / 2) * f + round(ox * bw)
        y = bh / 2 + (r.y() - bh / 2) * f + round(oy * bh)
        own0 = getattr(image, 'own_tip', None)
        ax0, ay0 = own0 if own0 is not None else opts.get('anchor', (.1, .1))
        # exp.155: the pen as if there were no camera (the hand over the cameras: their
        # zooms never move it), in this frame's pixels.
        spec['tip_plain'] = ((x + float(ax0) * r.width() * f) * w / max(1, bw),
                             (y + float(ay0) * r.height() * f) * h / max(1, bh))
        if got['zoom'] > 1.0001:                     # the camera's crop (camera.crop)
            cx, cy = got['centre']
            x -= max(0, min(bw - w, int(round(cx * bw - w / 2))))
            y -= max(0, min(bh - h, int(round(cy * bh - h / 2))))
        mw, mh = r.width() * f, r.height() * f
        own = getattr(image, 'own_tip', None)
        ax, ay = own if own is not None else opts.get('anchor', (.1, .1))
        nominal = bw * float(opts.get('hand_scale', .18)) * f
        spec.update(tip=(x + float(ax) * mw, y + float(ay) * mh), image=image, anchor=(float(ax), float(ay)),
                    ratio=(mw / nominal) if nominal > 0 else 1.)
    elif not travel:
        return None
    return spec


def _crop_spec(spec, frame, zoom, cx, cy):
    """The spec's pen tip after _camera_view(frame, zoom, cx, cy)."""
    if spec is None or spec.get('tip') is None or zoom <= 1.0001:
        return spec
    w, h = frame.width(), frame.height()
    vw, vh = w / zoom, h / zoom
    left = min(max(0., cx * w - vw / 2), w - vw)
    top = min(max(0., cy * h - vh / 2), h - vh)
    x, y = spec['tip']
    return dict(spec, tip=((x - left) * zoom, (y - top) * zoom))


def _paint_move_hand(frame, spec, tip, shown, options):
    """The move-in hand at `tip` (screen pixels), its own size (Hand tab) on the screen: the
    camera does not zoom it. (exp.152 made it as big as the drawing hand: far too big.)"""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainter
    import move_in
    image = spec['image']
    hw = max(1., float(spec.get('share', .35)) * frame.width())
    hh = hw * image.height() / max(1, image.width())
    out = frame.copy()
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(shown)
    painter.translate(QPointF(tip[0], tip[1]))
    painter.rotate(move_in.ANGLES[spec['side']])
    gx, gy = spec.get('anchor') or move_in.DEFAULT_GRIP
    painter.drawImage(QRectF(-gx * hw, -gy * hh, hw, hh), image)
    painter.end()
    return out


# exp.164 (the user): different ways for the hand to go to the drawing and back.
GLIDE_STYLES = ('Smooth', 'Steady', 'Quick start', 'Slow start', 'Overshoot', 'Curve', 'Swoop')


def _glide_ease(p, style):
    p = max(0., min(1., float(p)))
    if style == 'Steady':
        return p
    if style in ('Quick start', 'Swoop'):
        return 1 - (1 - p) ** 3
    if style == 'Slow start':
        return p ** 3
    if style == 'Overshoot':                 # goes a little past and settles back
        c1 = 1.70158; c3 = c1 + 1
        return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2
    return p * p * (3 - 2 * p)               # Smooth


def glide_point(a, b, p, style='Smooth'):
    """Where the hand is at p (0..1) of its way from a to b, in this style. Curve and Swoop
    go along an arc (bulging up) instead of a straight line."""
    e = _glide_ease(p, style)
    x = a[0] + (b[0] - a[0]) * e
    y = a[1] + (b[1] - a[1]) * e
    if style in ('Curve', 'Swoop'):
        import math
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length > 1e-6:
            bulge = .25 * length * math.sin(math.pi * max(0., min(1., e)))
            nx, ny = -dy / length, dx / length          # perpendicular
            if ny > 0:                                  # always bulge upwards
                nx, ny = -nx, -ny
            x += nx * bulge; y += ny * bulge
    return (x, y)


def paint_hand_spec(frame, spec, options, place=None):
    """exp.149: draw the hand on the screen picture `frame`: at the pen tip (mapped through
    `place` = (x, y, w, h) of the element's picture on the screen, None: the whole frame),
    always the same size (the hand size of the settings, not the camera's zoom); gliding
    between its corner and the pen; faded by the Hand row."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    if frame is None or spec is None or options.get('layers', 'all') == 'art':
        return frame
    W, H = frame.width(), frame.height()
    shown = 1. - _hidden(options, spec.get('seconds'))
    if shown <= 0:
        return frame
    tip = spec.get('tip')
    if tip is not None:
        fw, fh = spec['frame']
        if place is not None:
            px, py, pw, ph = place
            tip = (px + tip[0] * pw / max(1, fw), py + tip[1] * ph / max(1, fh))
        elif (fw, fh) != (W, H):
            tip = (tip[0] * W / max(1, fw), tip[1] * H / max(1, fh))
    if spec.get('kind') == 'move':
        if tip is None or spec.get('image') is None or spec['image'].isNull():
            return frame
        return _paint_move_hand(frame, spec, tip, shown, options)
    image, anchor, ratio = spec.get('image'), spec.get('anchor'), float(spec.get('ratio') or 1.)
    phase = spec.get('phase')
    if phase in ('in', 'out'):
        corner = rest_rect(W, H, options, spec.get('seconds'))
        hand = options.get('hand')
        if corner is None or hand is None or hand.isNull():
            return frame
        ax, ay = options.get('anchor', (.1, .1))
        home = (corner.x() + float(ax) * corner.width(), corner.y() + float(ay) * corner.height())
        target = spec.get('screen_target') or (tip if tip is not None else home)
        p = max(0., min(1., float(spec.get('p') or 0.)))
        style = options.get('hand_glide_style_in' if phase == 'in' else 'hand_glide_style_out') or 'Smooth'
        a, b = (home, target) if phase == 'in' else (target, home)
        tip = glide_point(a, b, p, style)
        image, anchor, ratio = hand, (float(ax), float(ay)), 1.
    if tip is None or image is None or image.isNull():
        return frame
    hw = W * float(options.get('hand_scale', .18)) * float(options.get('artwork_scale', 1.) or 1.) * ratio
    hh = hw * image.height() / max(1, image.width())
    out = frame.copy()
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(shown)
    painter.drawImage(QRectF(tip[0] - anchor[0] * hw, tip[1] - anchor[1] * hh, hw, hh), image)
    painter.end()
    return out


def _hidden(options, seconds):
    """exp.148: 0..1, how hidden the hand is at `seconds` of the video (Hand row)."""
    if seconds is None or not options.get('hand_away'):
        return 0.
    import camera_clips
    return camera_clips.hidden_at(camera_clips.from_hand_signature(options['hand_away']), seconds)
