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

    def test_track_headers_mute_and_hide(self):
        """exp.105: each track has its name, a mute and a hide button on the left."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from timeline_model import state_at
        w = self.w
        w.place_element(1, 0., 1)
        tl = w.stage_timeline
        self.assertGreaterEqual(tl.LEFT, tl.HEADER)                    # room for the headers
        got = []
        tl.track_toggled.connect(lambda t, which: got.append((t, which)))
        r = tl._icon_rect(1, 'hide')
        QTest.mouseClick(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(r.center().x()), int(r.center().y())))
        self.assertEqual(got, [(1, 'hide')])
        self.assertEqual(w.hidden_elements(), {1})                     # the click hid Track 2
        self.assertTrue(w.stage_timeline.flag(1, 'hide'))
        state = state_at(w.timeline_layout(), .5)
        self.assertIn(1, [k for k, _ in state.active])
        shown = w.timeline_frame(state, 320, 180)
        w.toggle_track(1, 'hide')
        self.assertEqual(w.hidden_elements(), set())
        self.assertNotEqual(shown, w.timeline_frame(state, 320, 180))  # it is drawn again
        w.toggle_track(0, 'mute')
        data = json.loads(json.dumps(w.project_state()))
        self.assertEqual(data['track_flags'], {'0': {'muted': True}})

    def test_choosing_an_element_puts_the_playhead_on_it(self):
        """exp.110: with tracks the playhead used the sum of all elements as the video's
        length, so choosing an element showed another one."""
        w = self.w
        w.place_element(1, 0., 1)
        w.preview_scope.setCurrentIndex(1); self.app.processEvents()
        w.select_scene(0); w.select_scene(1); self.app.processEvents()
        lay = w.timeline_layout()
        it = lay.items[1]
        self.assertAlmostEqual(w.position * lay.total, it.start + it.length * .999, delta=.05)

    def test_plus_card_after_the_last_element(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        w = self.w
        self.assertEqual(w.scene_list.count(), len(w.scenes) + 1)
        self.assertEqual(w.scene_list.item(len(w.scenes)).data(Qt.ItemDataRole.UserRole), 'add')
        w.select_scene(0); self.app.processEvents()
        with mock.patch.object(type(w), 'add_element_menu') as menu:
            w.strip_plus_clicked()
        self.assertEqual(w.scene_index, len(w.scenes) - 1)
        self.assertTrue(menu.called)

    def test_camera_moves_can_be_clicked_and_changed(self):
        """exp.111: a click on a camera move on the timeline changes how and how long it moves."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        w = self.w
        w.set_camera_move(0, 'Camera move', 1.2)  # setUp joins the two on the same page
        w.place_element(1, 5., 0)                # its own start: the timeline shows the camera row
        w.preview_scope.setCurrentIndex(1); w.refresh(); self.app.processEvents()
        tl = w.stage_timeline
        self.assertTrue(tl.moves)
        k, _, start, secs = tl.moves[0]
        got = []
        tl.move_clicked.connect(got.append)
        r = tl._move_chip(start, secs)
        from unittest import mock
        with mock.patch.object(type(w), 'edit_camera_move'):           # no dialog in the test
            QTest.mouseClick(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(int(r.center().x()), int(r.center().y())))
        self.assertEqual(got, [k])
        w.set_camera_move(k, 'Pan up', 2.5)
        self.assertEqual((w.scenes[k]['transition'], w.scenes[k]['transition_seconds']), ('Pan up', 2.5))
        w.undo(); self.app.processEvents()
        self.assertEqual(w.scenes[k]['transition'], 'Camera move')

    def test_animation_sections_in_working_order(self):
        w = self.w
        layout = w.section_drawing.parentWidget().layout()
        order = [layout.indexOf(x) for x in (w.section_drawing, w.section_painting, w.lines_box,
                                              w.section_move_in, w.section_out)]
        self.assertEqual(order, sorted(order))

    def test_number_boxes_beside_sliders_are_small(self):
        w = self.w
        self.assertLess(w.picture_x.width(), 90)
        self.assertGreaterEqual(w.picture_x.width(), 50)

    def test_restore_original(self):
        w = self.w
        w.picture_x.setValue(30); w.artwork_size.setValue(150)
        w.restore_original_look()
        self.assertEqual((w.picture_x.value(), w.artwork_size.value()), (0., 100.))

    def test_texts_in_the_whole_video(self):
        """exp.113: a text stays in Whole video: it can be chosen and dragged there, and the
        other elements' texts show on the timeline (a click goes to them)."""
        import overlays
        w = self.w
        w.place_element(1, .5, 1)
        w.preview_scope.setCurrentIndex(1); self.app.processEvents()
        lay = w.timeline_layout()
        it = lay.items[1]
        w.position = (it.start + it.length * .5) / lay.total
        w.refresh(); self.app.processEvents()
        item = w.add_overlay(overlays.new_text())
        self.app.processEvents()
        self.assertEqual(w.preview_scope.currentIndex(), 1)                 # stays on the whole video
        box = w.overlay_box()
        self.assertIsNotNone(box)
        x, y, bw, bh = box
        self.assertIs(w.overlay_at(x + bw / 2, y + bh / 2), item)
        before = item['x']
        self.assertTrue(w.drag_picture('start', x + bw / 2, y + bh / 2))
        w.drag_picture('move', .05, 0.); w.drag_picture('done', 0., 0.)
        self.assertGreater(item['x'], before)
        # Element 1 chosen: element 2's text shows on the timeline, and a click goes to it.
        w.select_scene(0); self.app.processEvents()
        others = w.stage_timeline.other_overlays
        self.assertEqual([(k, o['id']) for k, o in others], [(1, item['id'])])
        w.go_to_overlay(1, item['id']); self.app.processEvents()
        self.assertEqual((w.scene_index, w.selected_overlay), (1, item['id']))
        self.assertEqual(w.preview_scope.currentIndex(), 1)

    def test_element_hide_and_mute_on_its_own(self):
        """exp.106: hide / mute one element (right-click), not only a whole track."""
        w = self.w
        w.toggle_element_flag(0, 'hide')
        self.assertEqual(w.hidden_elements(), {0})
        self.assertFalse(w.timeline_layout().sequential)               # drawn without it
        self.assertTrue(w.stage_timeline.element_flags[0]['hidden'])
        w.toggle_element_flag(0, 'mute')
        data = json.loads(json.dumps(w.project_state()))
        from scenes import scenes_from_project
        back = scenes_from_project(data)
        self.assertTrue(back[0]['hidden']); self.assertTrue(back[0]['muted'])
        w.toggle_element_flag(0, 'hide')
        self.assertEqual(w.hidden_elements(), set())

    def test_zoom_and_scroll(self):
        """exp.106: zoom the timeline in time (scroll bar along the bottom); many tracks
        scroll up and down."""
        w = self.w
        tl = w.stage_timeline
        total = tl.total()
        tl.set_zoom(4.)
        self.app.processEvents()
        self.assertTrue(tl.hbar.isVisible())
        self.assertAlmostEqual(tl._span(), total / 4, places=3)              # a quarter of the video shown
        self.assertAlmostEqual(tl._x(total) - tl._x(0), tl._width() * 4, delta=2)
        tl.set_zoom(1.)
        self.assertFalse(tl.hbar.isVisible())
        for k in range(len(w.scenes)):
            w.place_element(k, 0., 4 + k)                              # tracks 5 and 6: tall
        tl.resize(tl.width(), 180); self.app.processEvents()
        self.assertTrue(tl.vbar.isVisible())
        bottom = tl._track_rect(0)
        self.assertLessEqual(bottom.bottom(), tl.height())               # Track 1 can be seen

    def test_pictures_of_every_element_after_opening(self):
        """exp.106: the element cards show their pictures as soon as the project opens."""
        import time
        from app import Window
        from projects import save
        w = self.w
        folder = Path(tempfile.mkdtemp())                              # not the frames folder
        path = folder / 'two.strokescribe'
        save(path, w.project_state())
        other = Window(); other.show()
        problems = []
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        try:
            with mock.patch.object(QMessageBox, 'warning', side_effect=lambda *a, **k: problems.append(a[2])):
                opened = other.open_project(str(path))
            self.assertEqual(problems, [])
            self.assertTrue(opened)
            deadline = time.time() + 20
            while time.time() < deadline and any(s.get('thumb') is None for s in other.scenes):
                self.app.processEvents(); time.sleep(.05)
            self.assertTrue(all(s.get('thumb') is not None and not s['thumb'].isNull() for s in other.scenes))
        finally:
            other.playing = False; other.close()

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
