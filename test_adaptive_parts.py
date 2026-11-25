"""exp.85: Adaptive Hand Painting paints part by part even when the SVG is mostly
open lines (a traced drawing whose only closed shape is the outer outline).

Before, the whole picture was one region and the brush zigzagged across all of
it; now a region that big is split into the picture's colour areas."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


@unittest.skipIf(SKIP, 'needs Qt')
class PartByPartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def picture(self):
        from PIL import Image, ImageDraw
        from adaptive_hand import qimage
        im = Image.new('RGBA', (120, 120), (0, 0, 0, 0))
        p = ImageDraw.Draw(im)
        p.rectangle((4, 4, 59, 115), fill=(200, 40, 40, 255))      # left part: red
        p.rectangle((60, 4, 115, 115), fill=(40, 60, 200, 255))    # right part: blue
        return im, qimage(im)

    def drawing(self):
        from engine import Drawing, Stroke
        outline = Stroke('outline', [(4, 4), (115, 4), (115, 115), (4, 115), (4, 4)], width=2)
        open_line = Stroke('open', [(30, 30), (90, 90)], width=2)
        return Drawing([outline, open_line, Stroke('last', [(10, 10), (12, 10)], width=2)], (0, 0, 120, 120), [])

    def test_one_big_outline_is_painted_part_by_part(self):
        from adaptive_hand import build_plan
        pil, image = self.picture()
        plan = build_plan(self.drawing(), image, .08, .2)
        self.assertGreaterEqual(plan.region_count, 2)
        gw, gh = plan.size
        small = pil.resize((gw, gh))
        red, blue = [], []
        for i, t in enumerate(plan.arrival):
            if plan.labels[i]:
                r, g, b, a = small.getpixel((i % gw, i // gw))
                (red if r > b else blue).append(t)
        first, second = (red, blue) if min(red) < min(blue) else (blue, red)
        # One part is finished before the brush starts the other (no zigzag across both).
        late = sum(1 for t in first if t > min(second))
        self.assertLess(late, .03 * len(first))

    def test_drawings_with_their_own_parts_are_unchanged(self):
        import adaptive_hand
        from adaptive_hand import build_plan
        from engine import Drawing, Stroke
        pil, image = self.picture()
        halves = Drawing([Stroke('left', [(4, 4), (59, 4), (59, 115), (4, 115), (4, 4)], width=2),
                          Stroke('right', [(60, 4), (115, 4), (115, 115), (60, 115), (60, 4)], width=2),
                          Stroke('last', [(10, 10), (12, 10)], width=2)], (0, 0, 120, 120), [])
        with_split = build_plan(halves, image, .08, .2)
        share = adaptive_hand.OPEN_AREA_SHARE
        try:
            adaptive_hand.OPEN_AREA_SHARE = 2.          # never split: the plan before exp.85
            before = build_plan(halves, image, .08, .2)
        finally:
            adaptive_hand.OPEN_AREA_SHARE = share
        # Each half is 50% > 30%, but splitting a single-colour half changes nothing.
        self.assertEqual(with_split.region_count, before.region_count)
        self.assertEqual(with_split.arrival, before.arrival)


if __name__ == '__main__':
    unittest.main()
