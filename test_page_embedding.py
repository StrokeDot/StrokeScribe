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


@unittest.skipIf(SKIP, 'needs Qt')
class Exp5Tests(unittest.TestCase):
    """exp.5: the painting order does not change with the edges' look; no lag; no card while
    switching."""
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def picture(self):
        rng = np.random.default_rng(4)
        a = np.zeros((120, 200, 4), np.float32)
        a[..., :3] = rng.random((120, 200, 1)) * 200 + 30
        a[..., 3] = 255
        return qimage(a)

    def test_the_route_is_planned_on_the_plain_look(self):
        import picture_look
        image = self.picture()
        s = dict(picture_look.DEFAULTS, ink_on=True)
        plain, shown = picture_look.pictures(image, s)
        self.assertIsNone(shown)                                   # the plain look: one picture
        for extra in (dict(ink_edges='Sketch edges'), dict(ink_colour=picture_look.GRAPHITE),
                      dict(ink_edges='Sketch edges', ink_colour=picture_look.GRAPHITE)):
            route, shown = picture_look.pictures(image, dict(s, **extra))
            self.assertIs(route, plain)                            # the same route: same order
            self.assertIsNotNone(shown)                            # the look itself is shown

    def test_the_shown_look_is_what_appears(self):
        import picture_look
        from color_reveal import render_color_timeline
        from engine import Drawing, Stroke
        from adaptive_hand import pil_image
        image = self.picture()
        s = dict(picture_look.DEFAULTS, ink_on=True, ink_colour=picture_look.GRAPHITE)
        route, shown = picture_look.pictures(image, s)
        d = Drawing([Stroke('a', [(0, 0), (200, 0), (200, 120)], width=2)], (0, 0, 200, 120), [])
        d.source_kind = 'image'; d.image_animation = 'paint_only'
        end = lambda img: np.asarray(pil_image(render_color_timeline(
            d, 1., 200, 120, duration=0, fade_duration=1, hold_duration=.2, final_image=route,
            reveal_mode='adaptive', display_image=img)).convert('RGBA')).astype(int)
        self.assertGreater(np.abs(end(shown) - end(None)).mean(), 1.)

    def test_the_fold_reworks_only_a_strip(self):
        import time
        import page_fold
        from PySide6.QtGui import QImage
        frame = QImage(4000, 2200, QImage.Format.Format_ARGB32_Premultiplied); frame.fill(0xff202020)
        started = time.perf_counter()
        picture, c0 = page_fold.fold_strip(frame, 1000., -200, 4000, 1920)
        self.assertLess(picture.width(), 400)                      # a strip, not the whole frame
        self.assertLess(time.perf_counter() - started, .25)

    def test_no_card_when_changing_the_paint_mode_while_paused(self):
        from app import Window
        from engine import Drawing, Stroke
        w = Window(); self.addCleanup(w.close)
        cards = []
        w.show_busy_now = lambda text, detail='': cards.append(text)
        w.canvas.frame = self.picture()
        w.drawing = Drawing([Stroke('a', [(0, 0), (200, 0), (200, 120)], width=2)], (0, 0, 200, 120), [])
        w.final_image = self.picture(); w.use_color.setChecked(True)
        w._animating = False
        o = w.options(); o['reveal_mode'] = 'painter'
        self.assertEqual(w.ensure_brush_plan(o), 'background')    # planned in the background
        self.assertTrue(w._plan_waiting)                          # the frame waits; the view is built
        self.assertEqual(cards, [])
        if getattr(w, 'plan_worker', None) is not None:
            w.plan_worker.wait(30000)
