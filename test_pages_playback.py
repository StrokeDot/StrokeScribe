"""exp.45: picture position on the page, several pictures on one page
('Same page'), smoother preview playback (ready-made frames), and cleaning
the colour picture of saved projects."""
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

import scenes

HERE = Path(__file__).parent


class PlainTests(unittest.TestCase):
    def test_same_page_has_no_move(self):
        self.assertIn(scenes.SAME_PAGE, scenes.TRANSITIONS)
        self.assertEqual(scenes.transition_seconds(scenes.SAME_PAGE, 2.), 0.)
        listed = [dict(transition=scenes.SAME_PAGE), dict(transition='Cut'), dict(transition='Fade')]
        self.assertEqual([scenes.on_page(listed, k) for k in range(3)], [False, True, False])
        opts = scenes.for_page(dict(camera_zoom=1.3, width=10))
        self.assertEqual((opts['camera_zoom'], opts['background']), (1., False))


def visible_box(image):
    """(left, top, right, bottom) of the visible pixels of a QImage."""
    import numpy as np
    from PySide6.QtGui import QImage
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    a = np.frombuffer(bytes(rgba.constBits()), np.uint8).reshape(rgba.height(), rgba.bytesPerLine())
    alpha = a[:, 3:rgba.width() * 4:4]
    ys, xs = np.nonzero(alpha > 20)
    return xs.min(), ys.min(), xs.max(), ys.max()


