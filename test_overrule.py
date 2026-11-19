"""exp.46 (the user: the Hand motion should overrule whatever is under; I could not join it to the
one before): a Hand motion, or a sticker's hand, may start during an element's way back: the way
back is dropped (the hand waits where the drawing finished) and it takes the hand from there.
The element keeps its length; drawings and ways in still come first."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class Overrule(unittest.TestCase):
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

    def test_a_hand_motion_in_a_way_back(self):
        import camera_clips, frame_render
        from timeline_model import state_at
        w = self.w
        lengths = [round(i.length, 3) for i in w.timeline_layout().items]
        m = w.hand_marks()[0]
        back = m[0] + m[1] + m[2]
        c = camera_clips.new_clip('Hand motion', round(back + .3, 2)); c['duration'] = .5
        w.cameras.append(c); w.refresh(); APP.processEvents()
        self.assertAlmostEqual(c['start'], round(back + .3, 2), places=2)           # it stays
        lay = w.timeline_layout()
        self.assertEqual([round(i.length, 3) for i in lay.items], lengths)           # nothing moves
        W, H = 960, 540
        finish = frame_render.last_tip(*w.preview_scene(0, W, H)[:2])
        for t in (back + .1, back + .25):                                           # it waits there
            frame_render._HAND.glide = None
            w.timeline_frame(state_at(lay, t), W, H, t)
            g = frame_render._HAND.glide
            self.assertAlmostEqual(g['a'][0], g['b'][0], delta=1); self.assertAlmostEqual(g['a'][1], g['b'][1], delta=1)
        t = c['start'] + .01
        self.assertIsNotNone(w.rest_hand_info(W, H, t))                              # the motion has it
        spot, _ = w.hand_spot_at(W, H, c['start'] + 1e-4)
        self.assertAlmostEqual(spot[0] / W, finish[0], delta=.01)                     # from the finish
        self.assertAlmostEqual(spot[1] / H, finish[1], delta=.01)

    def test_b_a_sticker_joins_the_drawing_before(self):
        import stickers
        w = self.w
        m = w.hand_marks()[0]
        back = m[0] + m[1] + m[2]
        w.add_sticker('Circle'); st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        st.update(drawing='Hand: everything', hand_in=.4, hand_out=.4, draw_seconds=.4)
        st['start'] = round(back + .2 + stickers.ways(st)[0], 2)
        w.refresh(); APP.processEvents()
        self.assertAlmostEqual(stickers.busy(st)[0], back + .2, delta=.02)           # it stays
        finish = __import__('frame_render').last_tip(*w.preview_scene(0, 960, 540)[:2])
        self.assertAlmostEqual(st['_home_screen'][0], finish[0], delta=.01)          # from the finish
        self.assertEqual(w.hand_source_at(stickers.busy(st)[0])[0], 'link')

    def test_c_a_drawing_still_comes_first(self):
        import camera_clips
        w = self.w
        m = w.hand_marks()[1]
        c = camera_clips.new_clip('Hand motion', round(m[0] + m[1] + 1., 2)); c['duration'] = .5   # mid-drawing
        w.cameras.append(c); w.refresh(); APP.processEvents()
        self.assertGreaterEqual(c['start'], m[0] + m[1] + m[2] - 1e-3)


if __name__ == '__main__':
    unittest.main()
