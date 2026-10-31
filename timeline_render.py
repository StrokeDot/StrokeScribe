"""Draw one moment of the whole video when elements overlap in time (timeline_model.py).

The classic video (every element after the one before it, all on Track 1) keeps its
own, older drawing code in the preview and the export; this is used once elements
are placed on tracks or given their own start.

At a moment: the camera view (the current element's page, or a camera move), the
finished pictures of the elements already drawn, then every element being drawn at
that moment, bottom track first, each at its own point in time. Only the top one
shows its hand (two hands drawing at once would look wrong); an element's own
"show hand" settings still apply to it.
"""
from __future__ import annotations


def element_frame(drawing, options, fraction, width, height, layers):
    """One element alone at `fraction` of its own time, `width` x `height`, layers 'art' or 'hand'."""
    from frame_render import compose_frame
    opts = {k: v for k, v in options.items() if k not in ('fps', 'audio', 'workers')}
    opts.update(width=max(2, int(round(width))), height=max(2, int(round(height))), layers=layers, ghost=0,
                _hand_later=True)            # exp.149: the page draws the hand (screen size)
    if layers == 'hand':
        opts['background'] = False
    return compose_frame(drawing, max(0., min(1., fraction)), opts)


def view_of(world, lay, state, elements):
    """The camera's view (cx, cy, w) on the board for this state."""
    import board
    frames = world.frames
    if state.kind == 'move':
        k = state.move
        kind = elements[k].get('transition', 'Camera move')
        nxt = elements[k + 1].get('camera') if k + 1 < len(elements) else None
        return board.join_view(frames, k, kind, state.t, world.aspect, elements[k].get('move_seconds', 1.),
                               leaving=elements[k].get('camera'), arriving=nxt)
    k = state.current
    view = frames[k]
    camera = elements[k].get('camera')
    if camera is not None:
        fraction = dict(state.active).get(k, 1.)
        view = board.sub_view(view, *camera.at(fraction), world.aspect)
    return view


def plain_view(world, state):
    """exp.155: the view with no camera at all (no zoom, no pan): the page shown."""
    if state.kind == 'move':
        return world.frames[min(state.move + 1, len(world.frames) - 1)] if state.t >= .5 else world.frames[state.move]
    return world.frames[state.current]


def fixed_view(world, lay, state, elements):
    """exp.162 (the user): what the Fixed camera shows (its moves and the moves between pages),
    without the Moving camera's zooms: the waiting hand's corner is a corner of this view, so a
    fixed camera leaves the hand in the corner of the picture and a zoom carries it."""
    import board
    import camera_clips
    if state.kind == 'move':
        return view_of(world, lay, state, elements)
    k = state.current
    camera = elements[k].get('camera')
    clips = [c for c in (getattr(camera, 'clips', None) or ()) if camera_clips.fixed(c)]
    if not clips:
        return world.frames[k]
    cam = camera_clips.VideoCamera(None, camera.start, clips, camera.moves, camera.total)
    return board.sub_view(world.frames[k], *cam.at(dict(state.active).get(k, 1.)), world.aspect)


def page_place(world, lay, state, elements, width, height, view_scale=1., view_pan=(0., 0.)):
    """exp.161/162: (x, y, w, h) on the screen of what the Fixed camera shows: the Moving
    camera's zooms move and size it; the waiting hand keeps its corner on it."""
    v = view_of(world, lay, state, elements)
    if view_scale > 1.:
        w = v[2] * view_scale
        v = (v[0] + view_pan[0] * w, v[1] + view_pan[1] * w * world.aspect, w)
    return world.place(fixed_view(world, lay, state, elements), v, width, height)


