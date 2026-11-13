"""1.0.1-experimental.4: the drawing embedded in the page (Graphite on paper, Sketch edges,
Follow the page fold)."""
import os
import unittest

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


def qimage(a):
    from PySide6.QtGui import QImage
    a = np.ascontiguousarray(a.astype(np.uint8))
    h, w = a.shape[:2]
    return QImage(a.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


def book(w=400, h=240, fold=None):
    """A warm page with a darker fold valley down the middle."""
    a = np.zeros((h, w, 4), np.float32)
    a[..., 0], a[..., 1], a[..., 2], a[..., 3] = 230, 205, 160, 255
    if fold is not None:
        xx = np.arange(w)
        a[..., :3] *= (1 - .35 * np.exp(-((xx - fold) / 4.) ** 2))[None, :, None]
    return qimage(a)


@unittest.skipIf(SKIP, 'needs Qt')
class EmbeddingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_finds_the_fold_of_an_open_book(self):
        import page_fold
        self.assertAlmostEqual(page_fold.find_fold(book(fold=210), 0, 0, 400, 240), 210.5, delta=2)
        self.assertIsNone(page_fold.find_fold(book(), 0, 0, 400, 240))          # a flat page: none
        self.assertAlmostEqual(page_fold.find_fold(book(fold=210), 100, 20, 240, 200), 210.5, delta=2)

    def test_the_drawing_bends_into_the_fold_and_fades_in_the_gutter(self):
        import page_fold
        from adaptive_hand import pil_image
        ink = np.zeros((240, 400, 4), np.float32); ink[..., 3] = 255.     # black ink everywhere
        out = np.asarray(pil_image(page_fold.follow_fold(qimage(ink), 200., 0, 400, 400)).convert('RGBA'))
        alpha = out[120, :, 3].astype(int)
        self.assertLess(alpha[200], 10)                          # no pencil in the gutter
        self.assertGreater(alpha[100], 250)                      # the page itself unchanged
        self.assertGreater(alpha[300], 250)

    def test_graphite_on_paper(self):
        import picture_look
        rng = np.random.default_rng(1)
        lum = np.clip(rng.random((120, 160)) * .9 + .05, 0, 1)
        rgba = np.dstack([lum, lum, lum, np.ones_like(lum)]).astype(np.float32)
        out = picture_look.ink(rgba, colour_rgb=picture_look.INK_COLOURS[picture_look.GRAPHITE],
                               edges='none', graphite=True)
        self.assertLessEqual(float(out[..., 3].max()), .91)      # never a solid black sticker
        plain = picture_look.ink(rgba, edges='none')
        self.assertGreater(float(plain[..., 3].max()), .99)

    def test_sketch_edges_end_raggedly(self):
        import picture_look
        lum = np.full((120, 160), .2, np.float32)
        lum[:, ::4] = .05
        rgba = np.dstack([lum, lum, lum, np.ones_like(lum)]).astype(np.float32)
        soft = picture_look.ink(rgba, edges='soft', edge_size=20)[..., 3]
        sketch = picture_look.ink(rgba, edges='sketch', edge_size=20)[..., 3]
        self.assertLess(float(sketch[:, 0].max()), .05)          # nothing at the very border
        band = slice(4, 18)
        self.assertGreater(float(sketch[60, band].std() + sketch[band, 80].std()),
                           float(soft[60, band].std() + soft[band, 80].std()) * .5)
        rows = sketch[band, 30:130]                              # ragged: varies along the edge
        self.assertGreater(float(rows.std(axis=1).mean()), float(soft[band, 30:130].std(axis=1).mean()) + .02)

    def test_settings(self):
        from export_job import options_from_settings
        import picture_look
        self.assertFalse(picture_look.DEFAULTS['ink_fold'])
        self.assertIn('Sketch edges', picture_look.EDGES)
        from app import Window
        w = Window(); self.addCleanup(w.close)
        s = w.settings_state()
        self.assertEqual(options_from_settings(s, w.drawing).get('blend_mode'), 'Normal')
        s.update(ink_on=True, ink_colour=picture_look.GRAPHITE, ink_fold=True)
        o = options_from_settings(s, w.drawing)
        self.assertEqual(o['blend_mode'], 'Multiply')          # graphite darkens the page
        self.assertTrue(o['follow_fold'])
        s.update(blend_mode='Screen')
        self.assertEqual(options_from_settings(s, w.drawing)['blend_mode'], 'Screen')   # the user's choice wins
        self.assertTrue(hasattr(w, 'ink_fold'))


if __name__ == '__main__':
    unittest.main()
