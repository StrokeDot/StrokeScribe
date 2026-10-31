"""Camera clips: the video's camera track (exp.119), like an adjustment layer in Filmora.

A camera clip sits on the Camera track at its own time and moves the camera for the
whole picture (every track under it): zoom in, zoom out, pan, or a custom framing that is
dragged on the preview.

    clip = {'id', 'kind', 'start', 'duration',
            'to': (zoom, centre x, centre y),       # where the camera ends up
            'from': (zoom, x, y) or None}           # None: from wherever the camera is

Zoom 1 is the page as the camera shows it without clips; zoom 2 is twice as close.
Centres are fractions of that page view.

The rules (agreed with the user):
* The clip's length is its speed: the camera eases from where it is to the framing
  over the clip, then holds that framing.
* The camera moves between elements (transitions) have the last word: a held framing
  lasts until the next transition; the transition starts from it and takes over
  gradually (board.join_view, `leaving`), then the new page starts unzoomed.
* Two clips: the later one starts from wherever the earlier one has the camera.

Plain Python (no Qt); the paths here have the same `at(fraction)` / `at_seconds(s)` as
the element camera paths (camera.py), so preview and export use them unchanged.
"""
from __future__ import annotations

import math
import uuid

CUSTOM = 'Move to a spot'      # exp.121 (was 'Custom'): drag the frame where the camera goes
# exp.124: a camera clip goes in, holds, and comes back to the normal frame; zoom out is its
# way back (no 'Zoom out' kind any more).
# exp.128 (the user): a fixed camera goes to a framing and STAYS there (until the next fixed
# camera or the next move between pages); the others (moving camera) go, stay a moment and
# come back.
FIXED = 'Fixed camera'
ZOOM_OUT = 'Zoom out'      # exp.159 (the user, like VideoScribe): goes further away than the page, stays, comes back
FAR, NEAR = .2, 10.         # exp.159: how far a camera can go out and how close it can go in
MENU = ('Zoom in', ZOOM_OUT)
HAND = 'Hand leaves'       # exp.147: on the Hand row: the waiting hand slides out of the picture and back
HIDE = 'Hand hidden'       # exp.148: on the Hand row: the hand fades away (also while drawing) and back
HAND_KINDS = (HAND, HIDE)
SIDES = ('Right', 'Bottom', 'Left')   # exp.142 (the user): + Add camera offers these two
MOVING = ('Zoom in', ZOOM_OUT, 'Pan left', 'Pan right', 'Pan up', 'Pan down', CUSTOM)
KINDS = MOVING + (FIXED,)
FOREVER = 1e9
REST = (1., .5, .5)
PAN_ZOOM = 1.4
IN_SECONDS = 1.2
OUT_SECONDS = 1.2
HOLD_SECONDS = 2.


def new_clip(kind='Zoom in', start=0., duration=None):
    """A camera clip: `in_s` seconds to get there, it holds, `out_s` seconds back to the
    normal frame; `duration` is the whole clip (in + hold + out)."""
    if duration is None:
        duration = IN_SECONDS if kind == FIXED else IN_SECONDS + HOLD_SECONDS + OUT_SECONDS
    if kind == HIDE and duration == IN_SECONDS + HOLD_SECONDS + OUT_SECONDS:
        duration = 2.6
    total = float(duration)
    clip = dict(id=uuid.uuid4().hex[:10], kind=kind, start=round(float(start), 2),
                duration=round(max(.4, total), 2), in_s=IN_SECONDS, out_s=OUT_SECONDS,
                to=None, **{'from': None})
    clip['from'], clip['to'] = presets(kind)
    if kind == HIDE:                     # a quick fade out and in
        clip['in_s'] = clip['out_s'] = .3
    fit(clip)
    return clip


def fit(clip):
    """In and back times fit in the clip (each at least .1 s; the hold can be 0)."""
    if clip.get('kind') == FIXED:                 # only one move (there)
        d = round(max(.2, float(clip.get('duration', IN_SECONDS))), 2)
        clip['duration'], clip['in_s'], clip['out_s'] = d, d, 0.
        return clip
    total = max(.4, float(clip.get('duration', 4.4)))
    a, b = max(.1, float(clip.get('in_s', IN_SECONDS))), max(.1, float(clip.get('out_s', OUT_SECONDS)))
    if a + b > total:
        scale = total / (a + b)
        a, b = a * scale, b * scale
    clip['duration'], clip['in_s'], clip['out_s'] = round(total, 2), round(a, 2), round(b, 2)
    return clip


