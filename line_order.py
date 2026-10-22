"""Drawing order of the lines: moving several lines at once, and automatic orders.

Every function takes the list of strokes and returns a new list (the strokes
themselves are never changed, except when a line is turned around by "Nearest
next", which makes a reversed copy as the Reverse button does).
"""
from __future__ import annotations

import math

AUTO = (
    ('Top to bottom', 'Lines higher in the picture first, like writing a page.'),
    ('Left to right', 'Lines further left first.'),
    ('Outlines first, details last', 'The longest lines (outlines, big shapes) first, then shorter lines and small details.'),
    ('Nearest next (pen travels least)', 'Each line starts where the pen is closest, turning lines around when that is shorter. '
                                         'Smooth and natural, like a person not lifting the pen far.'),
    ('Big shapes first, inside out', 'The lines that enclose the biggest area first, then the lines inside them.'),
)


def move_block(strokes, rows, position):
    """Move the lines at `rows` together (keeping their order) so the first one ends up
    at `position` (0-based, counted in the finished list). Returns (new list, new rows)."""
    rows = sorted(set(r for r in rows if 0 <= r < len(strokes)))
    if not rows:
        return list(strokes), []
    block = [strokes[r] for r in rows]
    rest = [s for i, s in enumerate(strokes) if i not in set(rows)]
    position = max(0, min(len(rest), int(position)))
    out = rest[:position] + block + rest[position:]
    return out, list(range(position, position + len(block)))


def _box(stroke):
    xs = [p[0] for p in stroke.points] or [0.]
    ys = [p[1] for p in stroke.points] or [0.]
    return min(xs), min(ys), max(xs), max(ys)


def _length(stroke):
    pts = stroke.points
    return sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def _reversed(stroke):
    from history import edited_stroke
    return edited_stroke(stroke, reverse=True)


def _start(stroke):
    return stroke.points[0] if stroke.points else (0., 0.)


def _end(stroke):
    return stroke.points[-1] if stroke.points else (0., 0.)


def nearest_next(strokes):
    if not strokes:
        return []
    left = list(strokes)
    first = min(left, key=lambda s: (_box(s)[1], _box(s)[0]))       # start at the top left
    left.remove(first)
    out = [first]
    while left:
        here = _end(out[-1])
        best, flip, best_d = None, False, float('inf')
        for s in left:
            d0, d1 = math.dist(here, _start(s)), math.dist(here, _end(s))
            if d0 < best_d:
                best, flip, best_d = s, False, d0
            if d1 < best_d:
                best, flip, best_d = s, True, d1
        left.remove(best)
        out.append(_reversed(best) if flip else best)
    return out


def ordered(strokes, kind):
    """`strokes` in the automatic order `kind` (a name from AUTO)."""
    strokes = list(strokes)
    if kind == 'Top to bottom':
        return sorted(strokes, key=lambda s: (round(_box(s)[1], 1), _box(s)[0]))
    if kind == 'Left to right':
        return sorted(strokes, key=lambda s: (round(_box(s)[0], 1), _box(s)[1]))
    if kind == 'Outlines first, details last':
        return sorted(strokes, key=lambda s: -_length(s))
    if kind == 'Nearest next (pen travels least)':
        return nearest_next(strokes)
    if kind == 'Big shapes first, inside out':
        def area(s):
            x0, y0, x1, y1 = _box(s)
            return (x1 - x0) * (y1 - y0)
        return sorted(strokes, key=lambda s: -area(s))
    raise ValueError(f'Unknown order: {kind}')


def apply_order(strokes, kind, rows=None):
    """The automatic order for all lines, or only for the lines at `rows` (they keep their
    places in the list; only their order among themselves changes). Returns (list, rows)."""
    strokes = list(strokes)
    if not rows:
        return ordered(strokes, kind), []
    rows = sorted(set(rows))
    new = ordered([strokes[r] for r in rows], kind)
    for r, s in zip(rows, new):
        strokes[r] = s
    return strokes, rows
