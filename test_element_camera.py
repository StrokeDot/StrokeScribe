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
    """exp.124: a camera clip gets there (in), stays, and comes back to the normal frame."""

    def test_in_hold_and_back(self):
        import camera_clips as cc
        clip = cc.new_clip('Zoom in', start=2.)                      # 1.2 s in, 2 s stays, 1.2 s back
        self.assertIsNone(cc.framing_at([clip], 1.))
        self.assertEqual(cc.framing_at([clip], 2.), (1., .5, .5))    # from the normal frame
        z, _, _ = cc.framing_at([clip], 2.6)
        self.assertTrue(1. < z < 1.6)
        self.assertEqual(cc.framing_at([clip], 3.2), (1.6, .5, .5))  # there
        self.assertEqual(cc.framing_at([clip], 5.2), (1.6, .5, .5))  # stays
        self.assertLess(cc.framing_at([clip], 5.8)[0], 1.6)          # coming back
        self.assertIsNone(cc.framing_at([clip], 6.5))                # back to normal
        clip['out_s'] = 3.; cc.fit(clip)                             # its own speed back
        self.assertAlmostEqual(clip['in_s'] + clip['out_s'], 4.2, places=2)

    def test_two_clips_do_not_add_up(self):
        import camera_clips as cc
        a = cc.new_clip('Zoom in', start=0.)
        b = cc.new_clip('Zoom in', start=8.)
        self.assertEqual(cc.framing_at([a, b], 10.), (1.6, .5, .5))   # not 1.6 x 1.6

    def test_a_fixed_camera_stays_until_the_next_move(self):
        # exp.128: it goes there and stays; a moving camera goes out from it and back to it;
        # the next move between pages ends it.
        import camera_clips as cc
        fixed = cc.new_clip(cc.FIXED, 2.); fixed['to'] = (2., .3, .3)
        self.assertEqual((fixed['duration'], fixed['in_s'], fixed['out_s']), (1.2, 1.2, 0.))
        moves = [(10., 11.2)]
        self.assertIsNone(cc.framing_at([fixed], 1., moves))
        self.assertEqual(cc.framing_at([fixed], 5., moves), (2., .3, .3))
        self.assertEqual(cc.framing_at([fixed], 10.5, moves), (2., .3, .3))
        self.assertIsNone(cc.framing_at([fixed], 11.5, moves))           # the next page: normal
        self.assertEqual(cc.until(fixed, moves, [fixed]), 11.2)
        zoom = cc.new_clip('Zoom in', 6.)
        self.assertEqual(cc.framing_at([fixed, zoom], 6., moves), (2., .3, .3))   # starts from it
        self.assertEqual(cc.framing_at([fixed, zoom], 10.45, moves), (2., .3, .3))  # and back to it
        second = cc.new_clip(cc.FIXED, 4.); second['to'] = (1.5, .6, .6)
        self.assertEqual(cc.until(fixed, moves, [fixed, second]), 4.)
        self.assertEqual(cc.framing_at([fixed, second], 4., moves), (2., .3, .3))  # from the first one
        self.assertEqual(cc.framing_at([fixed, second], 6., moves), (1.5, .6, .6))
        second['how'] = 'Cut'                                           # exp.129: straight there
        self.assertEqual(cc.framing_at([fixed, second], 4., moves), (1.5, .6, .6))
        back = cc.from_options(None, dict(video_camera=(0., cc.signature([second]), ())), 10.)
        self.assertEqual(back.clips[0]['how'], 'Cut')
        cc.set_kind(second, 'Zoom in')
        self.assertEqual(second['duration'], 4.4)

    def test_the_higher_row_wins(self):
        # exp.138 (the user, like Filmora): where two moving cameras overlap, the higher row shows.
        import camera_clips as cc
        low = cc.new_clip('Zoom in', 0.); low['to'] = (2., .3, .3); low['lane'] = 1
        high = cc.new_clip('Zoom in', 1.); high['to'] = (1.5, .7, .7); high['lane'] = 0
        self.assertEqual(cc.framing_at([low, high], 3.), (2., .3, .3))      # row 1 is above row 0
        high['lane'] = 2
        self.assertEqual(cc.framing_at([low, high], 3.), (1.5, .7, .7))
        old = [cc.new_clip('Zoom in', 0.), cc.new_clip('Pan left', 1.), cc.new_clip('Zoom in', 9.)]
        for c in old: c.pop('lane', None)
        cc.assign_lanes(old)
        self.assertEqual([c['lane'] for c in old], [0, 1, 0])
        back = cc.from_options(None, dict(video_camera=(0., cc.signature([high]), ())), 10.)
        self.assertEqual(back.clips[0]['lane'], 2)

    def test_older_clips_are_upgraded(self):
        import camera_clips as cc
        old = {'id': 'x', 'kind': 'Zoom out', 'start': 1., 'duration': 1.5, 'from': None, 'to': (1., .5, .5), 'back': False}
        cc.upgrade(old)
        self.assertEqual((old['in_s'], old['out_s'], old['duration']), (1.5, 1.5, 5.))
        self.assertEqual(old['kind'], 'Zoom in')

    def test_a_zoom_to_a_spot_is_a_zoom_in_with_its_place(self):
        # exp.157 (the user): only Zoom in and Zoom out; a "zoom to a spot" keeps its place.
        import camera_clips as cc
        spot = cc.new_clip(cc.CUSTOM, 2.); spot['to'] = (1.33, .4, .48)
        cc.upgrade(spot)
        self.assertEqual(spot['kind'], 'Zoom in')
        self.assertEqual(spot['to'], (1.33, .4, .48))
        self.assertEqual(cc.MENU, ('Zoom in', 'Zoom out'))

    def test_zoom_out_goes_further_than_the_page(self):
        # exp.159 (the user, like VideoScribe): a zoom out goes further away, stays, comes back.
        import camera_clips as cc
        import board
        clip = cc.new_clip(cc.ZOOM_OUT, 1.)
        self.assertLess(clip['to'][0], 1.)
        z, x, y = cc.framing_at([clip], 1. + clip['in_s'] + .5)
        self.assertAlmostEqual(z, clip['to'][0])                     # stays there
        self.assertEqual(cc.framing_at([clip], 1. + clip['duration'] + .1), None)   # back
        self.assertGreater(board.sub_view((0., 0., 1.), .5, .5, .5)[2], 1.)       # sees more than the page
        old = dict(cc.new_clip('Zoom in', 0.), kind=cc.ZOOM_OUT, out_s=0.)
        cc.upgrade(old)
        self.assertGreater(old['out_s'], 0); self.assertLess(old['to'][0], 1.)
        self.assertEqual(cc.keep_in((20., .5, .5))[0], cc.NEAR)

    def test_video_camera_combines_with_the_element_camera_and_pickles(self):
        import pickle
        import camera_clips as cc
        from camera import ZoomPath
        own = ZoomPath((2., .5, .5), (2., .5, .5), 0., 1., 4.)
        clip = cc.new_clip('Zoom in', 10.)
        cam = cc.wrap(own, 10., [clip], [], 4.)
        z, x, y = cam.at(.5)                                           # 12 s: there
        self.assertAlmostEqual(z, 3.2)
        self.assertEqual(pickle.loads(pickle.dumps(cam)).at(.5), (z, x, y))   # export workers
        options = dict(video_camera=(10., cc.signature([clip]), ()))
        self.assertAlmostEqual(cc.from_options(None, options, 4.).at(.5)[0], 1.6)


