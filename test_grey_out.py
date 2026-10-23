"""exp.96: settings that cannot apply are greyed out (with the reason in their tooltip)."""
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


@unittest.skipIf(SKIP, 'needs Qt')
class GreyOutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        from engine import import_svg
        from PySide6.QtGui import QColor, QImage
        self.w = Window()
        self.w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        colours = QImage(200, 150, QImage.Format.Format_ARGB32_Premultiplied)
        colours.fill(QColor(200, 60, 40))
        self.w.final_image = colours
        self.w.use_color.setEnabled(True)
        self.w.use_color.setChecked(True)
        self.w.update_applicable()

    def tearDown(self):
        self.w.close()

    def label(self):
        return self.w.timing_form.labelForField(self.w.duration).text()

    def test_drawn_by_the_hand_everything_applies(self):
        w = self.w
        w.entrance.setCurrentIndex(0)
        self.assertEqual(self.label(), 'Draw time (s)')
        for widget in (w.pen_ease, w.reveal_mode, w.color_fade, w.brush_width, w.camera):
            self.assertTrue(widget.isEnabled())
        self.assertFalse(w.entrance_part.isEnabled())

    def test_effect_greys_out_drawing_and_painting(self):
        w = self.w
        w.entrance.setCurrentText('Fade in')
        self.assertEqual(self.label(), 'Draw time (s)')
        self.assertFalse(w.duration.isEnabled())                         # exp.100: Move-in time is used
        self.assertTrue(w.move_time.isEnabled())
        self.assertFalse(w.draw_on.isChecked()); self.assertTrue(w.move_in_on.isChecked())
        self.assertFalse(w.pen_ease.isEnabled())
        self.assertIn('Not used now', w.pen_ease.toolTip())
        self.assertFalse(w.reveal_mode.isEnabled())                      # the whole picture fades in
        self.assertTrue(w.entrance_part.isEnabled())
        w.entrance_part.setCurrentIndex(1)                               # only the lines, then paint
        self.assertTrue(w.reveal_mode.isEnabled())
        self.assertTrue(w.color_fade.isEnabled())
        w.entrance.setCurrentIndex(0)                                    # back to the hand
        self.assertEqual(self.label(), 'Draw time (s)')
        self.assertTrue(w.duration.isEnabled())
        self.assertTrue(w.draw_on.isChecked()); self.assertFalse(w.move_in_on.isChecked())
        self.assertTrue(w.pen_ease.isEnabled())
        self.assertNotIn('Not used now', w.pen_ease.toolTip())

    def test_no_colours_no_painting_settings(self):
        w = self.w
        w.use_color.setChecked(False)
        for widget in (w.reveal_mode, w.color_fade, w.brush_width, w.stroke_spacing, w.color_hold):
            self.assertFalse(widget.isEnabled())
        self.assertTrue(w.pen_ease.isEnabled())

    def test_goes_out(self):
        w = self.w
        w.erase_mode.setCurrentText('Off')
        self.assertFalse(w.erase_time.isEnabled()); self.assertFalse(w.eraser.isEnabled())
        w.erase_mode.setCurrentText('Fade out')
        self.assertTrue(w.erase_time.isEnabled()); self.assertFalse(w.erase_size.isEnabled())
        w.erase_mode.setCurrentText('Zigzag (follows the shapes)')
        self.assertTrue(w.erase_size.isEnabled()); self.assertTrue(w.eraser.isEnabled())


if __name__ == '__main__':
    unittest.main()


@unittest.skipIf(SKIP, 'needs Qt')
class DrawingSwitchTests(unittest.TestCase):
    """exp.100: Animation -> Drawing has an on/off switch; off = Move in."""
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        from engine import import_svg
        self.w = Window()
        self.w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))

    def tearDown(self):
        self.w.close()

    def test_drawing_is_on_by_default(self):
        w = self.w
        self.assertTrue(w.draw_on.isChecked())
        self.assertEqual(w.entrance.currentIndex(), 0)
        self.assertTrue(w.section_drawing.switch.isChecked())
        self.assertFalse(w.section_move_in.switch.isChecked())

    def test_switching_drawing_off_uses_move_in(self):
        w = self.w
        w.section_drawing.switch.click()                     # Drawing off
        self.assertFalse(w.draw_on.isChecked())
        self.assertTrue(w.move_in_on.isChecked())
        self.assertEqual(w.entrance.currentText(), 'Fade in')
        self.assertTrue(w.section_move_in.expanded)
        w.entrance.setCurrentText('Slide in from the left')
        w.section_move_in.switch.click()                     # Move in off = Drawing on
        self.assertTrue(w.draw_on.isChecked())
        self.assertEqual(w.entrance.currentIndex(), 0)
        w.section_drawing.switch.click()                     # off again: the last effect comes back
        self.assertEqual(w.entrance.currentText(), 'Slide in from the left')

    def test_move_in_time_is_the_draw_time(self):
        w = self.w
        w.move_time.setValue(6.5)
        self.assertAlmostEqual(w.duration.value(), 6.5)
        w.duration.setValue(3)
        self.assertAlmostEqual(w.move_time.value(), 3)

    def test_project_values_show_on_the_switches(self):
        w = self.w
        w.entrance.blockSignals(True); w.entrance.setCurrentText('Zoom in'); w.entrance.blockSignals(False)
        w.update_applicable()                                # as after a project, undo or element switch
        self.assertFalse(w.draw_on.isChecked())
        self.assertTrue(w.move_in_on.isChecked())

