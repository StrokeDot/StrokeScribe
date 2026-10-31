"""exp.50: the board (VideoScribe style) — frames, camera moves, sharp zoom,
export through the board, and the Board view."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

import board

HERE = Path(__file__).parent
A = 9 / 16


class MathTests(unittest.TestCase):
    def test_default_frames_follow_the_transitions(self):
        scenes = [dict(transition='Camera move'), dict(transition='Pan down'), dict(transition='Pan left'),
                  dict(transition='Same page'), dict(transition='Cut')]
        f = board.frames(scenes, A)
        self.assertEqual(f[0], (0., 0., 1.))
        self.assertAlmostEqual(f[1][0], 1.12)                       # to the right
        self.assertAlmostEqual(f[2][1], A * 1.12)                   # below
        self.assertAlmostEqual(f[3][0], 0.)                         # to the left
        self.assertEqual(f[4], f[3])                                # same page
        self.assertTrue(board.has_base(f, 4, A))
        self.assertFalse(board.has_base(f, 1, A))
        # A scene placed by hand keeps its frame; the next ones follow it.
        scenes[1]['board'] = dict(cx=.2, cy=.1, w=.3)
        f = board.frames(scenes, A)
        self.assertEqual(f[1], (.2, .1, .3))
        self.assertTrue(board.has_base(f, 1, A))                    # a small frame inside scene 1
        self.assertAlmostEqual(f[2][1], .1 + .3 * A * 1.12)

    def test_camera_moves(self):
        a, b = (0., 0., 1.), (1.12, 0., 1.)
        self.assertEqual(board.move_view(a, b, 'Camera move', 0.), a)
        end = board.move_view(a, b, 'Camera move', 1.)
        self.assertAlmostEqual(end[0], 1.12); self.assertAlmostEqual(end[2], 1.)
        self.assertGreater(board.move_view(a, b, 'Camera move', .5)[2], 1.5)   # zooms out on the way
        self.assertAlmostEqual(board.move_view(a, b, 'Pan right', .5)[2], 1.)  # a pan does not
        # Into a small frame: the camera zooms in smoothly.
        small = (.1, .05, .25)
        widths = [board.move_view(a, small, 'Pan right', t / 10)[2] for t in range(11)]
        self.assertTrue(all(x >= y for x, y in zip(widths, widths[1:])))
        self.assertAlmostEqual(widths[-1], .25)

    def test_timeline_with_show_everything(self):
        self.assertEqual(board.transition_seconds('Camera move', 1.2, last=True), 0.)
        self.assertAlmostEqual(board.transition_seconds('Show everything', 1.5, last=True), 1.5 + board.END_HOLD)
        self.assertEqual(board.transition_seconds('Same page', 1.2), 0.)
        lengths, joins = [4., 3.], [1., 2.5]
        self.assertEqual(board.locate(lengths, joins, 2.)[:2], ('scene', 0))
        self.assertEqual(board.locate(lengths, joins, 4.5)[:2], ('join', 0))
        self.assertEqual(board.locate(lengths, joins, 7.)[:2], ('scene', 1))
        kind, k, t = board.locate(lengths, joins, 9.)
        self.assertEqual((kind, k), ('join', 1))
        f = [(0., 0., 1.), (1.12, 0., 1.)]
        whole = board.bounds(f, A)
        self.assertGreater(whole[2], 2.12)
        self.assertEqual(board.join_view(f, 1, 'Show everything', 1., A, 1.5), whole)
        self.assertEqual(board.join_view(f, 1, 'Show everything', .9, A, 1.5), whole)   # holding


@unittest.skipIf(SKIP, 'needs Qt')
class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def options(self):
        return dict(width=640, height=360, duration=1., fade_duration=.4, hold_duration=.5, final_image=None,
                    thickness=1., hand=None, hand_scale=.2, anchor=(.1, .1), reveal_mode='adaptive',
                    brush_width=.14, painting_hand=None, stroke_spacing=.55, artwork_scale=1.)

    def test_zoom_draws_bigger_not_stretched(self):
        from engine import import_svg
        d = import_svg(HERE / 'samples' / 'drawing.svg')
        world = board.World([dict(drawing=d, options=self.options(), frame=(0., 0., 1.), key='a')], A)
        normal = world.view((0., 0., 1.), 400, 225, upto=1)
        self.assertFalse(normal.isNull())
        world.view((0., 0., 1 / 3), 400, 225, upto=1)               # camera 3× closer
        widest = max(k[1] for k in world.cache)
        self.assertGreaterEqual(widest, 3 * 400 * .95)               # drawn about 1200 px wide
        far = world.view((5., 5., 1.), 400, 225, upto=1)             # nothing there
        self.assertEqual(far.pixelColor(200, 112).alpha(), 0)


@unittest.skipIf(SKIP, 'needs Qt')
class BoardWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        from app import Window
        from engine import import_svg
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); self.app.processEvents()
        self.w.duration.setValue(1.)
        self.w.add_scene()
        self.w.set_drawing(import_svg(HERE / 'samples' / 'arthur-headset-traced.svg'))
        self.w.duration.setValue(1.)

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()
        self.tmp.cleanup()

    def test_one_resolution_for_every_element(self):
        """exp.100: switching elements keeps the video's resolution (a page at 1920 x 1080
        and the picture on it at 2560 x 1440 did not line up)."""
        w = self.w
        w.res.setCurrentIndex(0)
        w.select_scene(0); self.app.processEvents()
        w.res.setCurrentIndex(1)
        chosen = w.res.currentText()
        w.select_scene(1); self.app.processEvents()
        self.assertEqual(w.res.currentText(), chosen)
        w.select_scene(0); self.app.processEvents()
        self.assertEqual(w.res.currentText(), chosen)

    def test_board_view_move_resize_and_edit(self):
        w = self.w
        w.preview_scope.setCurrentIndex(2)
        self.assertTrue(w.board_mode())
        self.assertTrue(w.board_arrange.isVisible())
        self.assertFalse(w.canvas.frame.isNull())
        view, W, H = w._board_map
        frames = w.board_frames()
        # The middle of frame 1 picks scene 1.
        from board import World
        place = World([], H / W).place
        x, y, fw, fh = place(frames[0], view, W, H)
        self.assertEqual(w.board_pick(x + fw / 2, y + fh / 2), 0)
        x2, y2, fw2, fh2 = place(frames[1], view, W, H)
        # Drag scene 2's frame left and make it smaller with the mouse wheel.
        self.assertTrue(w.board_drag('start', x2 + fw2 / 2, y2 + fh2 / 2))
        self.assertEqual(w.scene_index, 1)
        w.board_drag('move', -.2, .1)
        w.board_drag('done', 0, 0)
        moved = w.board_frames()[1]
        self.assertLess(moved[0], frames[1][0] - .1)
        self.assertEqual(w.board_frames()[0], frames[0])            # the other frame stays
        view, W, H = w._board_map
        mx, my, mw, mh = place(moved, view, W, H)
        w.board_wheel(-3, mx + mw / 2, my + mh / 2)
        self.assertLess(w.board_frames()[1][2], 1.)
        # Saved with the project.
        import projects, scenes
        saved = projects.save(self.dir / 'board', w.project_state())
        back = scenes.scenes_from_project(projects.load(saved))
        self.assertAlmostEqual(back[1]['board']['w'], w.board_frames()[1][2])
        # Arrange in a row again.
        w.arrange_board()
        self.assertEqual(w.board_frames(), [(0., 0., 1.), (1.12, 0., 1.)])
        # Double-click a frame: edit that scene.
        w.show_board()
        view, W, H = w._board_map
        x, y, fw, fh = place(w.board_frames()[0], view, W, H)
        w.board_double(x + fw / 2, y + fh / 2)
        self.assertEqual(w.scene_index, 0)
        self.assertEqual(w.preview_scope.currentIndex(), 1)          # the whole video, at that element

    def test_small_frame_inside_and_show_everything_export(self):
        import scenes
        w = self.w
        # Scene 2 is a small frame inside scene 1: the camera zooms in, scene 1 stays visible.
        w.scenes[0]['board'] = dict(cx=0., cy=0., w=1.)
        w.scenes[1]['board'] = dict(cx=.25, cy=.1, w=.35)
        w.scene_transition.setCurrentText('Show everything'); w.scene_transition_changed()   # last scene
        self.assertTrue(w.drawn_over(1))
        # Preview: the start of scene 2 already shows part of scene 1 (zoomed in, so bigger).
        base = w.scene_base(1, 480, 270)
        self.assertIsNotNone(base)
        w.preview_scope.setCurrentIndex(1)
        lengths, joins = w.scene_timeline()
        self.assertGreater(joins[1], 1.)                             # zoom out at the end
        for value in (300, 600, 990):
            w.slider.setValue(value)
            self.assertFalse(w.canvas.frame.isNull())
        w.preview_scope.setCurrentIndex(0)
        # Export.
        w.fps.setValue(4); w.mp4.setChecked(False); w.webm.setChecked(False); w.mov.setChecked(False)
        w._leave_scene()
        listed = [dict(state=s['state'], transition=s['transition'], transition_seconds=s['transition_seconds'],
                       board=s.get('board')) for s in w.scenes]
        w.scenes[w.scene_index]['state'] = None
        out = self.dir / 'video'
        scenes.export_scenes(listed, out, w.settings_state(), w.hand)
        info = json.loads((out / 'sequence.json').read_text())
        first, second = info['scenes']
        move = round(w.scenes[0]['transition_seconds'] * 4)
        self.assertEqual(second['first_frame'], first['frames'] + move)
        end = round((w.scenes[1]['transition_seconds'] + board.END_HOLD) * 4)
        self.assertEqual(info['frames'], second['first_frame'] + second['frames'] + end)
        self.assertAlmostEqual(second['board_frame']['w'], .35)
        from PySide6.QtGui import QImage
        import numpy as np

        def ink(path):
            im = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
            a = np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.bytesPerLine())[:, 3::4]
            return (a > 20).mean()
        start_of_second = out / f'frame_{second["first_frame"]:06d}.png'
        self.assertGreater(ink(start_of_second), .002)               # scene 1 under scene 2's frame
        last = out / f'frame_{info["frames"] - 1:06d}.png'
        self.assertGreater(ink(last), .002)                          # the whole board at the end


if __name__ == '__main__':
    unittest.main(verbosity=2)