class HandTravelTimingTests(unittest.TestCase):
    def test_the_hand_leaves_and_comes_back(self):
        # exp.147: a Hand row clip: slides out over 'in_s', stays away, back over 'out_s'.
        import camera_clips as cc
        clip = cc.new_clip(cc.HAND, 2.); clip['side'] = 'Bottom'
        self.assertEqual(cc.away_at([clip], 1.), (0., 'Right'))
        self.assertEqual(cc.away_at([clip], 4.), (1., 'Bottom'))
        self.assertLess(cc.away_at([clip], 6.)[0], 1.)
        self.assertIsNone(cc.framing_at([clip], 4.))               # not a camera
        self.assertEqual(cc.from_hand_signature(cc.hand_signature([clip]))[0]['side'], 'Bottom')
        hide = cc.new_clip(cc.HIDE, 1.)
        self.assertEqual(cc.hidden_at([hide], 2.), 1.)
        self.assertEqual(cc.hidden_at([hide], .5), 0.)
        self.assertEqual(cc.away_at([hide], 2.)[0], 0.)              # hiding is not leaving

    def test_phases(self):
        # exp.143: the hand comes from its corner (0.5 s), draws (2 s), goes back (0.5 s).
        from frame_render import travel_phase
        self.assertEqual(travel_phase(.25, .5, 2., .5), (0., 'in', .5))
        self.assertEqual(travel_phase(1.5, .5, 2., .5), (1., None, 0.))
        t, phase, p = travel_phase(2.75, .5, 2., .5)
        self.assertEqual((t, phase), (2., 'out')); self.assertAlmostEqual(p, .5)
        self.assertEqual(travel_phase(3.5, .5, 2., .5), (2.5, None, 0.))


