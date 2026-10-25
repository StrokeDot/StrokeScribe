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

KINDS = ('Zoom in', 'Zoom out', 'Pan left', 'Pan right', 'Pan up', 'Pan down', 'Custom')
REST = (1., .5, .5)
PAN_ZOOM = 1.4


def new_clip(kind='Zoom in', start=0., duration=1.2):
    clip = dict(id=uuid.uuid4().hex[:10], kind=kind, start=round(float(start), 2),
                duration=round(max(.2, float(duration)), 2), to=None, **{'from': None})
    clip['from'], clip['to'] = presets(kind)
    return clip


def presets(kind):
    """(from, to) of a kind: from None = from wherever the camera is."""
    side = .5 - .5 / PAN_ZOOM                       # how far the view can go at PAN_ZOOM
    return {
        'Zoom in': (None, (1.6, .5, .5)),
        'Zoom out': (None, REST),
        'Pan left': ((PAN_ZOOM, .5 + side, .5), (PAN_ZOOM, .5 - side, .5)),
        'Pan right': ((PAN_ZOOM, .5 - side, .5), (PAN_ZOOM, .5 + side, .5)),
        'Pan up': ((PAN_ZOOM, .5, .5 + side), (PAN_ZOOM, .5, .5 - side)),
        'Pan down': ((PAN_ZOOM, .5, .5 - side), (PAN_ZOOM, .5, .5 + side)),
        'Custom': (None, (1.6, .5, .5)),
    }.get(kind, (None, (1.6, .5, .5)))


def _ease(p):
    p = max(0., min(1., p))
    return p * p * (3 - 2 * p)


def mix(a, b, e):
    """Between two framings: zoom on a natural (logarithmic) scale."""
    (z0, x0, y0), (z1, x1, y1) = a, b
    z = math.exp(math.log(max(1., z0)) + (math.log(max(1., z1)) - math.log(max(1., z0))) * e)
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


def until(clip, moves):
    """A clip's framing holds until the end of the next transition after it starts."""
    start = float(clip['start'])
    ends = [b for a, b in moves if b > start + 1e-6]
    return min(ends) if ends else math.inf


def framing_at(clips, seconds, moves=()):
    """The camera clips' framing at `seconds` of the whole video, or None (no effect)."""
    t = float(seconds)
    live = [c for c in clips or () if float(c['start']) <= t + 1e-9 and t < until(c, moves)]
    if not live:
        return None
    clip = max(live, key=lambda c: (float(c['start']), c.get('id', '')))
    start = float(clip['start'])
    begin = clip.get('from')
    if begin is None:
        earlier = [c for c in clips if c is not clip and float(c['start']) < start - 1e-9]
        begin = framing_at(earlier, start, moves) or REST
    p = (t - start) / max(.05, float(clip.get('duration', 1.2)))
    return mix(tuple(begin), tuple(clip.get('to') or REST), _ease(p))


def signature(clips):
    """Plain data for fingerprints and option keys."""
    return tuple((c.get('id'), c.get('kind'), round(float(c['start']), 4), round(float(c['duration']), 4),
                  tuple(c['from']) if c.get('from') else None, tuple(c.get('to') or REST))
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
    clips = [{'id': i, 'kind': k, 'start': s, 'duration': d, 'from': f, 'to': t} for i, k, s, d, f, t in sig]
    return wrap(base, start, clips, moves, total)
