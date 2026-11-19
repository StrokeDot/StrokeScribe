"""exp.38 (the user): At the corner: Free ending: the way back ends where you put it (Edit path:
drag the red dot); the hand stays there and the next hand starts there."""
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class Options(unittest.TestCase):
    def test_a_free_ending_reaches_the_options_and_not_a_link(self):
        from scenes import apply_glide
        o = apply_glide(dict(hand_travel=1.), dict(hand_flow='free', hand_end=[.2, .3]))
        self.assertEqual(o.get('_free_end'), (.2, .3))
        self.assertFalse(o.get('hand_link_out'))
        self.assertNotIn('hand_flow', o)                   # not a "without stopping" way
        o = apply_glide(dict(hand_travel=1.), dict(hand_flow='free'))       # no spot put yet: as usual
        self.assertNotIn('_free_end', o)
        o = apply_glide(dict(hand_travel=1.), dict(hand_link=True, hand_flow='free', hand_end=[.2, .3]))
        self.assertTrue(o.get('hand_link_out')); self.assertNotIn('_free_end', o)   # Stays where it finished wins


class InTheWindow(unittest.TestCase):
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

    def test_the_next_hand_starts_where_it_was_put(self):
        w = self.w
        w.scenes[0]['hand_flow'] = 'free'; w.scenes[0]['hand_end'] = [.15, .25]
        w.board_frames = lambda: [(0., 0., 1.), (0., 0., 1.)]          # both on one page
        w._scene_cache = {}; w.__dict__.pop('_memo', None)
        els = w.timeline_elements(960, 540)
        if not els[0]['options'].get('hand_travel'):
            self.skipTest('no travelling hand in this setup')
        self.assertEqual(els[0]['options'].get('_free_end'), (.15, .25))
        self.assertEqual(tuple(els[1]['options'].get('_from_tip') or ()), (.15, .25))   # the window's own joins

    def test_z_a_hand_motion_goes_at_the_playhead(self):
        w = self.w
        w.board_frames = type(w).board_frames.__get__(w)
        total = w.video_length()
        w.position = 1.; w.refresh(); APP.processEvents()            # at the very end: it ends there
        clip = w.add_camera_clip('Hand motion')
        self.assertAlmostEqual(clip['start'] + clip['duration'], total, delta=.02)
        w.cameras.remove(clip)
        w.position = .25; w.refresh(); APP.processEvents()           # anywhere else: right there
        clip = w.add_camera_clip('Hand motion')
        self.assertAlmostEqual(clip['start'], w.video_seconds(), delta=.02)
        w.cameras.remove(clip)
        self.assertLess(len(w.add_hand_motion_button.toolTip()), 70)    # short

class EditPath(unittest.TestCase):
    def test_the_red_dot_can_be_dragged_and_the_keyframes_stay(self):
        from glide_path_dialog import PathCanvas
        frame = QImage(400, 225, QImage.Format.Format_ARGB32); frame.fill(QColor('white'))
        c = PathCanvas(frame, (50., 50.), (300., 150.), [(.5, .2)])
        c.resize(800, 520); c.movable_end = True
        before = c.points()[1]
        start = c.to_widget(c.b); end = c.to_widget((350., 60.))

        def ev(kind, p, b):
            return QMouseEvent(kind, p, p, Qt.MouseButton.LeftButton, b, Qt.KeyboardModifier.NoModifier)
        c.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton))
        c.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton))
        c.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton))
        self.assertAlmostEqual(c.b[0], 350., delta=1); self.assertAlmostEqual(c.b[1], 60., delta=1)
        after = c.points()[1]
        self.assertAlmostEqual(after[0], before[0], delta=.5); self.assertAlmostEqual(after[1], before[1], delta=.5)
        c.movable_end = False                                   # not a free ending: it stays put
        c.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, c.to_widget(c.b), Qt.MouseButton.LeftButton))
        self.assertNotEqual(c.drag, 'end')


if __name__ == '__main__':
    unittest.main()
