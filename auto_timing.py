"""Auto timing: pick draw / paint / hold / erase times, or fit them to a length.

`suggest` looks at how much there is to draw (total line length relative to
the picture size, number of lines) and paint, and returns times that feel
natural: busy pictures draw longer, simple ones stay short. `fit` stretches or
shrinks a set of times so they add up to a target length (for example the
voiceover), keeping their proportions and each control's limits.
"""
from __future__ import annotations

import math

PARTS = ('draw', 'paint', 'hold', 'erase')
LIMITS = {'draw': (.2, 120.), 'paint': (.2, 120.), 'hold': (0., 30.), 'erase': (.5, 30.)}


def amount(drawing):
    """(line length in picture diagonals, number of lines)."""
    strokes = [s for s in getattr(drawing, 'strokes', []) if len(s.points) > 1]
    if not strokes:
        return 0., 0
    xs = [p[0] for s in strokes for p in s.points]
    ys = [p[1] for s in strokes for p in s.points]
    diagonal = max(1e-6, math.hypot(max(xs) - min(xs), max(ys) - min(ys)))
    return sum(s.length for s in strokes) / diagonal, len(strokes)


def _half(x):
    return round(x * 2) / 2


def suggest(drawing, paint=True, erase=False, image=False, paint_only=False):
    """Suggested {'draw','paint','hold','erase'} seconds (0 for stages that are off)."""
    length, count = amount(drawing)
    draw = 1.5 + .32 * length + .04 * count
    draw = min(20., max(2., draw))
    times = dict(draw=0. if paint_only else _half(draw), paint=0., hold=0., erase=0.)
    if paint:
        times['paint'] = _half(min(20., max(3., draw * 1.3))) if image else _half(min(8., max(1., draw * .45)))
        times['hold'] = 1.
    if erase:
        times['erase'] = _half(min(6., max(1.5, draw * .4)))
    return times


def fit(times, target):
    """Scale the non-zero parts of `times` so they add up to `target` seconds.

    Returns (new_times, reached): reached is False when the control limits
    made the exact length impossible.
    """
    active = [k for k in PARTS if times.get(k, 0) > 0]
    out = {k: float(times.get(k, 0.)) for k in PARTS}
    if not active or target <= 0:
        return out, False
    free = list(active)
    for _ in range(8):                       # clamp and redistribute
        fixed = sum(out[k] for k in active if k not in free)
        base = sum(times[k] for k in free)
        if not free or base <= 0:
            break
        scale = (target - fixed) / base
        clamped = []
        for k in free:
            lo, hi = LIMITS[k]
            out[k] = times[k] * scale
            if out[k] < lo or out[k] > hi:
                out[k] = min(hi, max(lo, out[k])); clamped.append(k)
        if not clamped:
            break
        free = [k for k in free if k not in clamped]
    out = {k: round(v, 2) for k, v in out.items()}
    return out, abs(sum(out.values()) - target) < .05