def upgrade(clip):
    """Camera clips from exp.119-123 ('duration' was how long it took to get there; it then
    stayed): the same way in, a 2 s hold, the same time back."""
    if 'in_s' not in clip:
        ramp = max(.2, float(clip.get('duration', 1.2)))
        clip['in_s'], clip['out_s'] = ramp, ramp
        clip['duration'] = ramp * 2 + HOLD_SECONDS
        clip.pop('back', None)
        if clip.get('kind') == 'Zoom out':
            clip['kind'], clip['from'], clip['to'] = 'Zoom in', None, (1.6, .5, .5)
    if clip.get('kind') in ('Custom', CUSTOM):
        # exp.157 (the user): only Zoom in and Zoom out; a "zoom to a spot" is a zoom in with
        # its own place (X, Y) and closeness. It looks exactly the same.
        clip['kind'] = 'Zoom in'
    if clip.get('kind') == ZOOM_OUT and float(clip.get('out_s', 0) or 0) <= 0:
        # exp.159: a zoom out used to start close and open out to the page; now it goes
        # further away than the page, stays, and comes back.
        clip['in_s'] = clip['out_s'] = IN_SECONDS
        clip['duration'] = IN_SECONDS + HOLD_SECONDS + OUT_SECONDS
        clip['from'], clip['to'] = None, (.6, .5, .5)
    return fit(clip)


def keep_in(framing):
    """(zoom, x, y) with the view on the page when it is closer than the page; further away
    than the page (zoom < 1) it can look anywhere."""
    z, x, y = framing
    z = max(FAR, min(NEAR, float(z)))
    half = .5 / z if z >= 1 else 0.
    return (round(z, 3), max(half, min(1 - half, float(x))), max(half, min(1 - half, float(y))))


def presets(kind):
    """(from, to): pans start at 'from' (the camera gets there first), slide to 'to' while
    holding; zooms (from None) go straight to 'to'."""
    side = .5 - .5 / PAN_ZOOM                       # how far the view can go at PAN_ZOOM
    return {
        'Zoom in': (None, (1.6, .5, .5)),
        'Pan left': ((PAN_ZOOM, .5 + side, .5), (PAN_ZOOM, .5 - side, .5)),
        'Pan right': ((PAN_ZOOM, .5 - side, .5), (PAN_ZOOM, .5 + side, .5)),
        'Pan up': ((PAN_ZOOM, .5, .5 + side), (PAN_ZOOM, .5, .5 - side)),
        'Pan down': ((PAN_ZOOM, .5, .5 - side), (PAN_ZOOM, .5, .5 + side)),
        CUSTOM: (None, (1.6, .5, .5)),
        FIXED: (None, (1.6, .5, .5)),
        ZOOM_OUT: (None, (.6, .5, .5)),
        HAND: (None, REST),
        HIDE: (None, REST),
    }.get(kind, (None, (1.6, .5, .5)))


def _ease(p):
    p = max(0., min(1., p))
    return p * p * (3 - 2 * p)


def mix(a, b, e):
    """Between two framings: zoom on a natural (logarithmic) scale."""
    (z0, x0, y0), (z1, x1, y1) = a, b
    z0, z1 = max(FAR, z0), max(FAR, z1)
    z = math.exp(math.log(z0) + (math.log(z1) - math.log(z0)) * e)
    return z, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e


def combine(base, clip):
    """A clip framing inside another framing (an element's own camera): one framing."""
    if clip is None:
        return base
    if base is None:
        return tuple(clip)
    z1, x1, y1 = base
    z2, x2, y2 = clip
    return z1 * z2, x1 + (x2 - .5) / z1, y1 + (y2 - .5) / z1


def set_kind(clip, kind):
    """A clip changed to another kind: a single move (fixed, zoom out) or go-stay-back; its
    times start again when it changes between the two."""
    single = (FIXED,)
    was = clip.get('kind') in single
    clip['kind'] = kind
    clip['from'], clip['to'] = presets(kind)
    if kind in single and not was:
        clip['duration'] = float(clip.get('in_s', IN_SECONDS)) if kind == FIXED else 2.
        clip['in_s'] = clip['duration']
    elif was and kind not in single:
        clip['in_s'], clip['out_s'] = IN_SECONDS, OUT_SECONDS
        clip['duration'] = IN_SECONDS + HOLD_SECONDS + OUT_SECONDS
    return fit(clip)


