"""exp.43 (the user: the order makes no sense; the sticker's green dot cannot move): the writing
hand does one thing at a time (Hand motions and hand-drawn stickers wait for it), and a
sticker's hand starts where the hand really is (outside the picture: below the middle, or where
it was put)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class OneHand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg'))
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(40): APP.processEvents()
        w.hand_rest.setChecked(True)
        w.preview_scope.setCurrentIndex(1)
        for _ in range(40): APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def tearDown(self):
        w = self.w
        w.cameras[:] = [c for c in w.cameras if c.get('kind') != 'Hand motion']
        w.overlays[:] = [o for o in w.overlays if o.get('kind') != 'sticker']
        w.refresh(); APP.processEvents()

    def spans(self):
        import camera_clips, stickers
        w = self.w
        out = list(w.hand_busy_spans())
        out += [(c['start'], c['start'] + c['duration']) for c in w.cameras if c.get('kind') == camera_clips.MOVE]
        out += [tuple(stickers.busy(o)) for o in w.overlays if o.get('kind') == 'sticker' and stickers.hand_mode(o)]
        return sorted(out)

    def sticker(self, start):
        w = self.w
        w.add_sticker('Circle')
        st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        st['drawing'] = 'Hand: outline'; st['start'] = start
        return st

    def test_a_nothing_overlaps_and_it_stays_put(self):
        import camera_clips
        w = self.w
        busy = w.hand_busy_spans()
        c = camera_clips.new_clip('Hand motion', round(busy[0][1] - .5, 2)); c['duration'] = 1.
        w.cameras.append(c)                                   # starts during element 1's way back
        st = self.sticker(round(busy[1][1] - .2, 2))         # overlaps element 2's way back
        w.refresh(); APP.processEvents()
        spans = self.spans()
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            self.assertLessEqual(a1, b0 + 1e-4, spans)
        # exp.46 (the user: a Hand motion overrules what is under it): it stays where it was put;
        # element 1's way back is dropped from that moment
        self.assertAlmostEqual(c['start'], round(busy[0][1] - .5, 2), places=2)
        self.assertAlmostEqual(w.scenes[0].get('_motion_cut_at'), c['start'], places=2)
        before = (c['start'], st['start'])
        w.refresh(); APP.processEvents()
        self.assertEqual((c['start'], st['start']), before)   # stable

    def test_b_the_sticker_starts_where_a_hand_motion_left_the_hand(self):
        import camera_clips, stickers
        w = self.w
        end = w.hand_busy_spans()[-1][1]
        c = camera_clips.new_clip('Hand motion', round(end + .1, 2))
        c['duration'] = .8; c['back'] = False; c['path'] = [[.5, .5], [.3, .4]]
        w.cameras.append(c)
        st = self.sticker(round(end + 2.5, 2))
        w.refresh(); APP.processEvents()
        self.assertFalse(st['_home_outside'])
        W = 960; H = round(W * w.board_aspect())
        spot, _ = w.hand_spot_at(W, H, stickers.busy(st)[0] - 1e-3)
        self.assertAlmostEqual(st['_home_screen'][0] * W, spot[0], delta=1)
        self.assertAlmostEqual(st['_home_screen'][1] * H, spot[1], delta=1)
        self.assertAlmostEqual(spot[0] / W, .3, delta=.02)    # where the Hand motion left it
        span = stickers.busy(st)                              # its hand really starts there
        tip = stickers.hand_tip(st, span[0] + 1e-3, W, H, stickers.home_on_frame(st, W, H))
        self.assertAlmostEqual(tip[0], .3 * W, delta=4); self.assertAlmostEqual(tip[1], .4 * H, delta=4)
        back = stickers.hand_tip(st, span[1] - 1e-3, W, H, stickers.home_on_frame(st, W, H))
        self.assertAlmostEqual(back[0], .3 * W, delta=4)        # and goes back there

    def test_c_outside_the_picture_below_the_middle_and_it_can_be_put(self):
        import camera_clips
        w = self.w
        end = w.hand_busy_spans()[-1][1]
        c = camera_clips.new_clip('Hand motion', round(end + .1, 2))
        c['duration'] = .8; c['back'] = False; c['path'] = [[.5, .5], [.2, 2.4]]   # far below
        w.cameras.append(c)
        st = self.sticker(round(end + 2.5, 2))
        w.refresh(); APP.processEvents()
        self.assertTrue(st['_home_outside'])
        self.assertAlmostEqual(st['_home_screen'][0], .5, delta=.01)
        self.assertGreater(st['_home_screen'][1], 1.); self.assertLess(st['_home_screen'][1], 1.4)
        rows = [r for r in w.hand_path_rows() if r['kind'] == 'sticker' and r['which'] == 'in']
        self.assertTrue(rows and rows[0]['movable_start'])
        st['hand_start'] = [.8, 1.1]
        w.refresh(); APP.processEvents()
        self.assertEqual(st['_home_screen'], [.8, 1.1])



class Zoomed(unittest.TestCase):
    def test_home_through_the_camera(self):
        import stickers
        item = {'_home_screen': [.5, .5]}
        to_screen = lambda x, y: (10 + x * .5, 20 + y * .5)        # the page, zoomed out and moved
        x, y = stickers.home_on_frame(item, 960, 540, 960, None, to_screen)
        self.assertAlmostEqual(x, (480 - 10) / .5, delta=.01)
        self.assertAlmostEqual(y, (270 - 20) / .5, delta=.01)
        sx, sy = to_screen(x, y)
        self.assertAlmostEqual(sx, 480, delta=.01); self.assertAlmostEqual(sy, 270, delta=.01)


if __name__ == '__main__':
    unittest.main()
