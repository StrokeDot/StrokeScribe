"""exp.51 (the user: after the sticker's hand, the hand went back to the middle and the next Hand
motion did not start from the last point): the waiting hand stays exactly where a sticker's hand
really ended (the point its hand is painted at, through its own page), and the next Hand motion
starts there; whatever the sticker's ending, also with two pages on the board."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class AfterSticker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg'))
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(40): APP.processEvents()
        w.hand_rest.setChecked(True); w.preview_scope.setCurrentIndex(1)
        for _ in range(40): APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def tearDown(self):
        w = self.w
        w.cameras[:] = [c for c in w.cameras if c.get('kind') != 'Hand motion']
        w.overlays[:] = [o for o in w.overlays if o.get('kind') != 'sticker']
        w.refresh(); APP.processEvents()

    def painted_end(self, st):
        """Where the sticker's hand is painted as it finishes (its Edit path's mapping)."""
        import stickers
        W = 960; H = round(W * self.w.board_aspect())
        span = stickers.busy(st)
        _, to_screen = self.w.sticker_view_at(st, span[1] - 1e-3, W, H)
        tip = stickers.hand_tip(st, span[1] - 1e-3, W, H, stickers.home_on_frame(st, W, H, W, None, to_screen),
                                stickers.home_on_frame(st, W, H, W, None, to_screen, '_back_screen'))   # exp.64
        return to_screen(*tip), (W, H)

    def check(self, st, motion):
        import stickers
        w = self.w
        (ex, ey), (W, H) = self.painted_end(st)
        spot, _ = w.hand_spot_at(W, H, stickers.busy(st)[1] + .3)
        self.assertAlmostEqual(spot[0], ex, delta=2); self.assertAlmostEqual(spot[1], ey, delta=2)
        view = w.hand_motion_view(motion)
        self.assertAlmostEqual(view['begin'][0], ex, delta=2); self.assertAlmostEqual(view['begin'][1], ey, delta=2)

    def setup(self, **sticker):
        import camera_clips
        w = self.w
        end = max(b for a, b in w.hand_busy_spans())
        a = camera_clips.new_clip('Hand motion', round(end + .2, 2))
        a.update(duration=1., back=False, path=[[.5, .5], [.45, .6]])          # leaves the hand in the middle
        w.cameras.append(a)
        w.add_sticker('Line'); st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        st.update(drawing='Hand: everything', hand_in=.6, hand_out=.6, draw_seconds=.6, **sticker)
        st['start'] = round(end + 2.2, 2)
        b = camera_clips.new_clip('Hand motion', round(end + 5., 2)); b.update(duration=1., back=False)
        w.cameras.append(b); w.refresh(); APP.processEvents()
        return st, b

    def test_a_free_ending(self):
        st, b = self.setup(hand_flow='free', hand_end=[.85, .85])
        self.check(st, b)

    def test_b_stop_and_wait(self):
        st, b = self.setup()
        self.check(st, b)

    def test_c_even_when_it_comes_from_its_corner(self):
        st, b = self.setup()
        w = self.w
        real = w.hand_spot_at
        w.hand_spot_at = lambda W, H, t: None if abs(t - (__import__('stickers').busy(st)[0] + 1e-4)) < 1e-6 else real(W, H, t)
        try:
            w.refresh(); APP.processEvents()
            # exp.64: no waiting hand known: the corner of the screen (Hand panel → Corner)
            from frame_render import REST_CORNERS
            fx, fy = REST_CORNERS.get(w.hand_rest_corner.currentText(), REST_CORNERS['Bottom right'])
            self.assertAlmostEqual(st['_home_screen'][0], fx, places=3)
            self.assertAlmostEqual(st['_home_screen'][1], fy, places=3)
        finally:
            w.hand_spot_at = real
        self.check(st, b)


if __name__ == '__main__':
    unittest.main()
