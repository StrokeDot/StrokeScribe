"""exp.97: Filmora-style panels — sections that open on click, on/off switches on
their headers, a slimmer rail, no "Program" title over the preview."""
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
class PolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        from engine import import_svg
        self.w = Window()
        self.w.show()
        self.w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.app.processEvents()

    def test_every_section_starts_closed(self):
        """exp.100: every section closed by default, everywhere (Image, Animation, Hand)."""
        from ui_sections import Section
        w = self.w
        sections = w.findChildren(Section)
        self.assertGreaterEqual(len(sections), 12)
        for section in sections:
            self.assertFalse(section.expanded, section.title.text() + ' starts open')
        for name in ('section_drawing', 'section_move_in', 'section_painting', 'section_out',
                     'section_draw_hand', 'section_paint_hand', 'section_move_hand', 'section_transform',
                     'section_appearance', 'section_ink', 'section_look_colour', 'section_look_light',
                     'section_colors', 'section_image_drawing'):
            self.assertIn(getattr(w, name), sections)

    def test_position_has_sliders_like_scale(self):
        """exp.100: Position X and Y: a slider plus the number, like Scale; a click on
        the track jumps there."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from ui_sections import reveal
        w = self.w
        w.show_right_panel('source'); reveal(w.picture_x); self.app.processEvents()
        w.x_slider.setValue(30)
        self.assertAlmostEqual(w.picture_x.value(), 30)
        w.picture_y.setValue(-40)
        self.assertEqual(w.y_slider.value(), -40)
        QTest.mouseClick(w.x_slider, Qt.MouseButton.LeftButton, pos=QPoint(w.x_slider.width() - 3,
                                                                            w.x_slider.height() // 2))
        self.assertGreater(w.picture_x.value(), 80)                   # jumped near the right end

    def test_clicking_a_header_opens_and_closes_it(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        w = self.w
        w.show_right_panel('animation'); self.app.processEvents()
        header = w.section_painting.header
        QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=header.rect().center())
        self.assertTrue(w.section_painting.expanded)
        self.assertTrue(w.reveal_mode.isVisible())
        QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=header.rect().center())
        self.assertFalse(w.section_painting.expanded)

    def test_switches_follow_their_settings(self):
        w = self.w
        switch = w.section_paint_hand.switch
        self.assertTrue(switch.isChecked())
        switch.click()
        self.assertFalse(w.show_paint_hand.isChecked())
        w.show_paint_hand.blockSignals(True); w.show_paint_hand.setChecked(True); w.show_paint_hand.blockSignals(False)
        self.assertTrue(switch.isChecked())                     # a quiet restore shows at once

    def test_goes_out_switch(self):
        w = self.w
        w.erase_mode.setCurrentText('Fade out')
        self.assertTrue(w.erase_on.isChecked())
        w.section_out.switch.click()                            # off
        self.assertEqual(w.erase_mode.currentText(), 'Off')
        w.section_out.switch.click()                            # on again: the way chosen before
        self.assertEqual(w.erase_mode.currentText(), 'Fade out')

    def test_no_program_title_and_slim_rail(self):
        w = self.w
        from PySide6.QtWidgets import QLabel
        titles = [l for l in w.findChildren(QLabel) if l.text() == 'Program' and l.isVisible()]
        self.assertEqual(titles, [])
        button = next(iter(w.rail_buttons.values()))
        self.assertEqual(button.iconSize().width(), 18)


if __name__ == '__main__':
    unittest.main()
