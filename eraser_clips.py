"""Eraser clips (exp.186, the user): an eraser is put on the timeline like a text, so it can come
before or after a camera move. It rubs out one element on its page, whether the camera shows it
or not (you can come back to that place later and it is gone).

While it erases a page the camera shows, the waiting drawing hand goes down out of the picture
and the eraser comes in (only one hand at a time); erasing a page that is not shown happens
quietly, nothing waits for it.
"""
from __future__ import annotations

MODES = {'Zigzag (follows the shapes)': 'zigzag', 'Along the lines': 'lines'}
SIZE = .08                     # the eraser's size, share of the picture's width
WORK_WIDTH = 1280             # the erasing is worked out at this size, whatever the zoom
OUT_S = .45                    # the drawing hand goes down / comes back in this long


def clips(items):
    return [o for o in items or () if o.get('kind') == 'eraser']


def target_of(item, elements):
    """The element index the clip erases, or None."""
    uid = item.get('target')
    for k, el in enumerate(elements):
        if uid and el.get('uid') == uid:
            return k
    k = item.get('target_k')
    return int(k) if k is not None and 0 <= int(k) < len(elements) else None


def progress(item, seconds):
    """0 before the clip, 0..1 while it erases, 1 after (the element stays erased)."""
    start, length = float(item.get('start', 0)), max(.2, float(item.get('duration', 3)))
    return max(0., min(1., (float(seconds) - start) / length))


def at(items, elements, seconds):
    """{element index: (progress, clip)} of the erasers that have begun by `seconds`."""
    out = {}
    if seconds is None:
        return out
    for item in clips(items):
        k = target_of(item, elements)
        if k is None or float(seconds) < float(item.get('start', 0)):
            continue
        p = progress(item, seconds)
        if k not in out or p > out[k][0]:
            out[k] = (p, item)
    return out


def erase_options(options, item, hand=None):
    """The element's render options with this eraser as its way out (frame_render's eraser)."""
    from export_job import erase_from_settings
    mode = {v: k for k, v in MODES.items()}.get(item.get('mode') or 'zigzag', 'Zigzag (follows the shapes)')
    erase = erase_from_settings({'erase_mode': mode, 'erase_size': SIZE * 100, 'erase_time': 1.,
                                 'eraser': 'Built-in eraser',
                                 'left_handed': bool(options.get('_left_handed'))}, hand)
    opts = {k: v for k, v in options.items() if k not in ('hand_travel', 'hand_travel_out', 'hand_rest_here',
                                                       'hand_away', '_video_t', 'pause', 'erase')}
    opts.update(erase=erase, pause=0.)
    return opts


def fraction_for(drawing, options, p):
    """The element's own fraction that shows its eraser at progress p (0..1)."""
    from frame_render import timeline_seconds
    base = timeline_seconds(drawing, {k: v for k, v in options.items() if k != 'erase'})
    seconds = max(.1, float((options.get('erase') or {}).get('seconds', 1.)))
    return min(1., (base + max(1e-4, p) * seconds) / (base + seconds))


def hand_leaves(items, elements, frames, page_at):
    """'Hand leaves' clips (camera_clips) for the erasers on the page being shown: the waiting
    hand goes down out of the picture while the eraser works, and comes back."""
    out = []
    for item in clips(items):
        k = target_of(item, elements)
        if k is None:
            continue
        start, length = float(item.get('start', 0)), max(.2, float(item.get('duration', 3)))
        try:
            shown = page_at(start)
        except Exception:
            shown = None
        if shown is None or frames[shown] != frames[k]:
            continue                                  # not seen: nothing waits for it
        out.append(dict(id='eraser-' + str(item.get('id')), kind='Hand leaves', side='Bottom',
                        start=max(0., start - OUT_S), duration=length + 2 * OUT_S, in_s=OUT_S, out_s=OUT_S))
    return out
