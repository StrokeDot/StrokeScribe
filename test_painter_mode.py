"""exp.88: Painter — a paint mode that paints like a person: real parts, big parts
first and details last, each part brushed around its shape from the edge inwards."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


@unittest.skipIf(SKIP, 'needs Qt')
class PainterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def picture(self):
        """A big blue body, a medium red patch and a small yellow detail."""
        from PIL import Image, ImageDraw
        from adaptive_hand import qimage
        im = Image.new('RGBA', (160, 120), (0, 0, 0, 0))
        p = ImageDraw.Draw(im)
        p.rectangle((4, 4, 155, 115), fill=(40, 70, 200, 255))
        p.ellipse((20, 20, 70, 70), fill=(210, 40, 40, 255))
        p.rectangle((120, 90, 130, 100), fill=(240, 220, 30, 255))
        return im, qimage(im)

    def drawing(self):
        from engine import Drawing, Stroke
        return Drawing([Stroke('outline', [(4, 4), (156, 4), (156, 116), (4, 116), (4, 4)], width=2),
                        Stroke('last', [(150, 110), (152, 110)], width=2)], (0, 0, 160, 120), [])

    def plan(self):
        from painter_paint import build_painter_plan
        pil, image = self.picture()
        return pil, build_painter_plan(self.drawing(), image, .1, .5)

    def colour_times(self, pil, plan):
        gw, gh = plan.size
        small = pil.resize((gw, gh))
        times = {'blue': [], 'red': [], 'yellow': []}
        for i, t in enumerate(plan.arrival):
            if not plan.labels[i]:
                continue
            r, g, b, a = small.getpixel((i % gw, i // gw))
            key = 'blue' if b > 150 and r < 100 else ('red' if r > 150 and g < 100 else ('yellow' if r > 150 and g > 150 else None))
            if key:
                times[key].append(t)
        return times

    def test_everything_is_painted_big_parts_first_details_last(self):
        import math
        pil, plan = self.plan()
        self.assertTrue(all(math.isfinite(t) for t, rid in zip(plan.arrival, plan.labels) if rid))
        times = self.colour_times(pil, plan)
        median = lambda v: sorted(v)[len(v) // 2]
        self.assertLess(median(times['blue']), median(times['red']))       # the big body first
        self.assertLess(median(times['red']), median(times['yellow']))     # the small detail last

    def test_strokes_follow_the_shape(self):
        import numpy as np
        from painter_paint import shape_strokes
        mask = np.zeros((40, 60), bool); mask[5:35, 5:55] = True
        strokes = shape_strokes(mask, 4.)
        self.assertGreaterEqual(len(strokes), 3)                           # rings, from the edge inwards
        first = strokes[0]
        xs, ys = [p[0] for p in first], [p[1] for p in first]
        self.assertLess(min(xs), 7); self.assertGreater(max(xs), 53)       # the first ring goes around the edge
        self.assertLess(min(ys), 7); self.assertGreater(max(ys), 33)

    def test_renders_as_a_paint_mode(self):
        from engine import Drawing  # noqa: F401
        from color_reveal import render_color_timeline
        pil, image = self.picture()
        frames = [render_color_timeline(self.drawing(), f, 320, 240, duration=1, fade_duration=2,
                                        hold_duration=.2, final_image=image, reveal_mode='painter',
                                        brush_width=.1, stroke_spacing=.5) for f in (.5, .7, 1.)]
        self.assertTrue(all(not f.isNull() for f in frames))
        from export_job import REVEAL_BY_TEXT
        self.assertEqual(REVEAL_BY_TEXT['Painter — real parts, strokes follow the shape'], 'painter')

    def test_other_modes_are_unchanged(self):
        from adaptive_hand import plan_for
        pil, image = self.picture()
        d = self.drawing()
        d.paint_method = 'adaptive'
        a = plan_for(d, image, .1, .5)
        d.paint_method = 'painter'
        b = plan_for(d, image, .1, .5)
        self.assertIsNot(a, b)
        self.assertNotEqual([s.a for s in a.segments[:20]], [s.a for s in b.segments[:20]])


if __name__ == '__main__':
    unittest.main()
