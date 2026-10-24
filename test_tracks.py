"""exp.104: elements on tracks in the whole video (timeline_model / timeline_render)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


class ModelTests(unittest.TestCase):
    def test_classic_video_is_unchanged(self):
        from timeline_model import layout, state_at
        lay = layout([4., 5., 3.], [1.2, 0., 0.])
        self.assertTrue(lay.sequential)
        self.assertEqual([(it.start, it.end) for it in lay.items], [(0., 4.), (5.2, 10.2), (10.2, 13.2)])
        self.assertAlmostEqual(lay.total, 13.2)
        self.assertEqual(state_at(lay, 4.5).kind, 'move')                  # the camera move after element 1
        s = state_at(lay, 8.)
        self.assertEqual((s.kind, s.current, [k for k, _ in s.active], s.finished), ('page', 1, [1], [0]))

    def test_overlap_on_two_tracks(self):
        from timeline_model import describe, interval_at, layout, state_at
        lay = layout([4., 5., 3.], [0., 0., 0.], [None, 1., None], [0, 1, 0])
        self.assertFalse(lay.sequential)
        self.assertEqual([(it.start, it.track) for it in lay.items], [(0., 0), (1., 1), (6., 0)])
        s = state_at(lay, 2.)
        self.assertEqual([k for k, _ in s.active], [0, 1])               # both drawn, Track 1 first
        self.assertEqual(s.top, 1)                                        # the top one shows its hand
        self.assertAlmostEqual(dict(s.active)[0], .5)
        self.assertEqual(interval_at(lay, 2.), (1., 4.))
        a = describe(lay, state_at(lay, 1.), 1.)
        self.assertEqual(a, describe(lay, state_at(lay, 3.9), 1.))        # one stretch, one description
        self.assertEqual(state_at(lay, 7.).finished, [0, 1])
        self.assertAlmostEqual(lay.total, 9.)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['STROKESCRIBE_PREVIEW_CACHE'] = self.tmp.name
        from app import Window
        from engine import import_svg
        self.w = Window(); self.w.show()
        w = self.w
        w.duration.setValue(1.)
        w.add_scene()
        w.set_drawing(import_svg(HERE / 'samples' / 'arthur-headset-traced.svg'))
        w.duration.setValue(1.)
        w.scene_transition.setCurrentText('Same page')
        w.scenes[0]['transition'] = 'Same page'
        w.preview_scope.setCurrentIndex(1)
        w.refresh(); self.app.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()
        os.environ.pop('STROKESCRIBE_PREVIEW_CACHE', None)
        self.tmp.cleanup()

    def test_drag_an_element_onto_track_2_at_the_same_time(self):
        w = self.w
        before = w.timeline_layout().total
        w.place_element(1, 0., 1)                      # element 2 starts with element 1, on Track 2
        lay = w.timeline_layout()
        self.assertFalse(lay.sequential)
        self.assertEqual((lay.items[1].start, lay.items[1].track), (0., 1))
        self.assertLess(lay.total, before)             # they overlap: the video is shorter
        self.assertAlmostEqual(w.timeline_length(), lay.total)
        tl = w.stage_timeline
        self.assertEqual(tl.lanes(), 3)                # Track 1, Track 2, and an empty one on top
        self.assertEqual([i[4] for i in tl.items], [0, 1])
        for value in (100, 500, 900):
            w.slider.setValue(value)
            self.assertFalse(w.canvas.frame.isNull())
        # Pre-render works by stretches of time; every frame gets ready.
        for _ in range(w.ready_frames()[1] + 10):
            w.prerender_step()
        ready, total = w.ready_frames()
        self.assertEqual(ready, total)
        # Undo puts it back after element 1, and the menu does too.
        w.undo(); self.app.processEvents()
        self.assertTrue(w.timeline_layout().sequential)
        w.place_element(1, 0., 1)
        w.reset_element_time(1)
        self.assertTrue(w.timeline_layout().sequential)

    def test_two_elements_drawn_at_once_both_show(self):
        import numpy as np
        from PySide6.QtGui import QImage
        w = self.w
        w.place_element(1, 0., 1)
        lay = w.timeline_layout()
        from timeline_model import state_at
        state = state_at(lay, .6)
        self.assertEqual(sorted(k for k, _ in state.active), [0, 1])
        frame = w.timeline_frame(state, 480, 270).convertToFormat(QImage.Format.Format_RGBA8888)
        a = np.frombuffer(frame.constBits(), np.uint8, frame.sizeInBytes()).reshape(270, -1)[:, :480 * 4]
        self.assertGreater(int((a.reshape(270, 480, 4)[..., 3] > 0).sum()), 0)

    def test_tracks_are_saved_with_the_project(self):
        from scenes import scenes_from_project
        w = self.w
        w.place_element(1, .4, 2)
        data = json.loads(json.dumps(w.project_state()))
        back = scenes_from_project(data)
        self.assertEqual((back[1]['start'], back[1]['track']), (.4, 2))
        self.assertIsNone(back[0]['start'])

    def test_dragging_a_block_on_the_timeline(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        w = self.w
        tl = w.stage_timeline
        got = []
        tl.element_placed.connect(lambda k, start, track: got.append((k, start, track)))
        other = next(i for i in tl.items if i[0] != tl.current_scene)
        r = tl._item_rect(other)
        start = QPoint(int(r.center().x()), int(r.center().y()))
        up = tl._track_rect(other[4] + 1)
        QTest.mousePress(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        for x, y in ((start.x() + 10, start.y()), (start.x() + 30, int(up.center().y()))):
            move = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y), Qt.MouseButton.NoButton,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(tl, move)
        QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(start.x() + 30, int(up.center().y())))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], other[0])
        self.assertEqual(got[0][2], other[4] + 1)                      # onto the next track

    @unittest.skipUnless(shutil.which('ffmpeg'), 'needs FFmpeg')
    def test_export_with_tracks(self):
        import scenes
        w = self.w
        w.place_element(1, .2, 1)
        w.fps.setValue(6); w.mp4.setChecked(True); w.webm.setChecked(False); w.mov.setChecked(False)
        w.sound_on.setChecked(False)
        w._leave_scene()
        scene_list = [dict(state=s['state'], transition=s['transition'], transition_seconds=s['transition_seconds'],
                           board=s.get('board'), start=s.get('start'), track=s.get('track') or 0) for s in w.scenes]
        w.scenes[w.scene_index]['state'] = None
        out = Path(self.tmp.name) / 'video'
        scenes.export_scenes(scene_list, out, w.settings_state(), w.hand)
        info = json.loads((out / 'sequence.json').read_text())
        self.assertEqual([s['track'] for s in info['scenes']], [0, 1])
        self.assertEqual(info['scenes'][1]['first_frame'], 1)             # 0.2 s at 6 fps
        self.assertTrue(list(out.glob('*.mp4')))


if __name__ == '__main__':
    unittest.main()