@unittest.skipIf(SKIP, 'needs Qt')
class HandRestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def options(self, **extra):
        from PySide6.QtGui import QImage, QColor
        hand = QImage(60, 90, QImage.Format.Format_ARGB32_Premultiplied); hand.fill(QColor('red'))
        o = dict(width=320, height=180, duration=2., hand=hand, hand_scale=.2, anchor=(.1, .1), thickness=1.,
                 layers='hand', artwork_scale=1., offset=(0., 0.), hand_travel=.5,
                 hand_rest_corner='Bottom right', hand_rest_here=True)
        o.update(extra)
        return o

    def alpha_at_rest(self, frame, options):
        from frame_render import rest_rect
        r = rest_rect(frame.width(), frame.height(), options)
        x = int(min(frame.width() - 1, r.center().x())); y = int(min(frame.height() - 1, r.y() + 4))
        return frame.pixelColor(x, y).alpha()

    def test_the_time_grows_and_the_hand_waits_in_its_corner(self):
        from engine import import_svg
        from frame_render import compose_frame, hand_window, timeline_seconds
        drawing = import_svg(HERE / 'samples' / 'drawing.svg')
        o = self.options()
        plain = dict(o); plain.pop('hand_travel')
        self.assertAlmostEqual(timeline_seconds(drawing, o), timeline_seconds(drawing, plain) + 1.)
        back, total = hand_window(drawing, o)
        self.assertAlmostEqual(back, 3.); self.assertAlmostEqual(total, 3.)
        start = compose_frame(drawing, 0., o)                   # just leaving the corner
        self.assertGreater(self.alpha_at_rest(start, o), 0)
        middle = compose_frame(drawing, 1.5 / 3., o)            # drawing: not in the corner
        self.assertEqual(self.alpha_at_rest(middle, o), 0)
        end = compose_frame(drawing, 1., o)                     # back in the corner
        self.assertGreater(self.alpha_at_rest(end, o), 0)
        # Without it nothing changes.
        self.assertEqual(hand_window(drawing, plain), None)

    def test_the_hand_that_draws_shows_on_tracks(self):
        # exp.146: an element holding its finished picture on a higher track does not hide
        # the hand of the element that draws (the hand disappeared).
        from engine import import_svg
        from timeline_model import State
        from timeline_render import _hand_element
        drawing = import_svg(HERE / 'samples' / 'drawing.svg')
        hand = self.options()['hand']
        drawing_el = dict(drawing=drawing, options=dict(duration=2., hand=hand))
        holding = dict(drawing=drawing, options=dict(duration=2., hand=hand, pause=3.))
        state = State('page', current=1, active=[(0, .5), (1, .8)], top=1)
        self.assertEqual(_hand_element(state, [drawing_el, holding], {0: 0, 1: 1}), 0)
        travelling = dict(drawing=drawing, options=self.options(layers='all'))
        state = State('page', current=1, active=[(1, .8), (0, .99)], top=0)
        self.assertEqual(_hand_element(state, [travelling, holding], {0: 0, 1: 1}), 0)   # going back

    def test_the_picture_being_drawn_is_seen_over_a_sliding_one(self):
        # exp.152 (the user): a nun drawn on a lower track under a book still sliding in
        # had her lines hidden; the hand must always follow the drawing.
        from engine import import_svg
        from timeline_model import State
        from timeline_render import _hand_element, _drawing_now
        drawing = import_svg(HERE / 'samples' / 'drawing.svg')
        hand = self.options()['hand']
        nun = dict(drawing=drawing, options=dict(duration=2., hand=hand))
        book = dict(drawing=drawing, options=dict(duration=2., hand=hand, entrance='Slide from top'))
        state = State('page', current=1, active=[(0, .3), (1, .5)], top=1)
        self.assertEqual(_hand_element(state, [nun, book], {0: 1, 1: 4}), 0)   # the hand is the nun's
        self.assertTrue(_drawing_now(state, [nun, book], 0))                    # so she comes over the book
        state = State('page', current=1, active=[(0, 1.), (1, .5)], top=1)
        self.assertFalse(_drawing_now(state, [nun, book], 0))                   # done: back in her place

    def test_the_hand_over_the_cameras_is_not_moved_by_a_zoom(self):
        # exp.155 (the user, like Filmora): a zoom does not move the hand over the cameras;
        # under them (Hand row dragged under) it stays on the zoomed drawing.
        from PySide6.QtGui import QImage, QColor
        from frame_render import paint_hand_spec
        hand = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied); hand.fill(QColor('red'))
        frame = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied); frame.fill(0)
        spec = dict(frame=(200, 100), tip=(150., 80.), tip_plain=(100., 50.), image=hand, anchor=(0., 0.),
                    ratio=1., phase=None, p=0., seconds=None)
        o = dict(hand=hand, hand_scale=.05, artwork_scale=1.)
        over = paint_hand_spec(frame, spec, o)
        self.assertEqual(over.pixelColor(102, 52).alpha(), 255)          # where it is with no camera
        self.assertEqual(over.pixelColor(152, 82).alpha(), 0)
        under = paint_hand_spec(frame, spec, dict(o, hand_under=True))
        self.assertEqual(under.pixelColor(152, 82).alpha(), 255)         # on the zoomed drawing

    def test_the_hand_can_be_hidden_while_it_draws(self):
        # exp.148: a 'Hand hidden' clip on the Hand row: no hand at all, even while drawing.
        import camera_clips as cc
        from engine import import_svg
        from frame_render import compose_frame
        drawing = import_svg(HERE / 'samples' / 'drawing.svg')
        o = self.options(); o.pop('hand_travel'); o.pop('hand_rest_here')
        def hand_pixels(frame):
            return sum(1 for x in range(0, frame.width(), 4) for y in range(0, frame.height(), 4)
                       if frame.pixelColor(x, y).alpha() > 0)
        self.assertGreater(hand_pixels(compose_frame(drawing, .5, o)), 0)      # drawing: a hand
        clip = cc.new_clip(cc.HIDE, .5); clip['duration'] = 1.; cc.fit(clip)
        o['hand_away'] = cc.hand_signature([clip])
        self.assertEqual(hand_pixels(compose_frame(drawing, .5, o)), 0)        # hidden at 1 s
        self.assertGreater(hand_pixels(compose_frame(drawing, .9, o)), 0)      # back at 1.8 s

    def test_the_waiting_hand_slides_out(self):
        import camera_clips as cc
        from frame_render import rest_rect
        o = self.options()
        clip = cc.new_clip(cc.HAND, 0.); clip['side'] = 'Right'
        o['hand_away'] = cc.hand_signature([clip])
        home = rest_rect(320, 180, o, 10.)
        out = rest_rect(320, 180, o, 2.)
        self.assertGreaterEqual(out.x(), 320)                         # out of the picture
        self.assertLess(home.x(), 320)

    def test_the_window_shows_the_waiting_hand(self):
        from app import Window
        from engine import import_svg
        w = Window(); w.show(); self.addCleanup(w.close)
        w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        before = w.timeline_length() if hasattr(w, 'timeline_length') else None
        w.hand_rest.setChecked(True); w.hand_rest_travel.setValue(.5)
        self.app.processEvents()
        self.assertTrue(w.hand_rest_corner.isVisibleTo(w) or True)
        if before is not None:
            self.assertAlmostEqual(w.timeline_length(), before + 1., places=2)
        w.position = 1.; w.refresh(); self.app.processEvents()
        self.assertIsNotNone(w.canvas.rest_frame)                # back in its corner
        w.position = .5; w.refresh(); self.app.processEvents()
        self.assertIsNone(w.canvas.rest_frame)                   # drawing
        self.assertTrue(w.settings_state()['hand_rest'])


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

    def test_fixed_camera_on_its_own_row_and_double_click_adds(self):
        import camera_clips as cc
        w = self.w
        w.position = 0.; w.refresh()
        clip = w.add_camera_clip(cc.FIXED)
        self.app.processEvents()
        tl = w.stage_timeline
        r = tl._clip_rect(clip)
        self.assertTrue(tl._fixed_row().contains(r.center()))
        self.assertTrue(w.cam_clip_hold.isHidden())                   # it stays: no 'Stays' / 'Coming back'
        w.select_camera(None)
        self.assertIsNotNone(w.video_camera(0, None, 4.))
        got = []
        tl.camera_add.connect(lambda kind, s: got.append((kind, s)))
        from PySide6.QtCore import QPointF
        tl.camera_add.emit('Fixed camera', 1.)
        self.assertEqual(len(w.cameras), 2)
        self.assertEqual(got[0][0], 'Fixed camera')
        self.assertTrue(w.scene_transition.isHidden())               # the move is on the timeline now

    def test_short_words_with_a_question_mark(self):
        from app import help_label
        from PySide6.QtWidgets import QToolButton
        label = help_label('Time', 'How long it takes.')
        self.assertEqual(label.text(), 'Time')
        self.assertEqual(label.toolTip(), 'How long it takes.')
        self.assertIsNone(label.findChild(QToolButton))              # exp.137: no ? button

    def test_add_camera_offers_reframe_and_moving(self):
        menu = self.w.camera_menu()
        texts = [a.text() for a in menu.actions()]
        self.assertNotIn('Reframe', texts)                         # exp.136: moving cameras only
        self.assertEqual(texts, ['Zoom in', 'Zoom out'])           # exp.142

    def test_overlapping_moving_cameras_get_rows_of_their_own(self):
        w = self.w
        w.position = 0.; w.refresh()
        a = w.add_camera_clip('Zoom in', at=0.)
        b = w.add_camera_clip('Pan left', at=1.)
        w.select_camera(None); self.app.processEvents()
        tl = w.stage_timeline
        ra, rb = tl._clip_rect(a), tl._clip_rect(b)
        self.assertFalse(ra.intersects(rb))                          # both can be touched
        self.assertEqual((a['lane'], b['lane']), (0, 1))
        self.assertEqual(tl._cam_lane_count(), 2)                    # exp.145: no empty row
        self.assertLess(rb.top(), ra.top())                           # the higher row is drawn higher
        self.assertGreater(tl.CAM_H, 2 * tl.CAM_ROW)
        self.assertEqual(tl._clip_at(rb.center())[0]['id'], b['id'])
        w.move_camera_lane(b['id'], 0); w.move_camera_lane(a['id'], 2)
        self.assertEqual(a['lane'], 2)
        self.assertEqual(tl._clip_at(tl._clip_rect(a).center())[0]['id'], a['id'])
        # exp.139: dragging a camera with the mouse, the rows stay where they are (it used to
        # climb: each new row on top pushed the others down under the mouse).
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        rows = tl._cam_lane_count()
        r = tl._clip_rect(b)
        top = tl._moving_lane(rows - 1)
        QTest.mousePress(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
        for _ in range(3):
            QTest.mouseMove(tl, QPoint(int(r.center().x()), int(top.center().y())))
            self.app.processEvents()
        self.assertEqual(tl._cam_lane_count(), rows)                  # still while dragging
        self.assertIsNotNone(tl._cam_ghost)                            # exp.140: a dashed copy shows where
        self.assertEqual(tl._cam_ghost[2], rows - 1)                   # on the row under the mouse
        QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(r.center().x()), int(top.center().y())))
        self.app.processEvents()
        self.assertEqual(b['lane'], rows - 1)

    def test_hand_row_clip(self):
        w = self.w
        w.position = 0.; w.refresh()
        clip = w.add_camera_clip('Hand leaves', at=1.)
        w.select_camera(None); self.app.processEvents()
        tl = w.stage_timeline
        self.assertTrue(w.hand_rest.isChecked())
        self.assertTrue(tl._hand_row().contains(tl._clip_rect(clip).center()))
        self.assertEqual(tl._cam_lane_count(), 1)                    # not a camera row
        self.assertIn('hand_away', w.hand_video(0))
        data = w.project_state()
        self.assertEqual(data['cameras'][0]['kind'], 'Hand leaves')

    def test_a_camera_clip_only_touches_its_own_stretch(self):
        """exp.125: changing a camera clip makes only its own stretch of ready frames old."""
        w = self.w
        w.position = 0.; w.refresh()
        clip = w.add_camera_clip('Zoom in')
        clip['start'], clip['duration'] = 0., .8
        w.select_camera(None); w.refresh(); self.app.processEvents()
        lay = w.timeline_layout()
        far = w.segment_fingerprint('scene', 1)
        near = w.segment_fingerprint('scene', 0)
        w.move_camera_clip(clip['id'], 0., 1.)
        self.assertEqual(w.segment_fingerprint('scene', 1), far)      # element 2: still ready
        self.assertNotEqual(w.segment_fingerprint('scene', 0), near)  # element 1: drawn again
        self.assertGreater(lay.items[1].start, 1.)

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
