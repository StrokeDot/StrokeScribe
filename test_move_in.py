"""exp.84: Comes in — only the lines move in (then the colours are painted), and a
move-in hand that carries the picture in on the Slide effects."""
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

HERE = Path(__file__).parent


class PlanTests(unittest.TestCase):
    """The timing and positions (no Qt needed)."""

    def test_the_hand_carries_then_leaves(self):
        import move_in
        self.assertEqual(move_in.picture_progress(.5, None), .5)          # no hand: as before
        self.assertAlmostEqual(move_in.picture_progress(move_in.CARRY / 2, 'bottom'), .5)
        self.assertEqual(move_in.picture_progress(move_in.CARRY, 'bottom'), 1.)   # arrived, hand lets go
        box = (.3, .2, .7, .6)
        self.assertEqual(move_in.grip_point(box, 'bottom'), (.5, .6))
        self.assertEqual(move_in.grip_point(box, 'left'), (.3, .4))
        x, y = move_in.hand_position(box, 'bottom', .3, (0., .25))
        self.assertAlmostEqual(y, .85)                                    # holds the picture's lower edge
        x, y = move_in.hand_position(box, 'bottom', 1., (0., 0.))
        self.assertGreater(y, 1.)                                         # gone below the frame
        x, y = move_in.hand_position(box, 'right', 1., (0., 0.))
        self.assertGreater(x, 1.)                                         # back out to the right

    def test_lines_only_needs_colours(self):
        import move_in

        class Picture:
            def isNull(self):
                return False
        self.assertEqual(move_in.part_of({'entrance_part': 'lines'}), 'all')       # nothing to paint
        self.assertEqual(move_in.part_of({'entrance_part': 'lines', 'final_image': Picture()}), 'lines')
        self.assertEqual(move_in.part_of({'final_image': Picture()}), 'all')


def counts(image):
    """(red, green, any) pixel counts."""
    import numpy as np
    from PySide6.QtGui import QImage
    im = image.convertToFormat(QImage.Format.Format_RGBA8888)
    a = np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.bytesPerLine())
    a = a[:, :im.width() * 4].reshape(im.height(), im.width(), 4).astype(int)
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    red = (r > 150) & (g < 90) & (b < 90) & (al > 150)
    green = (g > 150) & (r < 90) & (b < 90) & (al > 150)
    return red, green, al > 20


