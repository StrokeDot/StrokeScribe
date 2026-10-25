"""exp.115: the element's own camera (start framing → end framing) and the camera moves.

The moves between elements have the last word: a zoom still running when a move starts
goes on, the move takes over from it gradually and lands on the next element's first
framing.
"""
import math
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


class ZoomPathTests(unittest.TestCase):
    def test_start_hold_move_end(self):
        from camera import ZoomPath
        path = ZoomPath((1., .5, .5), (2., .3, .7), begin=1., length=2., total=4.)
        self.assertEqual(path.at_seconds(0.), (1., .5, .5))           # holds the start framing
        z, x, y = path.at_seconds(2.)                                  # halfway: natural zoom
        self.assertAlmostEqual(z, math.sqrt(2.), places=6)
        self.assertAlmostEqual(x, .4, places=6)
        self.assertEqual(path.at_seconds(3.5), (2., .3, .7))          # holds the end framing
        self.assertEqual(path.at(1.), (2., .3, .7))
        self.assertFalse(path.runs_past_end())

    def test_a_zoom_longer_than_the_element_goes_on(self):
        from camera import ZoomPath, after_end
        path = ZoomPath((1., .5, .5), (3., .5, .5), begin=0., length=6., total=4.)
        self.assertTrue(path.runs_past_end())
        self.assertLess(path.at(1.)[0], 3.)
        self.assertGreater(after_end(path, 1.)[0], path.at(1.)[0])   # still zooming after the end

    def test_plan_from_settings(self):
        from camera import zoom_path
        self.assertIsNone(zoom_path((100, 50, 50, 100, 50, 50, 0, 1.2), 4.))   # nothing to do
        path = zoom_path((100, 50, 50, 200, 25, 75, 0, 1.2), 4.)
        self.assertEqual(path.at(1.), (2., .25, .75))


class MoveTakesOverTests(unittest.TestCase):
    def test_the_move_starts_where_the_zoom_is_and_lands_on_the_next_framing(self):
        import board
        from camera import ZoomPath
        A = 9 / 16
        frames = [(0., 0., 1.), (2., 0., 1.)]
        leaving = ZoomPath((1., .5, .5), (2., .5, .5), begin=0., length=8., total=4.)   # still zooming
        arriving = ZoomPath((1.5, .25, .5), (1.5, .25, .5), begin=0., length=1., total=4.)
        start = board.join_view(frames, 0, 'Camera move', 0., A, 1.2, leaving=leaving, arriving=arriving)
        self.assertAlmostEqual(start[2], board.sub_view(frames[0], *leaving.at(1.), A)[2])  # no jump
        end = board.join_view(frames, 0, 'Camera move', 1., A, 1.2, leaving=leaving, arriving=arriving)
        expected = board.sub_view(frames[1], *arriving.at(0.), A)
        for a, b in zip(end, expected):
            self.assertAlmostEqual(a, b)
        # Without element cameras: as before.
        for a, b in zip(board.join_view(frames, 0, 'Camera move', 1., A, 1.2), frames[1]):
            self.assertAlmostEqual(a, b)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        from engine import import_svg
        self.w = Window(); self.w.show()
        self.w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        self.app.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()

    def test_zoom_camera_settings_reach_the_frames(self):
        from camera import ZOOM_MODE, ZoomPath
        w = self.w
        self.assertTrue(w.camera_zoom_box.isHidden())
        w.camera.setCurrentText(ZOOM_MODE)
        self.assertFalse(w.camera_zoom_box.isHidden())
        w.cam_end_zoom.setValue(200); w.cam_end_x.setValue(30); w.cam_time.setValue(2.)
        options = w.options()
        self.assertEqual(options['cam_plan'][3:5], (200., 30.))
        self.assertEqual(options['camera_zoom'], 2.)
        self.assertIsInstance(w.preview_camera(options), ZoomPath)
        w.refresh(); self.app.processEvents()

    def test_camera_shows_on_the_timeline_and_new_elements_start_without_one(self):
        from camera import ZOOM_MODE
        w = self.w
        w.camera.setCurrentText(ZOOM_MODE)
        w.add_scene()
        w.camera.setCurrentText('Off')
        w.preview_scope.setCurrentIndex(1); w.refresh(); self.app.processEvents()
        marks = w.element_camera_marks()
        self.assertEqual([m[0] for m in marks], [0])
        self.assertTrue(w.new_element('file', path=str(HERE / 'samples' / 'drawing.svg')))
        self.assertEqual(w.camera.currentText(), 'Off')


if __name__ == '__main__':
    unittest.main()
