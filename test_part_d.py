"""exp.57: painting band by band like a painter (top to bottom, left to right), and
several pictures on one page placed in free spots (a full page goes to a new one)."""
import os
import unittest

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


def blob():
    """A headset-like shape: a band on top and two round parts below."""
    yy, xx = np.mgrid[:120, :160]
    m = ((xx - 80) ** 2 / 50 ** 2 + (yy - 45) ** 2 / 35 ** 2 <= 1) & ~((xx - 80) ** 2 / 36 ** 2 + (yy - 50) ** 2 / 25 ** 2 <= 1)
    m |= (xx - 50) ** 2 + (yy - 80) ** 2 <= 22 ** 2
    m |= (xx - 110) ** 2 + (yy - 80) ** 2 <= 22 ** 2
    return m


@unittest.skipIf(SKIP, 'needs Qt')
class BandTests(unittest.TestCase):
    def plan(self, across):
        from zigzag_paint import _Planner, _band_strokes
        m = blob()
        p = _Planner(m, np.zeros_like(m), (80, 118), .14, .55)
        p.components = m.astype(np.int32); p.component_count = 1
        r = max(1.2, p.max_radius * (.55 + .5 * p.spacing))
        for points in _band_strokes(m, r, across):
            p.hop(points[0], 1, r)
            if p.cursor != points[0]:
                p.move(points[0], 1, False)
            for q in points[1:]:
                p.move(q, 1, True, r)
        return m, p

    def test_top_to_bottom_and_left_to_right(self):
        for across in (False, True):
            m, p = self.plan(across)
            self.assertEqual(int((m & ~np.isfinite(p.arrival)).sum()), 0)       # nothing missed
            self.assertFalse(np.isfinite(p.arrival[~m]).any())                   # background untouched
            ys, xs = np.nonzero(m)
            t = p.arrival[ys, xs]
            along = xs if across else ys
            self.assertGreater(np.corrcoef(along, t)[0, 1], .9)                  # painted in that order

    def test_modes_in_the_menu(self):
        from export_job import REVEAL_BY_TEXT
        self.assertEqual(REVEAL_BY_TEXT['Top to bottom (rows)'], 'rows')
        self.assertEqual(REVEAL_BY_TEXT['Left to right (columns)'], 'columns')


@unittest.skipIf(SKIP, 'needs Qt')
class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_free_spots(self):
        from app import Window
        W, H = 160, 90

        def box(size, x, y):
            m = np.zeros((H, W), bool); bw, bh = .82 * size * W, .78 * size * H
            cx, cy = (.5 + x) * W, (.5 + y) * H
            m[max(0, int(cy - bh / 2)):int(cy + bh / 2), max(0, int(cx - bw / 2)):int(cx + bw / 2)] = True
            return m
        self.assertIsNone(Window.free_spot(box(1, 0, 0)))                       # full page
        size, x, y = Window.free_spot(box(.55, -.22, 0))
        self.assertGreater(x, 15); self.assertLess(abs(y), 8)                    # beside it, centred

    def test_pictures_on_one_page_then_a_new_page(self):
        from app import Window
        w = Window(); w.resize(1400, 860); w.show(); self.app.processEvents()
        try:
            w.duration.setValue(1.)
            self.assertTrue(w.add_picture())                                     # room is made
            self.assertEqual(w.scenes[0]['transition'], 'Same page')
            self.assertGreater(w.picture_x.value(), 10)
            first = w.scenes[0]['state']['settings']
            self.assertLess(float(first['picture_x']), 0)                        # moved to the left
            self.assertEqual(w.scene_list.item(1).text().split()[1], '+')
            # Keep adding: when the page is full, the next one goes to a new page.
            for _ in range(6):
                if w.add_picture() is False:
                    break
            else:
                self.fail('the page never got full')
            self.assertNotEqual(w.scenes[w.scene_index - 1]['transition'], 'Same page')
        finally:
            w.playing = False; w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
