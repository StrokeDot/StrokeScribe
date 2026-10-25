"""exp.120: the speed-ups give the same results as before."""
import math
import os
import random
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


@unittest.skipIf(SKIP, 'needs Qt')
class PlanningTests(unittest.TestCase):
    def test_alpha_cells_match_the_pixel_loop(self):
        import numpy as np
        from PIL import Image
        from adaptive_hand import _alpha_cells, VISIBLE_ALPHA
        rng = np.random.default_rng(3)
        for iw, ih in ((640, 400), (97, 333), (1200, 30)):
            a = rng.integers(0, 256, (ih, iw), dtype=np.uint8); a[rng.random((ih, iw)) < .4] = 0
            img = Image.fromarray(np.dstack([a, a, a, a]), 'RGBA')
            ratio = min(1., 160 / max(iw, ih)); gw, gh = max(1, math.ceil(iw * ratio)), max(1, math.ceil(ih * ratio))
            support = bytearray(gw * gh); faint = bytearray(gw * gh)
            for i, al in enumerate(img.getchannel('A').tobytes()):
                if al:
                    cell = min(gh - 1, (2 * (i // iw) + 1) * gh // (2 * ih)) * gw + min(gw - 1, (2 * (i % iw) + 1) * gw // (2 * iw))
                    if al >= VISIBLE_ALPHA: support[cell] = 1
                    else: faint[cell] = 1
            self.assertEqual(_alpha_cells(img, iw, ih, gw, gh), (support, faint))

    def test_nearest_region_matches_min(self):
        from adaptive_hand import _nearest_entry
        random.seed(5)
        gw = 160
        for _ in range(20):
            pool = [(i, (i, [random.randrange(gw * 100) for _ in range(random.randint(1, 40))])) for i in range(12)]
            cursor = (random.uniform(0, gw), random.uniform(0, 100))
            centre = lambda c: (c % gw + .5, c // gw + .5)
            ref = min(((i, min(cells, key=lambda c: math.dist(cursor, centre(c)))) for i, (_, cells) in pool),
                      key=lambda p: math.dist(cursor, centre(p[1])))
            self.assertEqual(_nearest_entry(pool, cursor, gw), ref)

    def test_paint_mask_matches(self):
        from adaptive_hand import PaintPlan
        arrival = [float('inf'), 1., 2., .5, 0.]
        plan = PaintPlan((5, 1), [1] * 5, [], [], arrival, (0, 0), 2., [], 1)
        for p in (0., .3, .5, 1.):
            clock = p / .98 * 2.
            expected = bytes(255 if t <= clock and p > 0 else 0 for t in arrival)
            self.assertEqual(plan.mask(p).tobytes(), expected)


class CacheTests(unittest.TestCase):
    def test_signature_sees_changes_in_big_texts(self):
        from project_lifecycle import ProjectChangeTracker as T
        a = {'png': 'a' * 10000, 'x': [1, 2.5]}
        self.assertEqual(T.signature(a), T.signature({'png': 'a' * 10000, 'x': [1, 2.5]}))
        self.assertNotEqual(T.signature(a), T.signature({'png': 'a' * 9999 + 'b', 'x': [1, 2.5]}))
        self.assertNotEqual(T.signature(a), T.signature({'png': 'a' * 10000, 'x': [1, 2.6]}))

    @unittest.skipIf(SKIP, 'needs Qt')
    def test_decoded_pictures_are_not_changed_by_callers(self):
        from PySide6.QtGui import QColor, QImage, QPainter
        from projects import qimage_from_b64, qimage_to_b64
        src = QImage(20, 10, QImage.Format.Format_ARGB32_Premultiplied); src.fill(QColor('red'))
        text = qimage_to_b64(src)
        first = qimage_from_b64(text)
        p = QPainter(first); p.fillRect(0, 0, 20, 10, QColor('blue')); p.end()
        again = qimage_from_b64(text)
        self.assertEqual(again.pixelColor(5, 5).name(), '#ff0000')


if __name__ == '__main__':
    unittest.main()
