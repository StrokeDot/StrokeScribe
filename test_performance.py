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


@unittest.skipIf(SKIP, 'needs Qt')
class FrameWriterTests(unittest.TestCase):
    def test_frames_are_the_same_pictures(self):
        import tempfile
        from pathlib import Path
        from PySide6.QtGui import QColor, QImage
        from frame_writer import FrameWriter
        folder = Path(tempfile.mkdtemp())
        a = QImage(64, 36, QImage.Format.Format_ARGB32_Premultiplied); a.fill(QColor(200, 30, 60, 128))
        b = QImage(64, 36, QImage.Format.Format_ARGB32_Premultiplied); b.fill(QColor(10, 220, 60))
        writer = FrameWriter(threads=3)
        for i, img in enumerate((a, a, b, b, a)):
            writer.write(img, folder / f'frame_{i:06d}.png')
        writer.close()
        for i, img in enumerate((a, a, b, b, a)):
            back = QImage(str(folder / f'frame_{i:06d}.png')).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            self.assertEqual(back.pixelColor(5, 5), img.pixelColor(5, 5))


class CacheTests(unittest.TestCase):
    def test_signature_sees_changes_in_big_texts(self):
        from project_lifecycle import ProjectChangeTracker as T
        a = {'png': 'a' * 10000, 'x': [1, 2.5]}
        self.assertEqual(T.signature(a), T.signature({'png': 'a' * 10000, 'x': [1, 2.5]}))
        self.assertNotEqual(T.signature(a), T.signature({'png': 'a' * 9999 + 'b', 'x': [1, 2.5]}))
        self.assertNotEqual(T.signature(a), T.signature({'png': 'a' * 10000, 'x': [1, 2.6]}))

    def test_signature_of_many_points_sees_one_moved_point(self):
        # exp.130: long lists of numbers are digested in one go.
        from project_lifecycle import ProjectChangeTracker as T
        points = [[i * .5, i * .25] for i in range(5000)]
        a = {'strokes': [{'points': points}], 'xs': list(range(200))}
        sig = T.signature(a)
        self.assertEqual(sig, T.signature({'strokes': [{'points': [list(p) for p in points]}], 'xs': list(range(200))}))
        points[2500][1] += .001
        self.assertNotEqual(sig, T.signature(a))
        self.assertNotEqual(T.signature({'p': [[1, 2]] * 70}), T.signature({'p': [[1, 2]] * 69 + [[1, 3]]}))
        self.assertNotEqual(T.signature({'p': [[1, 'x']] * 70}), T.signature({'p': [[1, 'y']] * 70}))

    @unittest.skipIf(SKIP, 'needs Qt')
    def test_sample_drawing_is_kept_ready(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        import engine
        sample = Path(__file__).parent / 'samples' / 'drawing.svg'
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict('os.environ', {'STROKESCRIBE_PREVIEW_CACHE': str(Path(tmp) / 'p')}):
            first = engine.import_svg_cached(sample)
            with mock.patch.object(engine, 'import_svg', side_effect=AssertionError('read again')):
                again = engine.import_svg_cached(sample)
        plain = engine.import_svg(sample)
        self.assertEqual([s.points for s in again.strokes], [s.points for s in plain.strokes])
        self.assertEqual([s.distances for s in again.strokes], [s.distances for s in first.strokes])
        self.assertEqual(again.bounds, plain.bounds)

    def test_cv2_waits_until_used(self):
        from lazy_import import Lazy
        math_module = Lazy('math')
        self.assertEqual(math_module.sqrt(9), 3)

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
