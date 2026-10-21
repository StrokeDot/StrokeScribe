"""exp.54: elements like VideoScribe — comes in / pause / goes out, element cards with
times, and the element editor window (Set / Cancel)."""
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


def alpha(image):
    import numpy as np
    from PySide6.QtGui import QImage
    im = image.convertToFormat(QImage.Format.Format_RGBA8888)
    a = np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.bytesPerLine())[:, 3::4][:, :im.width()]
    return a.astype(float)


@unittest.skipIf(SKIP, 'needs Qt')
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def options(self, **extra):
        o = dict(width=480, height=270, duration=2., fade_duration=.4, hold_duration=.5, final_image=None,
                 thickness=1., hand=None, hand_scale=.2, anchor=(.1, .1), reveal_mode='adaptive',
                 brush_width=.14, painting_hand=None, stroke_spacing=.55, artwork_scale=1.)
        o.update(extra)
        return o

    def test_comes_in_with_an_effect(self):
        from engine import import_svg
        from frame_render import compose_frame, timeline_seconds
        d = import_svg(HERE / 'samples' / 'drawing.svg')
        whole = alpha(compose_frame(d, 1., self.options())).sum()
        fade = self.options(entrance='Fade')
        early, late = alpha(compose_frame(d, .2, fade)).sum(), alpha(compose_frame(d, 1., fade)).sum()
        self.assertLess(early, late * .4)                        # faint at the start of the fade
        self.assertAlmostEqual(late, whole, delta=whole * .02)   # complete at the end
        # Slide in from the left: at the start the picture is still left of its place.
        import numpy as np
        slide = alpha(compose_frame(d, .1, self.options(entrance='Slide from left')))
        done = alpha(compose_frame(d, 1., self.options(entrance='Slide from left')))
        cols = lambda a: np.nonzero(a.sum(0) > 0)[0]
        if len(cols(slide)):
            self.assertLess(cols(slide).max(), cols(done).max())
        # No pen moves while it comes in (no pencil sound, no camera follow).
        import motion
        samples = motion.track(d, fade, 2., 10)
        self.assertTrue(all(s.point is None for _, s in samples))
        self.assertEqual(timeline_seconds(d, fade), 2.)

    def test_pause_and_goes_out(self):
        from engine import import_svg
        from frame_render import compose_frame, timeline_seconds
        d = import_svg(HERE / 'samples' / 'drawing.svg')
        o = self.options(pause=2.)
        self.assertAlmostEqual(timeline_seconds(d, o), 4.)
        finished = alpha(compose_frame(d, 1., self.options())).sum()
        self.assertAlmostEqual(alpha(compose_frame(d, .6, o)).sum(), finished, delta=finished * .02)   # pausing
        out = self.options(pause=1., erase=dict(mode='fade', seconds=2.))
        self.assertAlmostEqual(timeline_seconds(d, out), 5.)
        middle = alpha(compose_frame(d, 4. / 5, out)).sum()
        self.assertLess(middle, finished * .7); self.assertGreater(middle, finished * .2)
        self.assertLess(alpha(compose_frame(d, 1., out)).sum(), finished * .02)   # gone
        from eraser import MODES
        for name in ('Fade out', 'Pop out', 'Zoom out', 'Move out to the left'):
            self.assertIn(name, MODES)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        from engine import import_svg
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); self.app.processEvents()
        self.w.duration.setValue(2.)
        self.w.add_scene(); self.w.set_drawing(import_svg(HERE / 'samples' / 'arthur-headset-traced.svg'))
        self.w.duration.setValue(1.5)

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()

    def test_element_cards_and_editor(self):
        w = self.w
        self.assertIn('⏱', w.scene_list.item(0).text())
        self.assertIn('➜', w.scene_list.item(0).text())          # the camera move after element 1
        self.assertEqual(w.scene_add.text(), '+ Add element')
        self.assertEqual(w.preview_scope.itemText(0), 'This element')
        from element_dialog import ElementDialog
        w.scene_list.setCurrentRow(0)
        d = ElementDialog(w, 0)
        # Change how it comes in, its pause, how it goes out and the move: the window follows.
        # Appearance controls now precede the entrance controls in the editor.
        how = next(m for m, t in d.pairs if t is w.entrance)
        how.setCurrentText('Pop in')
        self.assertEqual(w.entrance.currentText(), 'Pop in')
        pause = next(m for m, t in d.pairs if t is w.pause_after)
        pause.setValue(1.5)
        self.assertEqual(w.pause_after.value(), 1.5)
        out = next(m for m, t in d.pairs if t is w.erase_mode)
        out.setCurrentText('Fade out')
        self.assertEqual(w.erase_mode.currentText(), 'Fade out')
        d.transition.setCurrentText('Pan right'); d.move.setValue(2.)
        self.assertEqual(w.scenes[0]['transition'], 'Pan right')
        self.assertEqual(w.scenes[0]['transition_seconds'], 2.)
        d.name.setText('House')
        d.seek(.5)
        self.assertIsNotNone(d.preview.pixmap())
        # Cancel: everything back.
        d.reject()
        self.assertEqual(w.entrance.currentText(), 'Draw with the hand')
        self.assertEqual(w.pause_after.value(), 0.)
        self.assertEqual(w.erase_mode.currentText(), 'Off')
        self.assertEqual(w.scenes[0]['transition'], 'Camera move')
        self.assertNotEqual(w.scene_label(0), 'House')
        # Set: the changes stay and show on the card.
        d = ElementDialog(w, 0)
        next(m for m, t in d.pairs if t is w.pause_after).setValue(2.)
        d.name.setText('House')
        d.accept()
        self.assertEqual(w.pause_after.value(), 2.)
        self.assertIn('House', w.scene_list.item(0).text())
        length, move = w.element_times(0)
        self.assertGreaterEqual(length, 4.)
        # The whole video still plays.
        w.preview_scope.setCurrentIndex(1)
        for v in (200, 600, 950):
            w.slider.setValue(v)
            self.assertFalse(w.canvas.frame.isNull())


if __name__ == '__main__':
    unittest.main(verbosity=2)
