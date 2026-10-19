"""Undo / redo for every setting and every line edit.

A snapshot is the settings dict (Window.settings_state) plus the tuple of
stroke objects. Line edits never change a Stroke in place; they make edited
copies (see edited_stroke), so keeping the old tuple is enough to restore it.
"""
from __future__ import annotations

import copy


class History:
    def __init__(self, limit=100):
        self.limit = limit
        self.undo_stack, self.redo_stack = [], []
        self.current = None

    @staticmethod
    def same(a, b):
        if a is None or b is None:
            return a is b
        return (a['settings'] == b['settings'] and len(a['strokes']) == len(b['strokes'])
                and all(x is y for x, y in zip(a['strokes'], b['strokes']))
                and a.get('overlays') == b.get('overlays')
                and a.get('source') is b.get('source'))

    def reset(self, snapshot):
        self.undo_stack.clear(); self.redo_stack.clear()
        self.current = snapshot

    def record(self, snapshot):
        """Remember a new state; returns True if anything changed."""
        if self.current is None:
            self.current = snapshot
            return False
        if self.same(snapshot, self.current):
            return False
        self.undo_stack.append(self.current)
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()
        self.current = snapshot
        return True

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if not self.undo_stack:
            return None
        self.redo_stack.append(self.current)
        self.current = self.undo_stack.pop()
        return self.current

    def redo(self):
        if not self.redo_stack:
            return None
        self.undo_stack.append(self.current)
        self.current = self.redo_stack.pop()
        return self.current


def edited_stroke(stroke, reverse=False, pace=None, pause=None):
    """A copy of the stroke with the change (the original is left untouched)."""
    new = copy.copy(stroke)
    if reverse:
        new.points = list(reversed(stroke.points))
        new.__post_init__()                     # distances and length
        new.reversed = not getattr(stroke, 'reversed', False)
    if pace is not None:
        new.pace = float(pace)
    if pause is not None:
        new.pause = max(0., float(pause))
    return new


def describe(stroke):
    """List label: name plus any timing/direction changes."""
    from stroke_timing import pace_name
    parts = [stroke.name]
    pace = float(getattr(stroke, 'pace', 1.) or 1.)
    if abs(pace - 1.) > 1e-9:
        parts.append(pace_name(pace).lower())
    pause = float(getattr(stroke, 'pause', 0.) or 0.)
    if pause > 0:
        parts.append(f'pause {pause:g} s')
    if getattr(stroke, 'reversed', False):
        parts.append('reversed')
    return '  •  '.join(parts)
