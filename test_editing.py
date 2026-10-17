"""Undo for every setting, line selection on the preview, line edits and timing control."""
import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'

import stroke_timing
from history import History


class _Stroke:
    def __init__(self, points, pace=1., pause=0.):
        self.name = 'line'
        self.points = points
        self.length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        self.pace, self.pause = pace, pause


class _Drawing:
    def __init__(self, strokes, **attrs):
        self.strokes = strokes
        self.__dict__.update(attrs)


def lines(*paces):
    return [_Stroke([(0, i * 10), (100, i * 10)], pace) for i, pace in enumerate(paces)]


class TimingTests(unittest.TestCase):
    def test_plain_drawings_are_unchanged(self):
        d = _Drawing(lines(1, 1, 1))
        for t in (0, .1, .33, .5, .9, 1):
            self.assertEqual(stroke_timing.ink_progress(d, t), t)

    def test_slow_line_takes_longer(self):
        d = _Drawing(lines(3, 1))             # first line three times slower
        self.assertAlmostEqual(stroke_timing.ink_progress(d, .75), .5, places=6)
        self.assertLess(stroke_timing.ink_progress(d, .5), .5)
        self.assertEqual(stroke_timing.pace_name(3), 'Very slow')
        self.assertEqual(stroke_timing.pace_name(1.6), 'Slow')

    def test_pause_holds_the_ink(self):
        strokes = lines(1, 1)
        strokes[0].pause = 1.
        d = _Drawing(strokes, draw_seconds=4.)
        # 1 s pause of 4 s: line 1 in 0..1.5 s, pause 1.5..2.5 s, line 2 in 2.5..4 s.
        self.assertAlmostEqual(stroke_timing.ink_progress(d, 1.5 / 4), .5, places=6)
        self.assertAlmostEqual(stroke_timing.ink_progress(d, 2. / 4), .5, places=6)
        self.assertAlmostEqual(stroke_timing.ink_progress(d, 2.49 / 4), .5, places=6)
        self.assertGreater(stroke_timing.ink_progress(d, 3. / 4), .5)
        # Pauses are capped at 60 % of the drawing time.
        strokes[0].pause = 100.
        d = _Drawing(strokes, draw_seconds=4.)
        self.assertAlmostEqual(sum(stroke_timing.pauses(d)), .6)

    def test_natural_pen_eases_each_line(self):
        d = _Drawing(lines(1, 1), pen_ease='natural')
        self.assertLess(stroke_timing.ink_progress(d, .05), .05)          # gentle start
        self.assertAlmostEqual(stroke_timing.ink_progress(d, .25), .25, places=6)
        self.assertAlmostEqual(stroke_timing.ink_progress(d, .5), .5, places=6)
        self.assertGreater(stroke_timing.ink_progress(d, .45), .45)       # gentle end

    def test_natural_is_clearly_different(self):
        strokes = [_Stroke([(0, i * 10), (100 if i % 2 else 20, i * 10)]) for i in range(6)]
        plain = _Drawing(strokes, draw_seconds=4.)
        natural = _Drawing(strokes, draw_seconds=4., pen_ease='natural')
        diff = max(abs(stroke_timing.ink_progress(plain, k / 50) - stroke_timing.ink_progress(natural, k / 50))
                   for k in range(51))
        self.assertGreater(diff, .04)                       # visible, not a tiny change
        # The pen lifts between lines: the ink stands still for a moment.
        ink = [stroke_timing.ink_progress(natural, k / 400) for k in range(401)]
        self.assertTrue(any(ink[k + 1] == ink[k] and 0 < ink[k] < 1 for k in range(400)))

    def test_image_drawing_pause(self):
        from image_drawing import drawing_state
        strokes = lines(1, 1)
        strokes[0].pause = 2.
        d = _Drawing(strokes, draw_seconds=4.)
        resting = drawing_state(d, .5)
        self.assertFalse(resting.painting)
        self.assertEqual(resting.lift_point, (100, 0))
        self.assertAlmostEqual(resting.stroke_progress, .5, places=3)
        self.assertTrue(drawing_state(d, .1).painting)


