"""When things happen in the whole video: elements on tracks, and the camera.

Until exp.104 the elements played strictly one after another, with a camera move
between two elements. Now each element can have its own start time and track
(like clips in Filmora), so two elements can be drawn at the same time.

    scene['start']  None (default): right after the element before it in the list
                    (and the camera move between them), as before. A number: seconds.
    scene['track']  0 (default) = Track 1, the lowest; higher tracks are drawn on top.

The camera: it shows the page of the element that started most recently; the move
to an element's page happens just before that element starts (the "Then" move of
the element before it, as before). After the last element, "Show everything" zooms
out to the whole board.

This module is plain Python (no Qt): times only. Drawing is in timeline_render.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    k: int                 # element number (its place in the elements list)
    start: float
    length: float
    track: int = 0

    @property
    def end(self):
        return self.start + self.length


@dataclass
class Move:
    k: int                 # the camera move after element k (to element k + 1; after the last: Show everything)
    start: float
    end: float

    @property
    def length(self):
        return self.end - self.start


@dataclass
class Layout:
    items: list
    moves: list
    total: float
    sequential: bool = True     # every element after the one before it, all on Track 1 (the classic video)
    boundaries: list = field(default_factory=list)


def layout(lengths, joins, starts=None, tracks=None):
    """lengths[k]: seconds of element k; joins[k]: seconds of the camera move after it
    (for the last element: the Show everything move, 0 if none); starts[k]: its own
    start (None: after the element before it); tracks[k]: its track (0: Track 1)."""
    n = len(lengths)
    starts = list(starts) if starts is not None else [None] * n
    tracks = [int(t or 0) for t in (tracks if tracks is not None else [0] * n)]
    items, moves = [], []
    end_before = 0.
    for k in range(n):
        if starts[k] is None:
            start = end_before + (float(joins[k - 1]) if k else 0.)
        else:
            start = max(0., float(starts[k]))
        items.append(Item(k, start, max(0., float(lengths[k])), max(0, tracks[k])))
        end_before = start + max(0., float(lengths[k]))
        if k and joins[k - 1] > 0:
            moves.append(Move(k - 1, max(0., start - float(joins[k - 1])), start))
    last_end = max((it.end for it in items), default=0.)
    if n and joins[-1] > 0:                          # Show everything, after everything
        moves.append(Move(n - 1, last_end, last_end + float(joins[-1])))
    total = max([last_end] + [m.end for m in moves])
    sequential = all(s is None for s in starts) and not any(tracks)
    points = {0., total}
    for it in items:
        points.update((it.start, it.end))
    for m in moves:
        points.update((m.start, m.end))
    bounds = sorted(p for p in points if 0. <= p <= total)
    return Layout(items, moves, total, sequential, bounds)


@dataclass
class State:
    """What is on screen at one moment."""
    kind: str                     # 'page' or 'move'
    current: int = 0              # page: the element whose page the camera shows
    active: list = field(default_factory=list)    # page: [(k, fraction of its own time)], bottom first
    finished: list = field(default_factory=list)  # elements already drawn (their finished pictures)
    move: int = -1                # move: the move after element `move`
    t: float = 0.                 # move: 0..1 through it
    top: int = -1                 # page: the active element whose hand is shown (the top one)
    seconds: float = None         # exp.170: the moment of the whole video (camera clips run on it)


def state_at(lay, seconds):
    """What the camera shows at `seconds` of the whole video."""
    s = max(0., min(lay.total, float(seconds)))
    active, finished = [], []
    for it in sorted(lay.items, key=lambda it: (it.track, it.start, it.k)):
        if it.start > s + 1e-9:
            continue
        if s < it.end - 1e-9:
            active.append((it.k, (s - it.start) / max(1e-9, it.length)))
        else:
            finished.append(it.k)
    if not active and not finished and lay.items:      # the very start: the first element, not begun
        first = min(lay.items, key=lambda it: (it.start, it.k))
        active = [(first.k, 0.)]
    top = active[-1][0] if active else -1
    last = len(lay.items) - 1
    for m in lay.moves:
        end_move = m.k == last
        if (m.start <= s < m.end) or (end_move and m.start <= s):
            return State('move', move=m.k, t=max(0., min(1., (s - m.start) / max(1e-9, m.length))),
                         active=active, finished=sorted(finished), top=top, seconds=s)
    started = [it for it in lay.items if it.start <= s + 1e-9] or \
        ([min(lay.items, key=lambda it: (it.start, it.k))] if lay.items else [])
    current = max(started, key=lambda it: (it.start, it.track, it.k)).k if started else 0
    return State('page', current=current, active=active, finished=sorted(finished), top=top, seconds=s)


def interval_at(lay, seconds):
    """(start, end) of the stretch of time around `seconds` in which nothing starts or ends
    (the unit the ready-frame cache keeps frames in)."""
    b = lay.boundaries or [0., lay.total]
    s = max(0., min(lay.total, float(seconds)))
    for a, c in zip(b, b[1:]):
        if a <= s < c:
            return a, c
    return (b[-2], b[-1]) if len(b) > 1 else (0., lay.total)


def describe(lay, state, a):
    """A short, stable description of a stretch of time starting at `a` (for fingerprints):
    who is active and since when, who is finished, where the camera is."""
    starts = {it.k: it.start for it in lay.items}
    active = tuple((k, round(a - starts[k], 4)) for k, _ in state.active)
    if state.kind == 'move':
        return ('move', state.move, active, tuple(state.finished), state.top)
    return ('page', state.current, active, tuple(state.finished), state.top)


def swapped_places(lay, k, j):
    """exp.126: elements k and j (next to each other in the list) change places in time too.

    Returns {element: (start, track)} for both, in their own (old) numbering. One after
    the other on the same track: the later one now starts where the earlier one started,
    the earlier one follows it with the same gap, so the pair ends where it ended and
    nothing after it moves (before, the ◀ ▶ buttons only changed the list order: elements
    with a start of their own stayed, the others moved, and they collided). Otherwise
    (side by side, on other tracks) they swap start and track."""
    a, b = sorted((k, j))
    first, second = lay.items[a], lay.items[b]
    if first.track == second.track and second.start >= first.end - 1e-6:
        gap = second.start - first.end
        return {b: (first.start, first.track), a: (first.start + second.length + gap, first.track)}
    return {b: (first.start, first.track), a: (second.start, second.track)}
