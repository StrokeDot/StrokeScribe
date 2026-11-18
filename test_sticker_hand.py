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


class Ways(unittest.TestCase):
    """exp.31 (the user: the same Hand settings as an element's): way in / back, How, Turn, Path."""
    def setUp(self):
        import stickers
        stickers.set_hand(hand_picture(), .2, (.05, .1), 'Bottom right')

    def tearDown(self):
        import stickers
        stickers.set_hand(None, .2, (0, 0), None)

    def item(self, **kw):
        import stickers
        item = stickers.new('Line'); item.update(start=2., draw_seconds=1., drawing='Hand: outline', x=.3, y=.3, size=.3)
        item.update(kw)
        return item

    def test_the_ways_set_how_long_the_hand_is_busy(self):
        import stickers
        item = self.item(hand_in=1.2, hand_out=.7)
        self.assertEqual(stickers.busy(item), (.8, 3.7))

    def test_curve_bends_the_way_and_a_path_is_followed(self):
        import math, stickers
        W, H = 640, 360
        home, first, _ = stickers.way_ends(self.item(), W, H)
        straight = stickers.hand_tip(self.item(), 1.75, W, H)
        curved = stickers.hand_tip(self.item(hand_in_style='Curve', hand_in_bend='Clockwise'), 1.75, W, H)

        def off_line(p):
            (x1, y1), (x2, y2) = home, first
            return abs((y2 - y1) * p[0] - (x2 - x1) * p[1] + x2 * y1 - y2 * x1) / math.dist(home, first)
        self.assertLess(off_line(straight), 2)
        self.assertGreater(off_line(curved), 10)
        from frame_render import to_keyframe
        far = to_keyframe(home, first, (W * .1, H * .1))           # a keyframe far off to the top left
        pathed = stickers.hand_tip(self.item(hand_in_path=[far]), 1.75, W, H)
        self.assertGreater(off_line(pathed), 30)                    # it goes the way of its keyframe


class HandSize(unittest.TestCase):
    """exp.30 (the user: the hand was huge): the camera zooms the page with the sticker, not the hand."""
    def setUp(self):
        import stickers
        img = QImage(100, 60, QImage.Format.Format_ARGB32); img.fill(QColor(0, 200, 0))
        stickers.set_hand(img, .2, (0., 0.), 'Bottom right')

    def tearDown(self):
        import stickers
        stickers.set_hand(None, .2, (0, 0), None)

    def green_width(self, image):
        cols = set()
        for y in range(0, image.height(), 2):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                if c.green() > 150 and c.red() < 80 and c.blue() < 80:
                    cols.add(x)
        return (max(cols) - min(cols) + 1) if cols else 0

    def test_the_same_size_with_a_zooming_camera(self):
        import stickers, timeline_render
        item = stickers.new('Line', color='#2050E0')
        item.update(start=1., draw_seconds=1., drawing='Hand: outline', x=.3, y=.3, size=.2)
        W, H = 640, 360

        def frame(zoom):
            out = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied); out.fill(QColor('white'))
            place = lambda f, view, w, h: (0., 0., w * zoom, h * zoom)   # the page, zoomed by the camera
            return timeline_render.paint_texts(out, [item], 1.4, [None], place, object())
        plain, zoomed = self.green_width(frame(1.)), self.green_width(frame(2.))
        self.assertGreater(plain, 50)
        self.assertAlmostEqual(zoomed, plain, delta=4)               # not twice as big


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
        marks = w.sticker_hand_marks()                                    # exp.30: on the Hand row
        self.assertEqual([m[4] for m in marks], [item['id']])
        self.assertAlmostEqual(marks[0][0], stickers.busy(item)[0])
        item['drawing'] = 'Animated'; item['start'] = .2
        self.assertFalse(w.place_hand_sticker(item))                      # no hand: anywhere
        self.assertEqual(item['start'], .2)


if __name__ == '__main__':
    unittest.main()