@unittest.skipIf(SKIP, 'needs Qt')
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_position_moves_the_picture_and_eraser(self):
        from engine import import_svg
        from frame_render import compose_frame
        d = import_svg(HERE / 'samples' / 'drawing.svg')
        base = dict(width=400, height=225, duration=1., fade_duration=.4, hold_duration=.5, final_image=None,
                    thickness=1., hand=None, hand_scale=.2, anchor=(.1, .1), reveal_mode='adaptive',
                    brush_width=.14, painting_hand=None, stroke_spacing=.55, artwork_scale=.5)
        a = visible_box(compose_frame(d, 1., base))
        b = visible_box(compose_frame(d, 1., dict(base, offset=(.25, -.1))))
        self.assertAlmostEqual(b[0] - a[0], 100, delta=2)
        self.assertAlmostEqual(b[1] - a[1], -22, delta=2)
        # While erasing, the picture stays where it was moved to.
        from export_job import builtin_eraser
        from eraser import ERASER_TIP
        erase = dict(mode='zigzag', seconds=1., size=.08, image=builtin_eraser(), anchor=ERASER_TIP, width=.18)
        e = visible_box(compose_frame(d, .55, dict(base, offset=(.25, 0.), erase=erase)))
        self.assertGreater(e[0], a[0] + 60)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        from app import Window
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); self.app.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()
        self.tmp.cleanup()

    def test_drag_on_preview_moves_picture(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        w = self.w
        c = w.canvas
        x, y, size = c.frame_rect()
        start = QPoint(x + size.width() // 2, y + size.height() // 2)
        end = QPoint(start.x() + size.width() // 10, start.y())
        QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in range(1, 6):
            QTest.mouseMove(c, QPoint(start.x() + (end.x() - start.x()) * step // 5, start.y()))
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, QPointF
        c.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(end), Qt.MouseButton.NoButton,
                                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        self.assertAlmostEqual(w.picture_x.value(), 10, delta=1.5)
        self.assertAlmostEqual(w.picture_y.value(), 0, delta=.5)
        self.assertIn('picture_x', w.settings_state())
        w.picture_center.click()
        self.assertEqual((w.picture_x.value(), w.picture_y.value()), (0., 0.))

    def test_add_picture_on_same_page(self):
        from engine import import_svg
        w = self.w
        w.duration.setValue(1.)
        first = visible_box(w.canvas.frame)
        w.add_picture()
        self.assertEqual(len(w.scenes), 2)
        self.assertEqual(w.scene_index, 1)
        self.assertEqual(w.scenes[0]['transition'], scenes.SAME_PAGE)
        self.assertTrue(scenes.on_page(w.scenes, 1))
        self.assertLess(w.artwork_size.value(), 100)
        self.assertGreater(w.picture_x.value(), 0)
        self.assertIn('+', w.scene_list.item(1).text())
        w.set_drawing(import_svg(HERE / 'samples' / 'arthur-headset-traced.svg'))
        w.duration.setValue(1.)
        # At the start of picture 2, picture 1 is already on the page.
        w.slider.setValue(0); self.app.processEvents()
        base = w.page_base(1, w.canvas.frame.width(), w.canvas.frame.height())
        self.assertIsNotNone(base)
        start = visible_box(w.canvas.frame)
        self.assertLessEqual(start[0], first[0] + 2)
        # All scenes: no move between the two pictures.
        w.preview_scope.setCurrentIndex(1)
        lengths, joins = w.scene_timeline()
        self.assertEqual(joins[0], 0.)
        w.preview_scope.setCurrentIndex(0)
        # Export: the last frame has both pictures.
        w.fps.setValue(4); w.mp4.setChecked(False); w.webm.setChecked(False); w.mov.setChecked(False)
        w._leave_scene()
        listed = [dict(state=s['state'], transition=s['transition'],
                       transition_seconds=s['transition_seconds']) for s in w.scenes]
        w.scenes[w.scene_index]['state'] = None
        out = self.dir / 'page'
        scenes.export_scenes(listed, out, w.settings_state(), w.hand)
        info = json.loads((out / 'sequence.json').read_text())
        self.assertEqual(info['scenes'][1]['first_frame'], info['scenes'][0]['frames'])   # no move frames
        from PySide6.QtGui import QImage
        last = QImage(str(out / f'frame_{info["frames"] - 1:06d}.png'))
        first_of_second = QImage(str(out / f'frame_{info["scenes"][1]["first_frame"]:06d}.png'))
        box_last = visible_box(last)
        box_first_picture = visible_box(first_of_second)
        self.assertGreater(box_last[2], box_first_picture[0])     # both are there
        # Saved and opened again: still on the same page.
        import projects
        saved = projects.save(self.dir / 'page', w.project_state())
        from app import Window
        other = Window(); self.addCleanup(other.close)
        self.assertTrue(other.open_project(str(saved)))
        self.assertEqual(other.scenes[0]['transition'], scenes.SAME_PAGE)

    def test_playback_uses_ready_frames(self):
        w = self.w
        w.duration.setValue(1.)
        self.app.processEvents()
        ready, total = w.ready_frames()
        self.assertEqual(ready, 0)
        self.assertGreater(total, 20)
        for _ in range(total + 2):                  # what the idle pre-render does
            w.prerender_step()
        ready, total = w.ready_frames()
        self.assertEqual(ready, total)
        # Playing: every frame comes ready-made (same picture object, no new drawing).
        w.playing = True
        index, count = w.frame_index(.5)
        frame = w.preview_frame(index / count, playing=True)
        self.assertIs(frame, w._frames[index])
        w.playing = False
        # Any change: the frames are made again.
        w.thickness.setValue(2.)
        self.assertEqual(w.ready_frames()[0], 0)
        # Moving the playhead keeps them.
        for _ in range(5): w.prerender_step()
        kept = w.ready_frames()[0]
        w.slider.setValue(300)
        self.assertEqual(w.ready_frames()[0], kept)
        self.assertFalse(w.canvas.frame.isNull())

    def test_project_colour_picture_is_cleaned(self):
        from PySide6.QtGui import QImage, QColor
        from projects import qimage_to_b64
        w = self.w
        # A colour picture with a painted checkerboard around a red square.
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        for yy in range(80):
            for xx in range(120):
                grey = 255 if ((xx // 10) + (yy // 10)) % 2 else 204
                image.setPixelColor(xx, yy, QColor(grey, grey, grey))
        for yy in range(25, 55):
            for xx in range(40, 80):
                image.setPixelColor(xx, yy, QColor(220, 30, 30))
        state = w.project_state()
        state['color_png'] = qimage_to_b64(image)
        state.setdefault('settings', {})['use_color'] = True
        state['settings']['clean_color'] = True
        import projects
        saved = projects.save(self.dir / 'colour', state)
        self.assertTrue(w.open_project(str(saved)))
        self.assertIsNotNone(w.final_image)
        self.assertEqual((w.final_image.width(), w.final_image.height()), (40, 30))   # only the square
        w.clean_color.setChecked(False)
        self.assertEqual(w.final_image.width(), 120)                                   # as saved
        w.clean_color.setChecked(True)
        self.assertEqual(w.final_image.width(), 40)


if __name__ == '__main__':
    unittest.main(verbosity=2)