def free_lane(clips, start, end, skip=None):
    """exp.138: the lowest Moving camera row with nothing between start and end."""
    lane = 0
    while any(int(c.get('lane', 0) or 0) == lane and c is not skip and moving(c)
              and float(c['start']) < end - 1e-6 and until(c) > start + 1e-6 for c in clips):
        lane += 1
    return lane


def assign_lanes(clips):
    """Clips from before exp.138 (no row): each on the lowest row where it fits, as they
    were shown."""
    if all('lane' in c or not moving(c) for c in clips):
        return False
    placed = [c for c in clips if 'lane' in c]
    for c in sorted((c for c in clips if 'lane' not in c and moving(c)), key=lambda c: float(c['start'])):
        c['lane'] = free_lane(placed, float(c['start']), until(c))
        placed.append(c)
    return True


def moving(clip):
    """A clip on the Moving camera rows (not a fixed camera, not the hand's)."""
    return clip.get('kind') not in (FIXED, HAND, HIDE)


def hand_clips(clips, kinds=HAND_KINDS):
    return [c for c in clips or () if c.get('kind') in kinds]


def _ramp(c, t):
    """0..1 through a go / stay / back clip at `t` (0 outside it)."""
    start, total = float(c['start']), max(.2, float(c.get('duration', 4.4)))
    if not start <= t < start + total:
        return 0.
    a = max(.05, float(c.get('in_s', IN_SECONDS)))
    b = max(.05, float(c.get('out_s', OUT_SECONDS)))
    local = t - start
    return _ease(local / a) if local < a else (_ease((total - local) / b) if local > total - b else 1.)


def hidden_at(clips, seconds):
    """exp.148: how hidden the hand is at `seconds`: 0 shown .. 1 hidden."""
    return max([_ramp(c, float(seconds)) for c in hand_clips(clips, (HIDE,))] or [0.])


def away_at(clips, seconds):
    """exp.147: (how far out of the picture the waiting hand is: 0 in its corner .. 1 out,
    side) at `seconds` of the video."""
    t = float(seconds)
    best, side = 0., 'Right'
    for c in hand_clips(clips, (HAND,)):
        start, total = float(c['start']), max(.4, float(c.get('duration', 4.4)))
        if not start <= t < start + total:
            continue
        a = max(.05, float(c.get('in_s', IN_SECONDS)))
        b = max(.05, float(c.get('out_s', OUT_SECONDS)))
        local = t - start
        e = _ease(local / a) if local < a else (_ease((total - local) / b) if local > total - b else 1.)
        if e >= best:
            best, side = e, c.get('side') or 'Right'
    return best, side


def hand_signature(clips):
    """Plain data of the hand clips (for render options and fingerprints)."""
    return tuple((c.get('id'), round(float(c['start']), 4), round(float(c['duration']), 4),
                  round(float(c.get('in_s', IN_SECONDS)), 4), round(float(c.get('out_s', OUT_SECONDS)), 4),
                  c.get('side') or 'Right', c.get('kind', HAND)) for c in hand_clips(clips))


def from_hand_signature(sig):
    return [dict(id=r[0], start=r[1], duration=r[2], in_s=r[3], out_s=r[4], side=r[5],
                 kind=r[6] if len(r) > 6 else HAND) for r in sig or ()]


def fixed(clip):
    return clip.get('kind') == FIXED


def until(clip, moves=(), clips=()):
    """Where the clip's effect ends (seconds of the whole video). A moving camera: at the end
    of the clip, back at the normal frame (exp.124). A fixed camera (exp.128): it stays until
    the next fixed camera starts or until the end of the next move between pages (the move
    takes the camera to the next page, which starts at its normal frame)."""
    start = float(clip['start'])
    if not fixed(clip):
        return start + max(.4, float(clip.get('duration', 4.4)))
    ends = [FOREVER]
    ends += [float(c['start']) for c in clips or () if fixed(c) and c is not clip
             and (float(c['start']), c.get('id', '')) > (start, clip.get('id', ''))]
    ends += [float(b) for a, b in moves or () if float(a) >= start - 1e-6]
    return max(start + float(clip.get('duration', IN_SECONDS)), min(ends))


