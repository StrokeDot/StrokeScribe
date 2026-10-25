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
    opts.update(width=max(2, int(round(width))), height=max(2, int(round(height))), layers=layers, ghost=0)
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


def compose(world, lay, state, elements, width, height, titles=None, seconds=None, view_scale=1.):
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
    view = view_of(world, lay, state, elements)
    if view_scale > 1.:                  # exp.121: the preview stepped back (Ctrl + wheel)
        view = (view[0], view[1], view[2] * view_scale)
    return _page(world, lay, state, elements, view, width, height, titles, seconds)


def _texts(out, items, seconds, copied=False):
    if not items or seconds is None:
        return out
    import overlays
    if not any(overlays.state_at(o, seconds) is not None for o in items):
        return out
    if not copied:
        out = out.copy()                 # never draw into a picture kept by the board
    return overlays.paint(out, items, seconds)


def _page(world, lay, state, elements, view, width, height, titles=None, seconds=None):
    skip = set(range(len(elements))) - set(state.finished)
    out = world.view(view, width, height, upto=len(elements), skip=skip)
    tracks = {it.k: it.track for it in lay.items}
    waiting = sorted(titles or (), key=lambda o: int(o.get('track', 0)))
    for k, fraction in state.active:
        under = [o for o in waiting if int(o.get('track', 0)) < tracks.get(k, 0)]
        if under:
            out = _texts(out, under, seconds)
            waiting = [o for o in waiting if o not in under]
        x, y, w, h = world.place(world.frames[k], view, width, height)
        if w < 2 or x > width or y > height or x + w < 0 or y + h < 0:
            continue
        el = elements[k]
        opts = el['options']
        art = element_frame(el['drawing'], opts, fraction, w, h, 'art')
        out = world.put(out, art, world.frames[k], view, opts.get('blend_mode', 'Normal'),
                        opts.get('artwork_opacity', 100))
        if k == state.top and opts.get('layers', 'all') != 'art':
            hand = element_frame(el['drawing'], opts, fraction, w, h, 'hand')
            out = world.put(out, hand, world.frames[k], view)
    return _texts(out, waiting, seconds)
