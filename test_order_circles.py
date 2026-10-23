"""exp.99: Line order — Circle groups (painting: a loop cuts its own part), Ctrl+click to
take something out of a trace, and saved orders."""
import os
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


class CircleCutTests(unittest.TestCase):
    def test_a_circle_cuts_its_own_part_out_of_what_it_covers(self):
        from painter_paint import apply_circles
        labels = np.zeros((40, 60), np.int32)
        labels[:, :30] = 1                        # "the wall"
        labels[:, 30:] = 2                        # "the man", touching the wall
        circle = [(.4, .2), (.6, .2), (.6, .8), (.4, .8)]   # around the place where they meet
        out, ids = apply_circles(labels, [circle])
        self.assertEqual(len(ids), 1)
        inside = out == ids[0]
        self.assertTrue(inside[20, 25] and inside[20, 34])  # both sides of the edge: one part now
        self.assertEqual(out[20, 5], 1); self.assertEqual(out[20, 55], 2)   # the rest stays

    def test_overlapping_circles_first_one_wins_and_order_kept(self):
        from painter_paint import apply_circles
        labels = np.ones((20, 20), np.int32)
        a = [(0, 0), (.6, 0), (.6, 1), (0, 1)]
        b = [(.4, 0), (1, 0), (1, 1), (.4, 1)]
        out, ids = apply_circles(labels, [a, b])
        self.assertEqual(ids, [2, 3])
        self.assertEqual(out[10, 10], 2)          # inside both: the first circle
        self.assertEqual(out[10, 18], 3)

    def test_no_circles_no_change(self):
        from painter_paint import apply_circles
        labels = np.arange(12).reshape(3, 4)
        out, ids = apply_circles(labels, None)
        self.assertIs(out, labels); self.assertEqual(ids, [])


@unittest.skipIf(SKIP, 'needs Qt')
class OrderWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        from engine import Drawing, Stroke
        self.w = Window()
        self.w.show()
        lines = [Stroke(f'line {i + 1}', [(10 + 20 * i, 10), (15 + 20 * i, 40)], width=2) for i in range(6)]
        self.w.set_drawing(Drawing(lines, (0, 0, 130, 50), []))
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.app.processEvents()

    def test_circle_groups_the_lines_inside(self):
        w = self.w
        d = w.open_line_order()
        d.circle_button.setChecked(True)
        d.circle_done([(65, 0), (130, 0), (130, 50), (65, 0 + 50)])      # around lines 4, 5, 6
        self.assertEqual([s.name for s in d.strokes][:3], ['line 4', 'line 5', 'line 6'])
        d.circle_done([(0, 0), (30, 0), (30, 50), (0, 50)])              # then line 1 (and 2 partly)
        self.assertEqual(d.strokes[3].name, 'line 1')
        d.circle_remove_at(100, 25)                                      # Ctrl+click in the first loop
        self.assertEqual(d.strokes[0].name, 'line 1')
        d.accept(); self.app.processEvents()
        self.assertEqual(w.drawing.strokes[0].name, 'line 1')

    def test_trace_and_take_one_out(self):
        w = self.w
        d = w.open_line_order()
        d.trace_button.setChecked(True)
        at = lambda name: [s.name for s in d.strokes].index(name)        # its place right now
        d.trace_add(at('line 5')); d.trace_add(at('line 3')); d.trace_add(at('line 1'))
        self.assertEqual([s.name for s in d.strokes][:3], ['line 5', 'line 3', 'line 1'])
        d.trace_remove(at('line 3'))                                     # take "line 3" out again
        names = [s.name for s in d.strokes]
        self.assertEqual(names[:2], ['line 5', 'line 1'])
        self.assertEqual(d.selected, {0, 1})                             # only the traced ones numbered
        self.assertEqual(names[2:], ['line 2', 'line 3', 'line 4', 'line 6'])
        d.reject()

    def test_save_and_come_back_to_an_order(self):
        w = self.w
        d = w.open_line_order()
        d.auto.setCurrentText('Left to right'); d.apply_auto()
        d.selected = {5}; d.move('start')                                # line 6 first
        d.save_order()
        self.assertEqual(d.saved.itemText(1), 'Order 1')
        d.use_saved(0)                                                   # Default
        self.assertEqual(d.strokes[0].name, 'line 1')
        d.use_saved(1)                                                   # back to Order 1
        self.assertEqual(d.strokes[0].name, 'line 6')
        d.reject(); self.app.processEvents()
        self.assertEqual(len(w.drawing.saved_orders), 1)                 # kept even after Cancel
        from projects import drawing_from_dict, drawing_to_dict
        back = drawing_from_dict(drawing_to_dict(w.drawing))
        self.assertEqual(back.saved_orders[0]['name'], 'Order 1')        # and saved with the project


if __name__ == '__main__':
    unittest.main()
