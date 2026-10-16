"""Timing control for the drawing stage: per-line pace, pauses and pen ease.

Each line (Stroke) can have
  pace   >1 draws it more slowly (careful detail), <1 faster (quick lines);
  pause  seconds the pen rests at the end of the line before going on.
The drawing can also have pen_ease = 'natural': every line starts and ends a
little slower, like a real hand, instead of at constant speed.

`ink_progress(drawing, t)` turns the time fraction of the drawing stage (0..1)
into the fraction of ink drawn, which is what the renderers use. Without any
custom timing it returns t unchanged, so old projects and tests look the same.
Pauses are in seconds, so they need the drawing time: options_from_settings
stores it on the drawing as `draw_seconds`.
"""
from __future__ import annotations

import math

PACES = (('Very slow', 3.), ('Slow', 1.8), ('Normal', 1.), ('Fast', .6), ('Very fast', .35))
MAX_PAUSE_SHARE = .6        # pauses never take more than 60 % of the drawing time


def pace_name(pace):
    pace = float(pace or 1.)
    return min(PACES, key=lambda p: abs(math.log(p[1]) - math.log(max(.01, pace))))[0]


def pace_value(name):
    return dict(PACES)[name]


def ease(f):
    """Gentle start and end of a line (60 % smoothstep, 40 % constant speed)."""
    f = max(0., min(1., f))
    return .4 * f + .6 * f * f * (3 - 2 * f)


def custom(drawing):
    if getattr(drawing, 'pen_ease', 'off') == 'natural':
        return True
    return any(abs(float(getattr(s, 'pace', 1.) or 1.) - 1.) > 1e-9 or float(getattr(s, 'pause', 0.) or 0.) > 0
               for s in drawing.strokes)


def pauses(drawing):
    """Pause of each stroke as a share of the drawing time (after capping)."""
    seconds = max(.001, float(getattr(drawing, 'draw_seconds', 0.) or 0.))
    raw = [max(0., float(getattr(s, 'pause', 0.) or 0.)) for s in drawing.strokes]
    if not getattr(drawing, 'draw_seconds', None):
        return [0.] * len(raw)
    total = sum(raw)
    limit = MAX_PAUSE_SHARE * seconds
    scale = limit / total if total > limit else 1.
    return [p * scale / seconds for p in raw]


def _schedule(drawing):
    """[(stroke start time share, moving share, pause share, ink before, length)]."""
    key = (tuple(id(s) for s in drawing.strokes), getattr(drawing, 'draw_seconds', None),
           tuple((getattr(s, 'pace', 1.), getattr(s, 'pause', 0.)) for s in drawing.strokes))
    cached = getattr(drawing, '_timing_cache', None)
    if cached and cached[0] == key:
        return cached[1]
    rests = pauses(drawing)
    moving = 1. - sum(rests)
    weights = [s.length * max(.05, float(getattr(s, 'pace', 1.) or 1.)) for s in drawing.strokes]
    total_weight = sum(weights) or 1.
    out = []
    t = ink = 0.
    for stroke, weight, rest in zip(drawing.strokes, weights, rests):
        share = moving * weight / total_weight
        out.append((t, share, rest, ink, stroke.length))
        t += share + rest
        ink += stroke.length
    try:
        drawing._timing_cache = (key, out)
    except AttributeError:
        pass
    return out


def ink_progress(drawing, t):
    """Fraction of ink drawn at time fraction t of the drawing stage."""
    t = max(0., min(1., float(t)))
    if t <= 0 or t >= 1 or not drawing.strokes or not custom(drawing):
        return t
    ink_total = sum(s.length for s in drawing.strokes)
    if ink_total <= 0:
        return t
    natural = getattr(drawing, 'pen_ease', 'off') == 'natural'
    for start, share, rest, before, length in _schedule(drawing):
        if t < start + share:
            f = (t - start) / share if share > 0 else 1.
            return (before + length * (ease(f) if natural else f)) / ink_total
        if t < start + share + rest:
            return (before + length) / ink_total
    return 1.


def stroke_times(drawing):
    """(start, end) time share of each stroke's own drawing (pauses excluded)."""
    if not custom(drawing):
        ink_total = sum(s.length for s in drawing.strokes) or 1.
        out, ink = [], 0.
        for s in drawing.strokes:
            out.append((ink / ink_total, (ink + s.length) / ink_total)); ink += s.length
        return out
    return [(start, start + share) for start, share, _, _, _ in _schedule(drawing)]
