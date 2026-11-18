"""exp.29 (the user): a sticker can be drawn by the hand: only its main shape (outline) or every
stroke; the hand comes from its resting corner (and the waiting hand leaves it) or comes in and
leaves; a sticker drawn by the hand waits for the element's hand; off by default."""
import math
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def hand_picture():
    img = QImage(100, 60, QImage.Format.Format_ARGB32); img.fill(QColor(160, 110, 70))
    return img


class Logic(unittest.TestCase):
    def setUp(self):
        import stickers
        stickers.set_hand(hand_picture(), .2, (.05, .1), 'Bottom right')

    def tearDown(self):
        import stickers
        stickers.set_hand(None, .2, (0, 0), None)

    def test_off_by_default(self):
        import stickers
        item = stickers.new('Circle')
        self.assertEqual(item['drawing'], 'Animated')
        self.assertIsNone(stickers.busy(item))
        self.assertIsNone(stickers.hand_tip(item, 1., 640, 360))

    def test_the_pen_follows_the_line_and_the_hand_comes_from_its_corner(self):
        import stickers
        from frame_render import REST_CORNERS
        item = stickers.new('Line'); item.update(start=1., draw_seconds=1., drawing='Hand: outline', x=.5, y=.5,
                                                size=.5)
        W, H = 640, 360
        corner = (REST_CORNERS['Bottom right'][0] * W, REST_CORNERS['Bottom right'][1] * H)
        a = stickers.hand_tip(item, 1. - stickers.GLIDE, W, H)
        self.assertLess(math.dist(a, corner), 1.)                       # starts at the corner
        b = stickers.hand_tip(item, 1., W, H)
        self.assertLess(abs(b[0] - (W * .25 + .03 * W * .5)), 3)          # at the line's start
        mid = stickers.hand_tip(item, 1.5, W, H)
        self.assertAlmostEqual(mid[1], H / 2, delta=1)                    # on the line
        self.assertGreater(mid[0], b[0] + 50)
        back = stickers.hand_tip(item, 2. + stickers.GLIDE, W, H)
        self.assertLess(math.dist(back, corner), 1.)                    # back in its corner
        self.assertIsNone(stickers.hand_tip(item, 2. + stickers.GLIDE + .1, W, H))

    def test_comes_in_and_leaves_goes_out_of_the_picture(self):
        import stickers
        item = stickers.new('Circle'); item.update(start=1., drawing='Hand: everything', hand_way='Comes in and leaves')
        self.assertGreater(stickers.hand_tip(item, 1. - stickers.GLIDE, 640, 360)[1], 360)
        self.assertEqual(stickers.busy_spans([item]), [])               # the corner hand is not used

    def test_outline_pops_the_head_everything_draws_it_by_hand(self):
        import stickers
        item = stickers.new('Arrow'); item.update(start=0., draw_seconds=1., drawing='Hand: outline')
        line, head = stickers.phases(item, 1.)
        self.assertEqual((line, head), (1., [0., 0.]))                   # the head comes after the hand
        self.assertEqual(stickers.phases(item, 1.01 + stickers.HEAD_POP)[1], [1., 1.])
        item['drawing'] = 'Hand: everything'
        line, head = stickers.phases(item, .8)
        self.assertEqual(line, 1.); self.assertGreater(head[0], 0); self.assertEqual(head[1], 0)
        self.assertEqual([round(x, 6) for x in stickers.phases(item, 1.)[1]], [1., 1.])

    def test_the_waiting_hand_leaves_its_corner_meanwhile(self):
        import stickers
        from frame_render import paint_rest_hand
        item = stickers.new('Circle'); item.update(start=2., draw_seconds=1., drawing='Hand: outline')
        blank = QImage(320, 180, QImage.Format.Format_ARGB32_Premultiplied); blank.fill(0)
        opts = dict(hand=hand_picture(), hand_scale=.2, anchor=(.05, .1), hand_rest_corner='Bottom right',
                    _sticker_busy=stickers.busy_spans([item]))
        self.assertIsNot(paint_rest_hand(blank, opts, 1.), blank)         # waiting in its corner
        self.assertIs(paint_rest_hand(blank, opts, 2.5), blank)           # gone to draw the sticker

    def test_the_hand_is_painted_and_not_in_drawing_only(self):
        import overlays, stickers
        item = stickers.new('Line', color='#2050E0'); item.update(start=1., drawing='Hand: outline', duration=3.)
        f = QImage(320, 180, QImage.Format.Format_ARGB32); f.fill(QColor('white'))
        g = f.copy()
        overlays.paint(f, [item], .8)                                     # the hand on its way
        overlays.paint(g, [item], .8, hands=False)
        self.assertNotEqual(f, g)


class Waiting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(40): APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def test_a_sticker_drawn_by_the_hand_waits_for_the_drawing_hand(self):
        w = self.w
        item = w.add_sticker('Circle')
        item.update(start=.2)
        w.sticker_drawing.setCurrentText('Hand: outline')
        busy_end = max(b for a, b in w.hand_busy_spans())
        import stickers
        self.assertGreaterEqual(stickers.busy(item)[0], busy_end - 1e-6)
        item['drawing'] = 'Animated'; item['start'] = .2
        self.assertFalse(w.place_hand_sticker(item))                      # no hand: anywhere
        self.assertEqual(item['start'], .2)


if __name__ == '__main__':
    unittest.main()