def compose(world, lay, state, elements, width, height, titles=None, seconds=None, view_scale=1., view_pan=(0., 0.)):
    """The whole video at this moment, width x height.

    elements[k]: {'drawing', 'options' (compose_frame options at the video size),
                  'camera' (camera follow path or None), 'transition', 'move_seconds'}.

    titles (exp.118): texts / pictures on top, each on a track like the elements: drawn on
    the screen at `seconds`, over the elements of lower tracks and under the elements being
    drawn on higher tracks."""
    import board
    from scenes import transition_frame
    if state.kind == 'move':
        k = state.move
        kind = elements[k].get('transition', 'Camera move')
        last = k == len(elements) - 1
        if kind in board.SCREEN_KINDS and not last and view_scale <= 1.:
            a = _page(world, lay, state, elements, world.frames[k], width, height)
            b = _page(world, lay, state, elements, world.frames[k + 1], width, height)
            return _texts(transition_frame(a, b, kind, state.t), titles, seconds)
    def view_fn(st, plain=False):
        v = plain_view(world, st) if plain else view_of(world, lay, st, elements)
        if view_scale > 1.:              # exp.121: the preview stepped back (Ctrl + wheel)
            w = v[2] * view_scale        # exp.122: and moved around by dragging it
            v = (v[0] + view_pan[0] * w, v[1] + view_pan[1] * w * world.aspect, w)
        return v
    return _page(world, lay, state, elements, view_fn(state), width, height, titles, seconds, view_fn)


def page_of(lay, seconds):
    """exp.123: the page a text belongs to: the page the camera shows when it starts."""
    from timeline_model import state_at
    if not lay.items:
        return 0
    st = state_at(lay, max(0., float(seconds)))
    if st.kind == 'page':
        return st.current
    return min(st.move + 1, len(lay.items) - 1)


def paint_texts(out, items, seconds, frames=None, place=None, view=None):
    """exp.123: texts live on their page like the drawings: each is drawn where its page is
    in this view (so the camera moves and zooms past it). Without a view: on the screen."""
    import overlays
    if not items or seconds is None:
        return out
    shown = [o for o in items if overlays.state_at(o, seconds) is not None]
    if not shown:
        return out
    out = out.copy()                     # never draw into a picture kept by the board
    w, h = out.width(), out.height()
    if view is None or frames is None or place is None:
        return overlays.paint(out, shown, seconds)
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    groups = {}
    for o in shown:
        groups.setdefault(min(max(0, int(o.get('_page', 0) or 0)), len(frames) - 1), []).append(o)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for k, group in groups.items():
        x, y, rw, rh = place(frames[k], view, w, h)
        if rw < 2 or x > w or y > h or x + rw < 0 or y + rh < 0:
            continue
        layer = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied); layer.fill(0)
        overlays.paint(layer, group, seconds)
        painter.drawImage(QRectF(x, y, rw, rh), layer)
    painter.end()
    return out


def _texts(out, items, seconds, world=None, view=None):
    if world is None:
        return paint_texts(out, items, seconds)
    return paint_texts(out, items, seconds, world.frames, world.place, view)


def _hand_element(state, elements, tracks):
    """exp.146: the element whose hand shows: the highest one whose hand is drawing or
    travelling now. It used to be simply the top element being drawn, so an element still
    holding its finished picture on a higher track hid the hand of the one drawing (the
    user: the hand disappeared going to the drawing and always going back)."""
    from frame_render import hand_busy
    busy = [k for k, f in state.active
            if elements[k]['options'].get('layers', 'all') != 'art'
            and hand_busy(elements[k]['drawing'], elements[k]['options'], f)]
    if not busy:
        return state.top
    return max(busy, key=lambda k: (tracks.get(k, 0), k))


