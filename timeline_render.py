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
        return board.join_view(frames, k, kind, state.t, world.aspect, elements[k].get('move_seconds', 1.))
    k = state.current
    view = frames[k]
    camera = elements[k].get('camera')
    if camera is not None:
        fraction = dict(state.active).get(k, 1.)
        view = board.sub_view(view, *camera.at(fraction), world.aspect)
    return view


def compose(world, lay, state, elements, width, height):
    """The whole video at this moment, width x height.

    elements[k]: {'drawing', 'options' (compose_frame options at the video size),
                  'camera' (camera follow path or None), 'transition', 'move_seconds'}."""
    import board
    from scenes import transition_frame
    if state.kind == 'move':
        k = state.move
        kind = elements[k].get('transition', 'Camera move')
        last = k == len(elements) - 1
        if kind in board.SCREEN_KINDS and not last:
            a = _page(world, lay, state, elements, world.frames[k], width, height)
            b = _page(world, lay, state, elements, world.frames[k + 1], width, height)
            return transition_frame(a, b, kind, state.t)
    return _page(world, lay, state, elements, view_of(world, lay, state, elements), width, height)


def _page(world, lay, state, elements, view, width, height):
    skip = set(range(len(elements))) - set(state.finished)
    out = world.view(view, width, height, upto=len(elements), skip=skip)
    for k, fraction in state.active:
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
    return out
