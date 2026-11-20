"""exp.70 (the user: the hand does not follow the path; added seconds must go to the right, not
before; the hand stayed below the middle after a camera step)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def pump(n=20):
    for _ in range(n): APP.processEvents()


class ToTheRight(unittest.TestCase):
    def test_a_longer_way_in_pushes_the_drawing_later(self):
        import stickers
        s = stickers.new('Circle', 10., 4.); s['drawing'] = 'Hand: outline'
        s['hand_in'] = .5
        a = stickers.draw_start(s)
        s['hand_in'] = 2.
        self.assertAlmostEqual(stickers.busy(s)[0], 10.)            # the hand starts at the clip's start
        self.assertAlmostEqual(stickers.draw_start(s) - a, 1.5)     # the drawing moves right

    def test_older_stickers_keep_their_moment(self):
        import stickers
        s = stickers.new('Circle', 10., 3.); s.pop('clip_v2'); s.update(drawing='Hand: outline', hand_in=1.2)
        drawn, busy = stickers.draw_start(s), stickers.busy(s)
        stickers.migrate([s])
        self.assertAlmostEqual(stickers.draw_start(s), drawn)
        self.assertEqual(stickers.busy(s), busy)
        self.assertAlmostEqual(s['start'], 8.8)                      # the clip starts where its hand does
        self.assertAlmostEqual(s['start'] + s['duration'], 13.)      # and still ends where it did


class ParkingEnds(unittest.TestCase):
    def test_a_camera_move_that_began_during_the_motion_ends_it(self):
        import camera_clips
        clip = dict(start=31., duration=3.)                          # ends at 34
        hands = [(33.12, 1.2, 'camera')]                             # the camera moves 33.12-34.32
        self.assertAlmostEqual(camera_clips.parked_until(clip, hands), 34.32)
        self.assertEqual(camera_clips.parked_glide(clip, hands), (34., 34.32))
        self.assertIsNone(camera_clips.parked_until(clip, [(30., 1., 'camera')]))   # over before it ended


class EditPathPage(unittest.TestCase):
    def test_the_path_is_on_the_stickers_own_page(self):
        import stickers
        from app import Window
        from engine import import_svg
        w = Window(); w.show(); w.resize(1400, 900)
        try:
            w.set_drawing(import_svg('samples/drawing.svg')); pump()
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); pump()
            w.scenes[1]['track'] = 1                                 # elements on tracks (exp.168)
            w.preview_scope.setCurrentIndex(1); pump()
            lay = w.timeline_layout()
            it = lay.items[1]
            s = stickers.new('Circle', it.start + it.length * .6, 3.); s.update(drawing='Hand: outline', x=.5, y=.4)
            w.overlays.append(s); w.__dict__.pop('_memo', None); w.refresh(); pump()
            w.mark_title_holds()
            W = 960; H = round(W * w.board_aspect())
            t = s['start'] + 1.5                                    # while it is being drawn
            self.assertNotEqual(int(s.get('_page', 0) or 0), 0)       # on element 2's page
            _, to = w.sticker_view_at(s, t, W, H)
            right, _ = w.sticker_screen_map(s, t, W, H)
            for point in ((0., 0.), (W * .5, H * .4)):
                a, b = to(*point), right(*point)
                self.assertAlmostEqual(a[0], b[0], delta=1); self.assertAlmostEqual(a[1], b[1], delta=1)
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
