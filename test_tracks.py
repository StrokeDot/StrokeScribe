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

    def test_swapping_two_elements_keeps_the_rest_in_place(self):
        # exp.126: element 4 moved before element 3 (which has its own start): no collision.
        from timeline_model import layout, swapped_places
        lay = layout([2., 3., 2., 4.], [1., 1., 1., 0.], [None, None, 10., None])
        self.assertEqual(swapped_places(lay, 3, 2), {3: (10., 0), 2: (15., 0)})
        side = layout([4., 5.], [0., 0.], [None, 1.], [0, 1])          # side by side: swap places
        self.assertEqual(swapped_places(side, 0, 1), {1: (0., 0), 0: (1., 1)})


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

    def test_moving_an_element_earlier_does_not_make_it_collide(self):
        w = self.w
        w.scenes[0]['transition'] = 'Cut'
        w.add_scene()
        from engine import import_svg
        w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg')); w.duration.setValue(1.)
        w.refresh(); self.app.processEvents()
        lay = w.timeline_layout()
        w.place_element(1, lay.items[1].start + 2., 0)      # element 2 has a start of its own
        w.select_scene(2); self.app.processEvents()
        w.move_scene(-1); self.app.processEvents()
        lay = w.timeline_layout()
        ends = sorted((it.start, it.end) for it in lay.items if it.track == 0)
        for (a0, a1), (b0, b1) in zip(ends, ends[1:]):
            self.assertLessEqual(a1, b0 + 1e-3)                # one after the other on Track 1
        self.assertEqual(w.scene_index, 1)

    def test_export_animation_opens_the_export_panel(self):
        from studio_workspace import TABS
        w = self.w
        w.show_right_panel('source')
        w.right_panel_close.click(); self.app.processEvents()
        w.quick_export.click(); self.app.processEvents()
        self.assertEqual(w.inspector_tabs.currentIndex(), TABS['export'])
        self.assertTrue(w.inspector_tabs.isVisible())

    def test_add_element_button_but_not_on_this_page(self):
        self.assertTrue(self.w.scene_add.isVisible())
        self.assertFalse(self.w.scene_picture.isVisible())
        self.assertTrue(self.w.scene_edit.isVisible())

    def test_texts_follow_the_frame_shown_while_playing(self):
        w = self.w
        w.position = .503; w.playing = True
        try:
            index, count = w.frame_index(w.position)
            self.assertAlmostEqual(w.shown_seconds(), index / count * w._view['length'], places=3)
        finally:
            w.playing = False
        self.assertAlmostEqual(w.shown_seconds(), w.video_seconds())

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

    def test_texts_are_the_videos_own_clips(self):
        """exp.116: a text is not part of an element: it is a clip of the whole video, in its
        seconds, drawn on the screen over everything; it stays when elements are chosen."""
        import overlays
        w = self.w
        w.place_element(1, .5, 1)
        w.preview_scope.setCurrentIndex(1); self.app.processEvents()
        lay = w.timeline_layout()
        it = lay.items[1]
        w.position = (it.start + it.length * .5) / lay.total
        w.refresh(); self.app.processEvents()
        item = w.add_overlay(overlays.new_text())
        self.assertAlmostEqual(item['start'], round(w.position * lay.total, 2), places=1)
        self.assertEqual(w.preview_scope.currentIndex(), 1)
        w.refresh(); self.app.processEvents()
        self.assertIsNotNone(w.canvas.titles_frame)                         # on the screen
        # exp.114: asked while painting, the box never works out the timeline right there.
        from unittest import mock
        w._box_cache = None
        with mock.patch.object(type(w), 'timeline_layout', side_effect=AssertionError('work in paint')):
            w.overlay_box()
        for _ in range(5): self.app.processEvents()
        self.assertIsNotNone(w.overlay_box())
        x, y, bw, bh = w.compute_overlay_box()
        self.assertIs(w.overlay_at(x + bw / 2, y + bh / 2), item)
        before = item['x']
        self.assertTrue(w.drag_picture('start', x + bw / 2, y + bh / 2))
        w.drag_picture('move', .05, 0.); w.drag_picture('done', 0., 0.)
        self.assertAlmostEqual(item['x'], before + .05, places=3)
        w.undo(); self.app.processEvents()
        self.assertAlmostEqual(w.find_overlay(item['id'])['x'], before, places=3)   # Ctrl+Z
        # Another element chosen: the text is still there (it belongs to the video).
        w.select_scene(0); self.app.processEvents()
        self.assertEqual([o['id'] for o in w.overlays], [item['id']])
        self.assertEqual([o['id'] for o in w.stage_timeline.overlays], [item['id']])
        # Saved with the project, not inside an element.
        data = json.loads(json.dumps(w.project_state()))
        self.assertEqual([o['id'] for o in data['titles']], [item['id']])
        self.assertFalse(any((s.get('state') or {}).get('overlays') for s in data.get('scenes', [])))

    def test_text_tracks_and_choosing(self):
        """exp.117: texts sit on their own tracks above the elements (Text 1, Text 2…, each
        with a hide button); one thing is chosen at a time, Ctrl+click chooses more."""
        import overlays
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        w = self.w
        w.place_element(1, .5, 1)
        w.preview_scope.setCurrentIndex(1); w.refresh(); self.app.processEvents()
        a = w.add_overlay(overlays.new_text())
        b = w.add_overlay(overlays.new_text())
        w.refresh(); self.app.processEvents()
        tl = w.stage_timeline
        self.assertNotEqual(a['track'], b['track'])                       # same time: two tracks
        # exp.118: texts sit on the element tracks, above the elements shown at that time.
        top = max(it.track for it in w.timeline_layout().items)
        self.assertGreater(min(a['track'], b['track']), top)
        row = tl._track_rect(a['track'])
        self.assertTrue(row.contains(tl._overlay_rect(a).center()))
        self.assertGreater(tl.lanes(), max(a['track'], b['track']))
        # Plain click chooses one; Ctrl+click adds; a click on an element clears the texts.
        r = tl._overlay_rect(a)
        QTest.mouseClick(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(r.center().x()), int(r.center().y())))
        self.assertEqual({o['id'] for o in w.chosen_overlays()}, {a['id']})
        r = tl._overlay_rect(b)
        area = tl._tracks_area()
        if not area.contains(r.center()):                 # exp.131: scroll it into view first
            tl.vbar.setValue(0); tl.y_off = 0.; tl.update(); self.app.processEvents()
            r = tl._overlay_rect(b)
        QTest.mouseClick(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                         QPoint(int(r.center().x()), int(r.center().y())))
        self.assertEqual({o['id'] for o in w.chosen_overlays()}, {a['id'], b['id']})
        block = tl._item_rect(tl.items[0])
        QTest.mouseClick(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(block.center().x()), int(block.center().y())))
        self.app.processEvents()
        self.assertEqual(w.chosen_overlays(), [])
        # Both chosen and deleted at once (one undo step).
        w.select_overlay(a['id']); w.toggle_overlay(b['id'])
        w.overlay_action(a['id'], 'delete')
        self.assertEqual(w.overlays, [])
        w.undo(); self.app.processEvents()
        self.assertEqual(len(w.overlays), 2)
        # Its track hidden (the track's own hide button): not drawn, not exported.
        t = w.overlays[0]['track']
        w.toggle_track(t, 'hide')
        self.assertNotIn(t, {int(o['track']) for o in w.visible_titles()})

    def test_a_text_under_an_element_of_a_higher_track(self):
        """exp.118: a text is ordered with the elements by its track."""
        import overlays
        w = self.w
        w.place_element(1, 0., 2)                       # element 2 on Track 3, from 0 s
        w.preview_scope.setCurrentIndex(1); w.refresh(); self.app.processEvents()
        w.position = 0.; w.refresh()
        text = w.add_overlay(overlays.new_text())
        w.move_overlay_clip(text['id'], 0., 2., 1)     # on Track 2: under element 2
        on_top, under = w.titles_split(.5)
        self.assertEqual([o['id'] for o in under], [text['id']])
        self.assertEqual(on_top, [])
        w.move_overlay_clip(text['id'], 0., 2., 3)     # Track 4: over it
        on_top, under = w.titles_split(.5)
        self.assertEqual([o['id'] for o in on_top], [text['id']])

    def test_opening_a_project_shows_the_whole_video_from_the_start(self):
        import projects
        w = self.w
        w.preview_scope.setCurrentIndex(0); w.position = .7
        saved = projects.save(Path(self.tmp.name) / 'p', w.project_state())
        from unittest import mock
        with mock.patch.object(type(w), 'confirm_leave_project', return_value=True):
            self.assertTrue(w.open_project(str(saved)))
        self.assertEqual(w.preview_scope.currentIndex(), 1)
        self.assertEqual(w.position, 0.)

    def test_a_text_lives_on_its_page_and_stays(self):
        """exp.123: like the drawings, a text with no way out stays (to the end of the video)
        on the page the camera showed when it started; the camera moves away from it."""
        import overlays
        w = self.w
        w.set_camera_move(0, 'Camera move', 1.2)
        w.place_element(1, 6., 0)
        w.preview_scope.setCurrentIndex(1); w.position = 0.; w.refresh(); self.app.processEvents()
        text = w.add_overlay(overlays.new_text())
        w.move_overlay_clip(text['id'], 0., 1., text['track'])
        text['effect_out'] = 'None'
        w.visible_titles()
        self.assertEqual(text['_page'], 0)
        end = w.video_length()
        self.assertAlmostEqual(text['_until'], end, places=2)
        self.assertIsNotNone(overlays.state_at(text, end - .1))                  # still there
        # On element 2's page the text's page is out of view.
        W, H = 320, 180
        x, y, rw, rh = w.text_rect(text, end - .1, W, H)
        self.assertTrue(x + rw <= 1 or x >= W - 1 or y + rh <= 1 or y >= H - 1)
        x, y, rw, rh = w.text_rect(text, .5, W, H)
        self.assertAlmostEqual(rw, W, delta=2)                                 # its own page: in view
        text['effect_out'] = 'Fade'
        self.assertIsNone(overlays.state_at(text, end - .1))                    # its way out: as set
        self.assertNotIn('_until', json.loads(json.dumps(w.project_state()))['titles'][0])

    def test_ctrl_wheel_steps_back_in_the_whole_video(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        w = self.w
        w.preview_scope.setCurrentIndex(1); w.refresh(); self.app.processEvents()
        before = w.canvas.frame
        with mock.patch.object(QApplication, 'keyboardModifiers', return_value=Qt.KeyboardModifier.ControlModifier):
            self.assertTrue(w.preview_wheel(-3, 10, 10))
        self.assertGreater(w.preview_zoom_out, 1.)
        self.assertTrue(w.zoomed_out())
        self.assertIsNotNone(w.canvas.frame)
        x, y, bw, bh = w.overlay_box()                     # the camera's frame, dashed
        self.assertLess(bw, w.canvas.frame.width())
        # exp.122: drag to look around; the frame moves with it; Camera view puts it back.
        self.assertFalse(w.preview_reset_view.isHidden())
        self.assertTrue(w.drag_picture('start', 10, 10))
        w.drag_picture('move', .1, 0.); w.drag_picture('done', 0., 0.)
        self.assertGreater(w.overlay_box()[0], x)            # the picture follows the mouse
        w.preview_frame_toggle.setChecked(False)
        self.assertIsNone(w.overlay_box())
        w.preview_frame_toggle.setChecked(True)
        w.reset_preview_view()
        self.assertFalse(w.zoomed_out())
        self.assertTrue(w.preview_reset_view.isHidden())
        with mock.patch.object(QApplication, 'keyboardModifiers', return_value=Qt.KeyboardModifier.ControlModifier):
            w.preview_wheel(-3, 10, 10)
        w.preview_scope.setCurrentIndex(0); self.app.processEvents()
        self.assertFalse(w.zoomed_out())

    def test_older_texts_move_to_the_video(self):
        """Projects from before exp.116: an element's texts become the video's own clips at
        the same moment."""
        import overlays
        w = self.w
        data = json.loads(json.dumps(w.project_state()))
        lay = w.timeline_layout()
        text = dict(overlays.new_text(), start=.5, duration=1.)
        if data['scenes'][1].get('state'):
            data['scenes'][1]['state']['overlays'] = [text]
        else:
            data['overlays'] = [text]                       # element 2 is the edited one
        data.pop('titles', None)
        w.apply_project(data); self.app.processEvents()
        self.assertEqual(len(w.overlays), 1)
        self.assertAlmostEqual(w.overlays[0]['start'], round(.5 + w.timeline_layout().items[1].start, 2), places=2)

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