@unittest.skipIf(SKIP, 'needs Qt')
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def options(self, **extra):
        o = dict(width=480, height=270, duration=2., fade_duration=.4, hold_duration=.5, final_image=None,
                 thickness=1., hand=None, hand_scale=.2, anchor=(.1, .1), reveal_mode='fade',
                 brush_width=.14, painting_hand=None, stroke_spacing=.55, artwork_scale=1.)
        o.update(extra)
        return o

    def drawing(self):
        from engine import import_svg
        return import_svg(HERE / 'samples' / 'drawing.svg')

    def red_picture(self):
        from PySide6.QtGui import QColor, QImage
        im = QImage(480, 270, QImage.Format.Format_ARGB32_Premultiplied)
        im.fill(QColor(220, 20, 20))
        return im

    def green_hand(self):
        from PySide6.QtGui import QColor, QImage
        im = QImage(60, 90, QImage.Format.Format_ARGB32_Premultiplied)
        im.fill(QColor(20, 220, 20))
        return im

    def test_only_the_lines_move_in_then_the_colours_are_painted(self):
        from frame_render import compose_frame, timeline_seconds
        d = self.drawing()
        colours = self.red_picture()
        lines = self.options(final_image=colours, entrance='Slide from bottom', entrance_part='lines')
        whole = self.options(final_image=colours, entrance='Slide from bottom', entrance_part='all')
        total = timeline_seconds(d, lines)
        self.assertAlmostEqual(total, 2.9)
        moving = 1.6 / total                         # the lines are still coming in
        self.assertEqual(counts(compose_frame(d, moving, lines))[0].sum(), 0)      # no colours yet
        self.assertGreater(counts(compose_frame(d, moving, lines))[2].sum(), 0)    # but the lines are there
        self.assertGreater(counts(compose_frame(d, moving, whole))[0].sum(), 0)    # whole picture: colours too
        self.assertGreater(counts(compose_frame(d, 1., lines))[0].sum(), 1000)     # painted at the end
        # The pen comes back for the painting (sound, camera), not while the lines move.
        import motion
        samples = motion.track(d, lines, total, 10)
        self.assertTrue(all(s.point is None and s.kind is None for t, s in samples if t < 1.9))

    def test_the_hand_carries_the_picture_in(self):
        import numpy as np
        from frame_render import compose_frame
        d = self.drawing()
        o = self.options(entrance='Slide from bottom', move_hand=self.green_hand(), move_hand_grip=(.5, 0.),
                         move_hand_size=.1, offset=(0., -.3))     # room below the picture for the hand
        _, green, art = counts(compose_frame(d, .6, o))
        self.assertGreater(green.sum(), 50)                    # the hand is there while carrying
        rows_hand, rows_art = np.nonzero(green.any(1))[0], np.nonzero((art & ~green).any(1))[0]
        self.assertGreaterEqual(rows_hand.min(), rows_art.max() - 3)   # below the picture, holding its edge
        self.assertGreater(counts(compose_frame(d, .76, o))[1].sum(), 0)        # letting go, leaving
        self.assertEqual(counts(compose_frame(d, 1., o))[1].sum(), 0)           # gone at the end
        self.assertEqual(counts(compose_frame(d, .6, dict(o, layers='art')))[1].sum(), 0)   # Drawing only
        hand_only = counts(compose_frame(d, .6, dict(o, layers='hand')))
        self.assertGreater(hand_only[1].sum(), 50)
        self.assertEqual((hand_only[2] & ~hand_only[1]).sum(), 0)                # Hand only: no picture
        self.assertEqual(counts(compose_frame(d, .6, dict(o, entrance='Fade')))[1].sum(), 0)   # slides only
        self.assertEqual(counts(compose_frame(d, .6, dict(o, move_hand=None)))[1].sum(), 0)

    def test_settings_give_the_hand(self):
        from export_job import options_from_settings
        d = self.drawing()
        on = options_from_settings({'entrance': 'Slide in from the bottom', 'move_hand': True,
                                    'entrance_part': 'Only the lines, then paint the colours'}, d)
        self.assertIsNotNone(on['move_hand'])
        self.assertEqual(on['entrance_part'], 'lines')
        self.assertIsNone(options_from_settings({'move_hand': False}, d)['move_hand'])
        self.assertIsNone(options_from_settings({}, d)['move_hand'])        # older projects: no hand

    def test_export_with_the_hand(self):
        from engine import export_frames
        from export_job import options_from_settings
        d = self.drawing()
        o = options_from_settings({'entrance': 'Slide in from the bottom', 'move_hand': True,
                                   'res': '1920 × 1080', 'duration': 1}, d)
        for key in ('audio', 'fps'):
            o.pop(key, None)
        o.update(width=320, height=180, workers=1)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertGreater(export_frames(d, Path(tmp) / 'f', fps=6, **o), 2)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_controls(self):
        from app import Window
        w = Window()
        try:
            w.entrance.setCurrentIndex(0)
            self.assertFalse(w.entrance_part.isEnabled())        # drawn by the hand: nothing moves in
            w.entrance.setCurrentText('Slide in from the bottom')
            self.assertTrue(w.entrance_part.isEnabled())
            self.assertTrue(w.move_hand.isChecked())
            w.move_hand_gx.setValue(.5)
            w.set_move_hand(None)                                 # built-in: its own grip again
            self.assertAlmostEqual(w.move_hand_gx.value(), .08)
            self.assertIn('placeholder', w.move_hand_name.text())
            self.assertIsNotNone(w.options()['move_hand'])
            state = w.settings_state()
            self.assertIn('move_hand_path', state)
            self.assertTrue(state['move_hand'])
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
