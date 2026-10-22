"""exp.90: the Line order window — move several lines together, automatic orders."""
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


class FakeStroke:
    def __init__(self, name, points):
        self.name, self.points = name, list(points)

    def __post_init__(self):
        pass


def lines(*specs):
    return [FakeStroke(n, pts) for n, pts in specs]


class MoveTests(unittest.TestCase):
    def test_move_several_lines_together(self):
        from line_order import move_block
        s = lines(*[(c, [(0, 0), (1, 1)]) for c in 'ABCDEF'])
        out, rows = move_block(s, [1, 3, 4], 0)                       # B, D, E to the start
        self.assertEqual([x.name for x in out], list('BDEACF'))
        self.assertEqual(rows, [0, 1, 2])
        out, rows = move_block(s, [0, 2], 4)                          # A, C to the end
        self.assertEqual([x.name for x in out], list('BDEFAC'))
        self.assertEqual(rows, [4, 5])
        out, rows = move_block(s, [5], 1)
        self.assertEqual([x.name for x in out], list('AFBCDE'))

    def test_automatic_orders(self):
        from line_order import apply_order, ordered
        s = lines(('low', [(0, 50), (10, 50)]), ('high', [(5, 0), (6, 0)]), ('left', [(-20, 20), (-20, 30)]),
                  ('long', [(0, 10), (100, 10)]))
        self.assertEqual([x.name for x in ordered(s, 'Top to bottom')], ['high', 'long', 'left', 'low'])
        self.assertEqual([x.name for x in ordered(s, 'Left to right')][0], 'left')
        self.assertEqual([x.name for x in ordered(s, 'Outlines first, details last')][0], 'long')
        # Only the selected lines are ordered; the others keep their places.
        out, rows = apply_order(s, 'Top to bottom', [0, 1])
        self.assertEqual([x.name for x in out], ['high', 'low', 'left', 'long'])
        self.assertEqual(rows, [0, 1])

    def test_nearest_next_turns_lines_around(self):
        from line_order import ordered
        s = lines(('a', [(0, 0), (10, 0)]), ('b', [(30, 0), (11, 0)]), ('c', [(31, 1), (50, 1)]))
        out = ordered(s, 'Nearest next (pen travels least)')
        self.assertEqual([x.name for x in out], ['a', 'b', 'c'])
        self.assertEqual(out[1].points[0], (11, 0))                    # b drawn from the near end
        self.assertTrue(out[1].reversed)
        self.assertEqual(s[1].points[0], (30, 0))                      # the original is untouched


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        from engine import import_svg
        self.w = Window()
        self.w.show()
        self.w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.app.processEvents()

    def test_pick_move_and_use_the_order(self):
        w = self.w
        names = [s.name for s in w.drawing.strokes]
        self.assertGreaterEqual(len(names), 4)
        self.assertTrue(w.line_order_button.isEnabled())
        dialog = w.open_line_order()
        self.app.processEvents()
        dialog.picture_clicked(1); dialog.picture_clicked(3); dialog.picture_clicked(2)
        dialog.picture_clicked(2)                                      # clicked again: unselected
        self.assertEqual(dialog.selected, {1, 3})
        self.assertIn('2 lines selected', dialog.count.text())
        dialog.move('end')
        self.assertEqual([s.name for s in dialog.strokes][-2:], [names[1], names[3]])
        self.assertEqual(dialog.selected, {len(names) - 2, len(names) - 1})   # still selected after moving
        self.assertEqual(names, [s.name for s in w.drawing.strokes])          # nothing changed yet
        dialog.accept(); self.app.processEvents()
        self.assertEqual([s.name for s in w.drawing.strokes][-2:], [names[1], names[3]])
        w.undo()
        self.assertEqual(names, [s.name for s in w.drawing.strokes])          # one undo step

    def test_cancel_and_automatic(self):
        w = self.w
        names = [s.name for s in w.drawing.strokes]
        dialog = w.open_line_order()
        dialog.auto.setCurrentText('Outlines first, details last')
        dialog.apply_auto()
        dialog.toggle_play()
        for _ in range(len(names) + 2):
            dialog.play_step()
        dialog.reject(); self.app.processEvents()
        self.assertEqual(names, [s.name for s in w.drawing.strokes])          # Cancel keeps the order

    def test_names_default_and_place(self):
        w = self.w
        names = [s.name for s in w.drawing.strokes]
        dialog = w.open_line_order()
        self.assertEqual(dialog.list.item(0).text(), 'Line 1')            # simple names
        dialog.picture_clicked(2)
        self.assertEqual(dialog.position.value(), 3)                       # Move to place starts where it is
        dialog.move('at')
        self.assertEqual([s.name for s in dialog.strokes], names)          # so Move keeps it there
        dialog.move('start')
        dialog.default()                                                   # back to the order it came in
        self.assertEqual([s.name for s in dialog.strokes], names)
        dialog.picture_clicked(0)
        dialog.edit(reverse=True)
        self.assertTrue(dialog.strokes[0].reversed)
        dialog.reject()

    def test_painting_tab_orders_the_painter_parts(self):
        from PySide6.QtGui import QColor, QImage, QPainter
        w = self.w
        colours = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
        colours.fill(QColor(0, 0, 0, 0))
        p = QPainter(colours)
        p.fillRect(20, 20, 160, 260, QColor(200, 40, 40)); p.fillRect(220, 20, 160, 260, QColor(40, 60, 200))
        p.fillRect(240, 200, 30, 30, QColor(240, 220, 30)); p.end()
        w.final_image = colours
        w.use_color.setEnabled(True); w.use_color.setChecked(True)
        dialog = w.open_line_order()
        dialog.set_mode('paint')
        self.assertEqual(dialog.mode, 'draw')                              # not Painter: explained, stays on Drawing
        self.assertIn('Painter', dialog.hint.text())
        dialog.reject(); self.app.processEvents()
        w.reveal_mode.setCurrentText(w.PAINTER_TEXT)
        dialog = w.open_line_order()
        dialog.set_mode('paint')
        self.assertEqual(dialog.mode, 'paint')
        self.assertGreaterEqual(len(dialog.parts), 2)
        self.assertEqual(dialog.list.item(0).text(), 'Part 1')
        last = len(dialog.parts) - 1
        dialog.picture_clicked(last)
        dialog.move('start')
        chosen = list(dialog.parts)
        dialog.accept(); self.app.processEvents()
        self.assertEqual(w.drawing.paint_part_order, chosen)
        from adaptive_hand import plan_for
        from painter_paint import part_order
        self.assertEqual(part_order(dialog.grid, (0, 0), w.drawing.paint_part_order)[0], chosen[0])
        self.assertIsNotNone(plan_for)

    def test_trace_the_order_with_the_mouse(self):
        w = self.w
        names = [s.name for s in w.drawing.strokes]
        dialog = w.open_line_order()
        self.app.processEvents()
        dialog.trace_button.setChecked(True)
        self.assertTrue(dialog.tracing)
        dialog.trace_size.setValue(3)
        lines = dialog.picture.polylines()
        def middle(i):
            line = lines[i]
            return line[len(line) // 2]
        first, second = middle(3), middle(1)
        dialog.picture.trace_hit(*first)                                  # passes over line 4 first
        lines = dialog.picture.polylines()
        dialog.picture.trace_hit(*second)                                 # then over line 2
        order = [s.name for s in dialog.strokes]
        self.assertEqual(order[:2], [names[3], names[1]])                 # the traced path comes first
        self.assertEqual(sorted(order), sorted(names))                    # nothing lost
        self.assertEqual(dialog.selected, {0, 1})                         # numbered 1, 2
        dialog.picture.trace_hit(*first)                                  # passing again changes nothing
        self.assertEqual([s.name for s in dialog.strokes][:2], [names[3], names[1]])
        dialog.trace_restart()
        self.assertEqual(dialog.traced, [])
        dialog.accept(); self.app.processEvents()
        self.assertEqual([s.name for s in w.drawing.strokes][:2], [names[3], names[1]])

    def test_box_select_and_small_list_moves_several(self):
        w = self.w
        dialog = w.open_line_order()
        dialog.picture_boxed([0, 1])
        self.assertEqual(dialog.selected, {0, 1})
        dialog.reject(); self.app.processEvents()
        names = [s.name for s in w.drawing.strokes]
        w.order.clearSelection()
        w.order.item(1).setSelected(True); w.order.item(2).setSelected(True)
        w.move(1)                                                      # Move down: both lines at once
        self.assertEqual([s.name for s in w.drawing.strokes][2:4], [names[1], names[2]])


if __name__ == '__main__':
    unittest.main()
