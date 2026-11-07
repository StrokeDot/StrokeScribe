"""Eraser clips (exp.186, the user): an eraser is put on the timeline like a text, so it can come
before or after a camera move. It rubs out one element on its page, whether the camera shows it
or not (you can come back to that place later and it is gone).

While it erases a page the camera shows, the waiting drawing hand goes down out of the picture
and the eraser comes in (only one hand at a time); erasing a page that is not shown happens
quietly, nothing waits for it.
"""
from __future__ import annotations

MODES = {'Zigzag (follows the shapes)': 'zigzag', 'Along the lines': 'lines'}
# exp.192 (the user: treat them all as one way out): what the clip does: the eraser, or an effect
EFFECTS = {'Eraser': None, 'Fade out': 'fade', 'Pop out': 'pop', 'Zoom out': 'zoom', 'Spin out': 'spin',
           'Move out to the left': 'out-left', 'Move out to the right': 'out-right',
           'Move out to the top': 'out-top', 'Move out to the bottom': 'out-bottom'}


def effect_of(item):
    """The exit effect (frame_render.EXITS key) of the clip, or None for the eraser."""
    return EFFECTS.get(item.get('effect') or 'Eraser')


def with_hand(item):
    """The eraser (or its hand) is seen rubbing: only for the eraser, when the clip says so."""
    return effect_of(item) is None and item.get('hand', True) is not False
# exp.190 (the user: an eraser hand): what rubs: the eraser, the drawing hand, or your own picture
TOOLS = ('Built-in eraser', 'Pen hand', 'My picture…')
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


GLIDE = .8          # exp.197: the eraser hand comes in before the clip and leaves after it (s)


def leaves(item):
    """exp.197: while it erases, the drawing hand leaves the picture (else it stays in its corner)."""
    return item.get('drawing_hand') == 'leaves'


def other_hand(item):
    """exp.197: the eraser is held in the other hand (else the same hand as the pencil)."""
    return item.get('eraser_in', 'other') != 'same'


def glides(items, elements, seconds):
    """exp.197: [(k, clip, 'in' | 'out', 0..1)]: an eraser hand on its way in (before its clip)
    or out (after it), from / to the bottom edge on its own side."""
    out = []
    if seconds is None:
        return out
    t = float(seconds)
    for item in clips(items):
        if not with_hand(item):
            continue
        k = target_of(item, elements)
        if k is None:
            continue
        start, end = float(item.get('start', 0)), float(item.get('start', 0)) + max(.2, float(item.get('duration', 3)))
        if start - GLIDE <= t < start:
            out.append((k, item, 'in', (t - (start - GLIDE)) / GLIDE))
        elif end <= t < end + GLIDE:
            out.append((k, item, 'out', (t - end) / GLIDE))
    return out


def tool_key(item):
    return (item.get('tool') or 'Built-in eraser', item.get('tool_path'))


_PICTURES = {}


def _picture(path):
    """(picture, rubbing spot) of your own eraser picture: its plain background (black,
    white...) made see-through, and the rubbing spot found like a pen tip (the point farthest
    from where the arm comes in) (exp.190)."""
    if path not in _PICTURES:
        from PIL import Image
        from adaptive_hand import qimage
        import png_cleanup, hand_tip
        try:
            with Image.open(str(path)) as im:
                clean = png_cleanup.clean_background(im.convert('RGBA'))
            picture = qimage(clean)
            tip = hand_tip.find_tip(picture)
            spot = (tip[0], tip[1]) if tip else (.2, .85)
        except Exception:
            from PySide6.QtGui import QImage
            picture, spot = QImage(str(path)), (.2, .85)
        _PICTURES[path] = (picture, spot)
    return _PICTURES[path]


def side_of(options, item):
    """'left' / 'right': the side the eraser hand comes from (the hand that holds it)."""
    look = options.get('eraser_tool') or {}
    writes_left = bool(look.get('left'))
    return ('right' if writes_left else 'left') if other_hand(item) else ('left' if writes_left else 'right')


def erase_options(options, item, hand=None):
    """The element's render options with this eraser as its way out (frame_render's eraser).

    exp.192: what rubs comes from the element's Hand panel (Eraser hand: the built-in eraser,
    the pen hand or your own picture, and its size). The user's rule: a hand that erases is
    the OTHER hand of the one that writes (a right-handed writer erases with the left)."""
    from export_job import erase_from_settings
    mode = {v: k for k, v in MODES.items()}.get(item.get('mode') or 'zigzag', 'Zigzag (follows the shapes)')
    look = options.get('eraser_tool') or {}
    tool = look.get('kind') or item.get('tool') or 'Built-in eraser'
    path = look.get('path') if look.get('kind') else item.get('tool_path')
    size = float(look.get('size') or .45)
    left = bool(look.get('left'))                   # the writing hand is the left one
    pen = options.get('hand') if hand is None else hand
    erase = erase_from_settings({'erase_mode': mode, 'erase_size': SIZE * 100, 'erase_time': 1.,
                                 'eraser': 'Built-in eraser', 'left_handed': left}, None)
    picture, spot = None, None
    if tool == 'Pen hand' and pen is not None and not pen.isNull():
        a = options.get('anchor') or (.08, .13)
        picture, spot = pen, (float(a[0]), float(a[1]))
        size = float(look.get('size') or .45)
    elif tool == 'My picture…' and path:
        picture, spot = _picture(path)
        if picture.isNull():
            picture = None
    if picture is not None:
        # the other hand: the pen hand as it writes, mirrored; your picture is taken as a right
        # hand, so it is mirrored for a right-handed writer. exp.197: the same hand: as written.
        from tools_kit import mirrored
        mirror = (tool == 'Pen hand' or not left) if other_hand(item) else (tool != 'Pen hand' and left)
        if mirror:
            picture, spot = mirrored(picture), (1 - spot[0], spot[1])
        erase = dict(erase, image=picture, anchor=spot, width=size)
    if not with_hand(item) or look.get('on') is False:
        erase = dict(erase, image=None)          # exp.195: the Eraser hand switch (Hand panel)
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
        if k is None or not with_hand(item) or not leaves(item):     # exp.197: only when it leaves
            continue
        start, length = float(item.get('start', 0)), max(.2, float(item.get('duration', 3)))
        try:
            shown = page_at(start)
        except Exception:
            shown = None
        if shown is None or frames[shown] != frames[k]:
            continue                                  # not seen: nothing waits for it
        out.append(dict(id='eraser-' + str(item.get('id')), kind='Hand leaves', side='Bottom',
                        start=max(0., start - GLIDE - OUT_S), duration=length + 2 * (GLIDE + OUT_S),
                        in_s=OUT_S, out_s=OUT_S))
    return out
