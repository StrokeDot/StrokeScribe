"""exp.48 (the user: the old way was right; keep it): a Hand motion put over a drawing's way back
does not stop it or freeze the hand. The way back follows its own path until the Hand motion
starts; from then on it heads for where the Hand motion is (it follows the new path), and when
the way back is over the waiting hand goes on along the Hand motion from the same spot."""
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


class MotionOverWayBack(unittest.TestCase):
    def test_the_way_back_follows_the_hand_motion(self):
        import camera_clips, frame_render
        from app import Window
        from engine import import_svg
        from timeline_model import state_at
        w = Window(); w.show()
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(40): APP.processEvents()
            w.hand_rest.setChecked(True); w.preview_scope.setCurrentIndex(1)
            for _ in range(40): APP.processEvents()
            m = w.hand_marks()[0]
            back0, tail = m[0] + m[1] + m[2], m[3]
            c = camera_clips.new_clip('Hand motion', round(back0 + .3, 2))
            c.update(duration=1.5, back=False, path=[[.5, .2], [.2, .3]])
            w.cameras.append(c); w.refresh(); APP.processEvents()
            self.assertAlmostEqual(c['start'], round(back0 + .3, 2), places=2)      # stays where put
            lay = w.timeline_layout(); W, H = 960, 540

            def way(t):
                frame_render._HAND.glide = None
                w.timeline_frame(state_at(lay, t), W, H, t)
                return frame_render._HAND.glide
            corner = way(back0 + .05)['b']
            self.assertEqual([round(v) for v in way(c['start'] - .05)['b']], [round(v) for v in corner])  # its own path
            moving = [way(t)['b'] for t in (c['start'] + .15, c['start'] + .25)]
            self.assertGreater(math.dist(moving[0], corner), 2.)                    # it follows the motion
            self.assertGreater(math.dist(moving[1], moving[0]), 2.)
            for t in (c['start'] + .15, c['start'] + .25):                          # where the motion is
                spot, _ = w.hand_spot_at(W, H, t)
                b = way(t)['b']
                self.assertAlmostEqual(b[0], spot[0], delta=1.5); self.assertAlmostEqual(b[1], spot[1], delta=1.5)
            after = back0 + tail + .05                                              # then the waiting hand
            self.assertIsNone(way(after))
            self.assertIsNotNone(w.rest_hand_info(W, H, after))
            self.assertIsNone(w.scenes[0].get('_motion_cut'))                       # no freezing
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