class HistoryTests(unittest.TestCase):
    def test_undo_redo(self):
        a, b = object(), object()
        h = History(limit=3)
        h.reset({'settings': {'x': 1}, 'strokes': (a, b)})
        self.assertFalse(h.record({'settings': {'x': 1}, 'strokes': (a, b)}))   # same: no step
        self.assertTrue(h.record({'settings': {'x': 2}, 'strokes': (a, b)}))
        self.assertTrue(h.record({'settings': {'x': 2}, 'strokes': (b, a)}))
        self.assertEqual(h.undo()['strokes'], (a, b))
        self.assertEqual(h.undo()['settings'], {'x': 1})
        self.assertIsNone(h.undo())
        self.assertEqual(h.redo()['settings'], {'x': 2})
        h.record({'settings': {'x': 9}, 'strokes': (a,)})
        self.assertFalse(h.can_redo())
        for x in range(10):
            h.record({'settings': {'x': 100 + x}, 'strokes': ()})
        self.assertEqual(len(h.undo_stack), 3)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        self.assertFalse(w.undo_button.isEnabled())
        return w

    def test_every_setting_can_be_undone(self):
        w = self.window()
        w.thickness.setValue(3.)
        w.commit_history()
        w.reveal_mode.setCurrentIndex(2)
        w.camera.setCurrentIndex(1)                 # quick edits before the pause: one step
        w.undo()
        self.assertEqual((w.thickness.value(), w.reveal_mode.currentIndex(), w.camera.currentIndex()), (3., 1, 0))
        w.undo()
        self.assertEqual(w.thickness.value(), 1.)
        self.assertFalse(w.undo_button.isEnabled())
        w.redo(); w.redo()
        self.assertEqual((w.thickness.value(), w.reveal_mode.currentIndex(), w.camera.currentIndex()), (3., 2, 1))

    def test_click_a_line_on_the_preview(self):
        w = self.window()
        lines = w.preview_lines()
        self.assertEqual(len(lines), len(w.drawing.strokes))
        k = len(lines) // 2
        x, y = lines[k][len(lines[k]) // 2]
        w.click_preview(x, y)
        rows = w.selected_rows()
        self.assertEqual(len(rows), 1)
        chosen = lines[rows[0]]
        self.assertLess(min(math.dist((x, y), p) for p in chosen), 3.)
        self.assertEqual(len(w.canvas.highlight), 1)
        self.assertTrue(w.delete_button.isEnabled())
        # Ctrl+click adds another line; clicking empty space clears.
        other = next(i for i in range(len(lines)) if w.line_at(*lines[i][0]) not in (None, rows[0]))
        w.click_preview(*lines[other][0], add=True)
        self.assertEqual(len(w.selected_rows()), 2)
        w.click_preview(-500, -500)
        self.assertEqual(w.selected_rows(), [])
        self.assertEqual(w.canvas.highlight, [])

    def test_delete_reverse_and_drag(self):
        w = self.window()
        strokes = list(w.drawing.strokes)
        w.order.item(1).setSelected(True)
        w.delete_lines()
        self.assertEqual(len(w.drawing.strokes), len(strokes) - 1)
        self.assertNotIn(strokes[1], w.drawing.strokes)
        w.undo()
        self.assertEqual(w.drawing.strokes, strokes)
        self.assertTrue(all(a is b for a, b in zip(w.drawing.strokes, strokes)))
        # Reverse: same line, drawn from the other end; the original is untouched.
        w.order.clearSelection(); w.order.item(0).setSelected(True)
        w.reverse_lines()
        self.assertEqual(w.drawing.strokes[0].points, strokes[0].points[::-1])
        self.assertIn('reversed', w.order.item(0).text())
        self.assertEqual(strokes[0].points[0], w.drawing.strokes[0].points[-1])
        self.assertAlmostEqual(w.drawing.strokes[0].length, strokes[0].length, places=6)
        w.undo()
        self.assertIs(w.drawing.strokes[0], strokes[0])
        # Drag in the list (simulated drop): first line moved to the end.
        item = w.order.takeItem(0)
        w.order.addItem(item)
        w.order_dragged()
        self.assertIs(w.drawing.strokes[-1], strokes[0])
        self.assertTrue(w.undo_button.isEnabled())
        w.undo()
        self.assertIs(w.drawing.strokes[0], strokes[0])

    def test_pace_pause_and_pen_ease(self):
        import motion
        from projects import drawing_from_dict, drawing_to_dict
        w = self.window()
        w.order.item(0).setSelected(True)
        w.line_pace.setCurrentText('Very slow'); w.set_line_pace()
        self.assertEqual(w.drawing.strokes[0].pace, 3.)
        self.assertIn('very slow', w.order.item(0).text())
        w.line_pause.setValue(1.5)
        w.commit_history()
        self.assertEqual(w.drawing.strokes[0].pause, 1.5)
        o = w.options()
        self.assertEqual(w.drawing.draw_seconds, o['duration'])
        # During the pause the pen rests (no drawing, so no pencil sound).
        start, end = __import__('stroke_timing').stroke_times(w.drawing)[0]
        resting = (end + .02) * o['duration'] / w.timeline_length()
        sample = motion.pen_at(w.drawing, resting, **{k: v for k, v in o.items() if k not in ('fps',)})
        self.assertEqual(sample.kind, motion.LIFT)
        # Saved in projects.
        again = drawing_from_dict(drawing_to_dict(w.drawing))
        self.assertEqual((again.strokes[0].pace, again.strokes[0].pause), (3., 1.5))
        w.pen_ease.setCurrentIndex(1)
        w.options()
        self.assertEqual(w.drawing.pen_ease, 'natural')
        self.assertIn('pen_ease', w.settings_state())
        w.undo(); w.undo(); w.undo()          # pen movement, pause, pace
        self.assertEqual(w.drawing.strokes[0].pace, 1.)
        self.assertEqual(w.pen_ease.currentIndex(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