def _glide_target(world, lay, elements, k, fraction, phase, seconds, view_fn, width, height):
    """exp.154 (the user: while the camera zooms and nothing is drawn yet, the hand must not
    follow the camera): where on the screen the pen will be when the drawing starts (the way
    in) or was when it stopped (the way back). The hand glides straight between its corner
    and that point; it used to aim at the first point as the camera showed it at each moment,
    so during a zoom it chased the camera."""
    from frame_render import travel_plan, timeline_seconds, last_hand_spec
    from timeline_model import state_at
    el = elements[k]
    drawing, opts = el['drawing'], el['options']
    try:
        plan = travel_plan(drawing, opts)
        if plan is None:
            return None
        lead, hand_end, tail, inner_total, _, hand_start = plan
        total = timeline_seconds(drawing, opts)
        t = float(fraction) * total
        eps = .02
        when = lead + eps if phase == 'in' else lead + hand_end - hand_start - eps
        st = state_at(lay, max(0., seconds + when - t))
        f = dict(st.active).get(k)
        if f is None:
            return None
        view = view_fn(st)
        x, y, w, h = world.place(world.frames[k], view, width, height)
        if w < 2:
            return None
        element_frame(drawing, opts, f, w, h, 'hand')
        spec = last_hand_spec()
        if spec is None or spec.get('tip') is None or spec.get('phase') in ('in', 'out'):
            return None
        fw, fh = spec['frame']
        return (x + spec['tip'][0] * w / max(1, fw), y + spec['tip'][1] * h / max(1, fh))
    except Exception:
        return None


def _drawing_now(state, elements, k):
    """True when element k's hand is drawing, painting or travelling now."""
    from frame_render import hand_busy
    for j, f in state.active:
        if j == k:
            o = elements[k]['options']
            return o.get('layers', 'all') != 'art' and hand_busy(elements[k]['drawing'], o, f)
    return False


def _page(world, lay, state, elements, view, width, height, titles=None, seconds=None, view_fn=None):
    skip = set(range(len(elements))) - set(state.finished)
    out = world.view(view, width, height, upto=len(elements), skip=skip)
    tracks = {it.k: it.track for it in lay.items}
    waiting = sorted(titles or (), key=lambda o: int(o.get('track', 0)))
    hand_k = _hand_element(state, elements, tracks)
    hand_layer = None
    active = list(state.active)
    if _drawing_now(state, elements, hand_k):
        # exp.152 (the user): the picture the hand is drawing is always seen while it draws:
        # it comes over the other pictures on the page (a nun on a lower track was drawn
        # under a book that was still sliding in, so her lines were hidden and the hand
        # drew nothing). When its hand is done, it goes back to its track's place.
        active = [a for a in active if a[0] != hand_k] + [a for a in active if a[0] == hand_k]
    for k, fraction in active:
        under = [o for o in waiting if int(o.get('track', 0)) < tracks.get(k, 0)]
        if under:
            out = _texts(out, under, seconds, world, view)
            waiting = [o for o in waiting if o not in under]
        x, y, w, h = world.place(world.frames[k], view, width, height)
        if w < 2 or x > width or y > height or x + w < 0 or y + h < 0:
            continue
        el = elements[k]
        opts = el['options']
        art = element_frame(el['drawing'], opts, fraction, w, h, 'art')
        out = world.put(out, art, world.frames[k], view, opts.get('blend_mode', 'Normal'),
                        opts.get('artwork_opacity', 100))
        if k == hand_k and opts.get('layers', 'all') != 'art':
            from frame_render import last_hand_spec
            layer = element_frame(el['drawing'], opts, fraction, w, h, 'hand')   # eraser, move-in hand
            spec = last_hand_spec()
            place = (x, y, w, h)
            # exp.160 (the user): the pencil is always on the line it draws, wherever the camera
            # shows it. exp.161: its corner is a spot of the page too, so on its way between them
            # the hand is carried by the camera like the page (its size never changes).
            if spec is not None and spec.get('phase') in ('in', 'out') and view_fn is not None:
                opts = dict(opts, _rest_place=world.place(fixed_view(world, lay, state, elements), view_fn(state), width, height))
            hand_layer = (layer, world.frames[k], spec, place, opts)
    out = _texts(out, waiting, seconds, world, view)
    if hand_layer is not None:
        # exp.148 (the user): the hand is always over everything (it was drawn under the
        # pictures of higher tracks, e.g. under a book). exp.149: on the screen, its own size.
        from frame_render import paint_hand_spec
        layer, frame, spec, place, opts = hand_layer
        out = world.put(out, layer, frame, view)
        out = paint_hand_spec(out, spec, dict(opts, width=width, height=height), place)
    return out