def _fixed_at(fixeds, t, moves):
    live = [c for c in fixeds if float(c['start']) <= t + 1e-9 and t < until(c, moves, fixeds)]
    if not live:
        return None
    clip = max(live, key=lambda c: (float(c['start']), c.get('id', '')))
    start = float(clip['start'])
    earlier = [c for c in fixeds if (float(c['start']), c.get('id', '')) < (start, clip.get('id', ''))]
    before = _fixed_at(earlier, start - 1e-6, moves) if earlier else None
    if clip.get('how') == 'Cut':                 # exp.129: straight there
        return tuple(clip.get('to') or REST)
    a = max(.05, float(clip.get('in_s', clip.get('duration', IN_SECONDS))))
    return mix(before or REST, tuple(clip.get('to') or REST), _ease((t - start) / a))


def framing_at(clips, seconds, moves=()):
    """The camera clips' framing at `seconds` of the whole video, or None (no effect).

    exp.124 (the user's rule): a moving camera goes in over in_s seconds, holds there, and
    comes back over out_s seconds at the end of the clip; when they overlap, the later one is
    shown. exp.128: a fixed camera moves there and stays (see until); the moving cameras go
    out from where the fixed camera has it and come back there."""
    t = float(seconds)
    clips = list(clips or ())
    fixeds = [c for c in clips if fixed(c)]
    base = _fixed_at(fixeds, t, moves) if fixeds else None
    live = [c for c in clips if moving(c) and float(c['start']) <= t + 1e-9 and t < until(c)]
    if not live:
        return base
    rest = base or REST
    # exp.138 (the user, like Filmora): the camera on the higher row wins; on the same row,
    # the later one.
    clip = max(live, key=lambda c: (int(c.get('lane', 0) or 0), float(c['start']), c.get('id', '')))
    start, total = float(clip['start']), max(.4, float(clip.get('duration', 4.4)))
    a = max(.05, float(clip.get('in_s', IN_SECONDS)))
    b = max(.05, float(clip.get('out_s', OUT_SECONDS)))
    local = t - start
    to = tuple(clip.get('to') or REST)
    there = tuple(clip['from']) if clip.get('from') else to      # where the hold begins
    if local < a:
        return mix(rest, there, _ease(local / a))
    if local > total - b:
        return mix(to, rest, _ease((local - (total - b)) / b))
    hold = max(1e-6, total - a - b)
    return mix(there, to, _ease((local - a) / hold)) if there != to else to


def signature(clips):
    """Plain data for fingerprints and option keys."""
    return tuple((c.get('id'), c.get('kind'), round(float(c['start']), 4), round(float(c['duration']), 4),
                  tuple(c['from']) if c.get('from') else None, tuple(c.get('to') or REST),
                  round(float(c.get('in_s', IN_SECONDS)), 4), round(float(c.get('out_s', OUT_SECONDS)), 4),
                  c.get('how'), int(c.get('lane', 0) or 0))
                 for c in clips or ())


class VideoCamera:
    """An element's camera in the whole video: its own camera (or none) with the camera
    clips on top. at(fraction) / at_seconds(s) in the element's own time; `start` is
    where the element starts in the whole video."""

    def __init__(self, base, start, clips, moves, total):
        self.base, self.start = base, float(start)
        self.clips, self.moves = list(clips or ()), list(moves or ())
        self.total = max(1e-6, float(total))

    def at_seconds(self, seconds):
        s = float(seconds)
        if self.base is None:
            own = None
        elif hasattr(self.base, 'at_seconds'):
            own = self.base.at_seconds(s)
        else:
            own = self.base.at(max(0., min(1., s / self.total)))
        framing = combine(own, framing_at(self.clips, self.start + s, self.moves))
        return framing if framing is not None else REST

    def at(self, fraction):
        return self.at_seconds(max(0., min(1., float(fraction))) * self.total)


def wrap(base, start, clips, moves, total):
    """The element's camera with the clips (unchanged when there are none)."""
    if not clips:
        return base
    return VideoCamera(base, start, clips, moves, total)


def from_options(base, options, total):
    """frame_render.camera_for: options['video_camera'] = (start, clips signature, moves)."""
    info = options.get('video_camera')
    if not info:
        return base
    start, sig, moves = info
    clips = []
    for i, k, s, d, f, t, *rest in sig:
        a, b = (rest + [IN_SECONDS, OUT_SECONDS])[:2] if len(rest) >= 2 else (IN_SECONDS, OUT_SECONDS)
        clips.append({'id': i, 'kind': k, 'start': s, 'duration': d, 'from': f, 'to': t, 'in_s': a, 'out_s': b,
                      'how': rest[2] if len(rest) >= 3 else None, 'lane': rest[3] if len(rest) >= 4 else 0})
    return wrap(base, start, clips, moves, total)
