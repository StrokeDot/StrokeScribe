"""exp.64 (the user: a new camera position has its own corner; the sticker said "Rests in its
corner" but did not go there): a sticker hand that stops and waits goes back to where the waiting
hand is when it finishes (the corner of the camera then), like an element's hand; nothing pins
the hand at an old spot. Only a Free ending leaves the hand where it was put."""
import math
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


class StickerCorner(unittest.TestCase):
    def setUp(self):
        import stickers
        from app import Window
        from engine import import_svg
        self.w = w = Window(); w.show(); w.resize(1500, 950)
        w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.set_camera = lambda k=None: None
        w.add_camera_step(); pump()
        k = w.scene_index
        b = dict(w.scenes[k].get('board') or {}); b['view'] = [.3, .25, .45]      # a new camera: close, up left
        w.scenes[k]['board'] = b; w.__dict__.pop('_memo', None); w._scene_cache = {}
        w.preview_scope.setCurrentIndex(1); pump()
        w.hand_rest.setChecked(True); pump()                   # the hand waits in its corner (as the user has it)
        lay = w.timeline_layout()
        self.step_end = lay.items[k].start + lay.items[k].length
        first = lay.items[0]
        self.a = stickers.new('Arrow', first.start + first.length * .3, 2.)
        self.b = stickers.new('Circle', self.step_end + 1.5, 2.)
        for s, x in ((self.a, .3), (self.b, .6)):
            s.update(drawing='Hand: everything', x=x, y=.4)
            w.overlays.append(s)
        w.sync_titles_timeline(); w.refresh(); pump(30)
        w.sticker_homes()
        self.W = 960; self.H = round(960 * w.board_aspect())

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); pump()

    def corner_at(self, t):
        return self.w.hand_spot_at(self.W, self.H, t)[0]

    def park_with_a_hand_motion(self):
        """The user's timeline: a Hand motion leaves the hand up left, before the camera step."""
        import stickers
        w = self.w
        lay = w.timeline_layout(); k = w.scene_index
        move_start = next(m.start for m in lay.moves if m.k + 1 == k)
        clip = w.add_camera_clip('Hand motion', at=max(0., move_start - 2.2)); pump()
        clip.update(start=round(max(0., move_start - 2.2), 3), duration=1.5, back=False, path=[[.15, .2]])
        w.overlays.remove(self.a)                         # only the Hand motion parks the hand here
        w.__dict__.pop('_memo', None); w.refresh(); pump(20)
        w.sticker_homes()
        self.move_start = move_start
        return clip

    def test_a_new_camera_ends_the_parking_and_the_sticker_uses_the_corner(self):
        import stickers
        self.park_with_a_hand_motion()
        parked = self.corner_at(self.move_start - .05)          # parked by the Hand motion
        span = stickers.busy(self.b)
        corner = self.w.screen_corner(self.W, self.H)[0]
        waiting = self.corner_at(span[0] - .05)
        self.assertGreater(math.dist(parked, waiting), 40)       # it did not stay parked
        self.assertLess(math.dist(waiting, corner), 3)           # it is in its corner again
        home, back = self.b['_home_screen'], self.b['_back_screen']
        self.assertLess(math.dist((home[0] * self.W, home[1] * self.H), corner), 3)
        self.assertLess(math.dist((back[0] * self.W, back[1] * self.H), corner), 3)

    def test_it_glides_back_during_the_camera_move(self):
        self.park_with_a_hand_motion()
        lay = self.w.timeline_layout()
        m = next(m for m in lay.moves if m.k + 1 == self.w.scene_index)
        a, mid, b = (self.corner_at(m.start + m.length * f) for f in (0.01, .5, .99))
        self.assertGreater(math.dist(a, mid), 5)                 # moving, not jumping at one moment
        self.assertGreater(math.dist(mid, b), 5)

    def test_the_sticker_goes_back_to_where_the_hand_waits_then(self):
        import stickers
        span = stickers.busy(self.b)
        back = self.b['_back_screen']
        corner = self.corner_at(span[1] + .3)                     # the waiting hand once it is done
        self.assertLess(math.dist((back[0] * self.W, back[1] * self.H), corner), 3)
        end = self.b['_end_screen']                               # where its hand is really painted last
        self.assertLess(math.dist((end[0] * self.W, end[1] * self.H), corner), 6)

    def test_nothing_pins_the_hand_after_a_sticker(self):
        import stickers
        self.assertEqual(stickers.park_clips(self.w.overlays), [])

    def test_a_free_ending_still_stays_where_it_was_put(self):
        import stickers
        self.a.update(hand_flow='free', hand_end=[.5, .5]); self.w.sticker_homes()
        self.assertEqual(len(stickers.park_clips(self.w.overlays)), 1)


if __name__ == '__main__':
    unittest.main()
