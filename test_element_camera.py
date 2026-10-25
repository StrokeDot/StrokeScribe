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


class CameraClipTests(unittest.TestCase):
    """exp.119: camera clips on the Camera track."""

    def test_a_zoom_in_eases_then_holds_until_the_transition(self):
        import camera_clips as cc
        clip = cc.new_clip('Zoom in', start=2., duration=2.)
        moves = [(6., 7.)]
        self.assertIsNone(cc.framing_at([clip], 1., moves))                 # before it: no effect
        self.assertEqual(cc.framing_at([clip], 2., moves), (1., .5, .5))     # from where the camera is
        z, _, _ = cc.framing_at([clip], 3., moves)
        self.assertTrue(1. < z < 1.6)
        self.assertEqual(cc.framing_at([clip], 5., moves), (1.6, .5, .5))    # holds
        self.assertEqual(cc.framing_at([clip], 6.5, moves), (1.6, .5, .5))   # the move takes over from it
        self.assertIsNone(cc.framing_at([clip], 7.5, moves))                 # the next page: unzoomed

    def test_the_next_clip_starts_where_the_camera_is(self):
        import camera_clips as cc
        a = cc.new_clip('Zoom in', start=0., duration=1.)
        b = cc.new_clip('Zoom out', start=2., duration=1.)
        self.assertEqual(cc.framing_at([a, b], 2., ()), (1.6, .5, .5))       # no jump
        self.assertEqual(cc.framing_at([a, b], 3.5, ()), (1., .5, .5))

    def test_video_camera_combines_with_the_element_camera_and_pickles(self):
        import pickle
        import camera_clips as cc
        from camera import ZoomPath
        own = ZoomPath((2., .5, .5), (2., .5, .5), 0., 1., 4.)
        cam = cc.wrap(own, 10., [cc.new_clip('Zoom in', 10., 1.)], [], 4.)
        z, x, y = cam.at(1.)
        self.assertAlmostEqual(z, 3.2)
        self.assertEqual(pickle.loads(pickle.dumps(cam)).at(1.), (z, x, y))   # export workers
        options = dict(video_camera=(10., cc.signature([cc.new_clip('Zoom in', 10., 1.)]), ()))
        self.assertAlmostEqual(cc.from_options(None, options, 4.).at(1.)[0], 1.6)


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
        self.w.add_scene()
        self.w.preview_scope.setCurrentIndex(1); self.w.refresh()
        self.app.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()

    def test_camera_clip_on_the_camera_track(self):
        import json
        w = self.w
        w.position = 0.; w.refresh()
        clip = w.add_camera_clip('Zoom in')
        self.app.processEvents()
        self.assertEqual(w.stage_timeline.cam_clips, w.cameras)
        self.assertEqual(w.selected_camera, clip['id'])
        self.assertFalse(w.camera_clip_box.isHidden())
        # Chosen: the preview shows a frame where the camera goes; drag it.
        box = w.camera_box()
        self.assertIsNotNone(box)
        x, y, bw, bh = box
        self.assertTrue(w.drag_picture('start', x + bw / 2, y + bh / 2))
        w.drag_picture('move', -.05, 0.); w.drag_picture('done', 0., 0.)
        self.assertLess(clip['to'][1], .5)
        # Saved with the project; Ctrl+Z.
        data = json.loads(json.dumps(w.project_state()))
        self.assertEqual(data['cameras'][0]['id'], clip['id'])
        w.camera_clip_action(clip['id'], 'delete')
        self.assertEqual(w.cameras, [])
        w.undo(); self.app.processEvents()
        self.assertEqual(len(w.cameras), 1)
        # Not chosen: the whole video uses it (the camera of element 1 is wrapped).
        w.select_camera(None)
        camera = w.video_camera(0, None, 4.)
        self.assertIsNotNone(camera)

    def test_older_element_zoom_becomes_a_camera_clip(self):
        w = self.w
        data = w.project_state()
        data['settings'] = dict(data['settings'], camera='Zoom (start → end)', cam_end_zoom=200., cam_time=2.)
        w.apply_project(data); self.app.processEvents()
        self.assertEqual(len(w.cameras), 1)
        self.assertEqual(w.cameras[0]['to'][0], 2.)
        self.assertEqual(w.camera.currentText(), 'Off')


if __name__ == '__main__':
    unittest.main()
