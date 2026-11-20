"""Zigzag sweep painting tests (synthetic shapes; no personal artwork)."""
import math
import os
import unittest

import cv2
import numpy as np

from zigzag_paint import plan_cells


def headset(size=160):
    """A band over two round cups with a thin arm: a simple 'headset'."""
    m = np.zeros((size, size), np.uint8)
    cv2.ellipse(m, (80, 70), (55, 50), 0, 180, 360, 1, 12)          # band
    cv2.circle(m, (32, 95), 22, 1, -1)                               # left cup
    cv2.circle(m, (128, 95), 22, 1, -1)                              # right cup
    cv2.line(m, (128, 117), (60, 145), 1, 3)                         # thin arm
    return m.astype(bool)


class ShortStrokeTests(unittest.TestCase):
    def test_short_vertical_strokes_alternate_and_stay_compact(self):
        from zigzag_paint import _band_strokes
        canvas=np.zeros((48,160),bool)
        canvas[8:40,8:150]=True
        paths=_band_strokes(canvas,4.5,False,short_vertical=True)
        self.assertTrue(paths)
        longest=max(paths,key=len)
        self.assertGreater(len(longest),15)
        flips=sum(1 for a,b in zip(longest,longest[1:])
                  if abs(a[1]-b[1])>1.)
        self.assertGreater(flips,len(longest)*.8)
        self.assertLess(max(abs(a[0]-b[0]) for a,b in zip(longest,longest[1:])),4.5)

    def test_short_stroke_paint_plan_covers_all_visible_pixels(self):
        from zigzag_paint import _Planner,_band_strokes
        mask=np.zeros((44,90),bool)
        mask[8:36,10:80]=True
        mask[18:26,34:40]=False
        plan=_Planner(mask,np.zeros_like(mask),(4.,4.),.14,.55)
        plan.components=mask.astype(np.int32)
        plan.component_count=1
        radius=max(1.2,plan.max_radius*(.55+.5*plan.spacing))
        for points in _band_strokes(mask,radius,False,short_vertical=True):
            plan.hop(points[0],1,radius)
            for p in points[1:]:plan.move(p,1,True,radius)
        self.assertTrue(any(s[4] for s in plan.segments))
        self.assertFalse(np.isfinite(plan.arrival[~mask]).any())


class ZigzagPlanTests(unittest.TestCase):
    def plan(self, mask, origin=(80., 10.)):
        faint = np.zeros_like(mask)
        return plan_cells(mask, faint, origin, .14, .55)

    def test_every_visible_cell_is_painted_and_nothing_else(self):
        mask = headset()
        labels, segments, arrival, total, regions = self.plan(mask)
        self.assertEqual(regions, 1)
        self.assertTrue(np.isfinite(arrival[mask]).all(), 'full coverage')
        self.assertFalse(np.isfinite(arrival[~mask]).any(), 'no paint outside')
        self.assertLessEqual(float(arrival[mask].max()), total + 1e-6)

    def test_starts_near_where_the_drawing_ended(self):
        mask = headset()
        for origin in ((10., 100.), (150., 100.)):
            _, segments, arrival, _, _ = self.plan(mask, origin)
            first = min(zip(*np.nonzero(arrival <= np.nanmin(arrival[mask]) + 5)),
                        key=lambda p: math.dist((p[1], p[0]), origin))
            self.assertLess(math.dist((first[1] + .5, first[0] + .5), origin), 40)

    def test_strokes_zigzag_across_the_shape(self):
        mask = np.zeros((60, 200), bool)
        mask[20:40, 10:190] = True                                   # a long bar
        _, segments, _, _, _ = self.plan(mask, (0., 30.))
        tips = [s[1] for s in segments if s[4]]
        sides = [np.sign(y - 30) for _, y in tips if abs(y - 30) > 3]
        flips = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
        self.assertGreater(flips, len(sides) * .6, 'alternates across the bar')
        xs = [x for x, _ in tips]
        self.assertLess(xs[0], 60)                                   # left to right
        self.assertGreater(xs[len(xs) // 2], 60)

    def test_one_continuous_route_with_few_lifts(self):
        mask = headset()
        _, segments, _, _, _ = self.plan(mask)
        painting = sum(1 for s in segments if s[4])
        lifts = sum(1 for s in segments if not s[4])
        self.assertGreater(painting, 10)
        self.assertLess(lifts, painting / 2)

    def test_separate_pieces_and_repeatable(self):
        mask = np.zeros((80, 160), bool)
        mask[10:30, 10:70] = True
        mask[50:70, 90:150] = True
        a = self.plan(mask)
        b = self.plan(mask)
        self.assertEqual(a[4], 2)
        self.assertTrue(np.isfinite(a[2][mask]).all())
        self.assertTrue(np.array_equal(a[2], b[2]))

    def test_timing_rules_match_adaptive(self):
        mask = headset()
        _, segments, _, total, _ = self.plan(mask)
        clock = 0.
        for a, b, r, region, painting, start, end in segments:
            self.assertAlmostEqual(start, clock, places=6)
            d = math.dist(a, b)
            expected = max(.05, d) if painting else max(.5, min(12., d * .2))
            self.assertAlmostEqual(end - start, expected, places=6)
            clock = end
        self.assertAlmostEqual(clock, total, places=6)


@unittest.skipIf(os.environ.get('STROKESCRIBE_SKIP_QT') == '1', 'needs Qt')
class ZigzagRenderTests(unittest.TestCase):
    def test_plan_for_and_timeline_use_zigzag(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from adaptive_hand import plan_for, pil_image
        from color_reveal import render_color_timeline
        from engine import Drawing, Stroke
        image = QImage(160, 160, QImage.Format.Format_RGBA8888)
        image.fill(0)
        for y, x in zip(*np.nonzero(headset())):
            image.setPixel(int(x), int(y), 0xff3070c0)
        d = Drawing([Stroke('a', [(10., 10.), (150., 150.)])], (0, 0, 160, 160), [])
        d.paint_method = 'zigzag'
        zig = plan_for(d, image)
        d.paint_method = 'adaptive'
        ada = plan_for(d, image)
        self.assertIsNot(zig, ada)
        self.assertNotEqual([s.end for s in zig.segments][:5], [s.end for s in ada.segments][:5])
        kwargs = dict(width=320, height=240, duration=1, fade_duration=1, hold_duration=0,
                      final_image=image)
        mid = pil_image(render_color_timeline(d, .75, reveal_mode='zigzag', **kwargs))
        self.assertEqual(d.paint_method, 'zigzag')
        end = pil_image(render_color_timeline(d, 1, reveal_mode='zigzag', **kwargs))
        painted = lambda im: sum(1 for p in im.getdata() if p[3] > 0 and p[2] > 150)
        self.assertGreater(painted(mid), 0)
        self.assertGreater(painted(end), painted(mid))


if __name__ == '__main__':
    unittest.main(verbosity=2)
