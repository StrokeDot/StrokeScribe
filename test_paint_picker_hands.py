"""exp.87: the Paint mode picker (a bigger window with groups, descriptions and a
preview) and a Right | Left switch under the drawing hand and the painting hand."""
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
class PickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        self.w = Window()
        self.w.show()

    def tearDown(self):
        self.w.close()
        self.app.processEvents()

    def test_groups_keep_every_mode_and_order(self):
        from paint_mode_dialog import GROUPS
        w = self.w
        shown = [text for _, modes in GROUPS for text, _ in modes]
        listed = [w.reveal_mode.itemText(i) for i in range(w.reveal_mode.count())]
        self.assertEqual(sorted(shown), sorted(listed))                  # nothing lost, nothing new
        self.assertEqual(shown[:2], ['Adaptive Hand Painting', 'Adaptive — Short up/down strokes'])
        self.assertEqual(shown[-1], 'Brush painting')                    # at the bottom
        self.assertEqual(listed[0], 'Brush painting')                    # the list's own order is unchanged

    def test_clicking_paint_mode_opens_the_picker_and_choosing_sets_it(self):
        from PySide6.QtCore import Qt
        w = self.w
        w.reveal_mode.showPopup()
        self.app.processEvents()
        dialog = w.paint_mode_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertFalse(w.reveal_mode.view().isVisible())              # no small dropdown
        dialog.list.setCurrentItem(dialog.items['Zigzag sweep'])
        self.assertIn('scribbling', dialog.about.text())
        dialog.accept()
        self.app.processEvents()
        self.assertEqual(w.reveal_mode.currentText(), 'Zigzag sweep')
        w.reveal_mode.showPopup(); self.app.processEvents()
        w.paint_mode_dialog.list.setCurrentItem(w.paint_mode_dialog.items['Brush painting'])
        w.paint_mode_dialog.reject(); self.app.processEvents()
        self.assertEqual(w.reveal_mode.currentText(), 'Zigzag sweep')   # Cancel keeps it
        self.assertIsNotNone(Qt)

    def test_preview_frames_on_an_element_with_colours(self):
        from engine import import_svg
        from PySide6.QtGui import QColor, QImage
        w = self.w
        w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        colours = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
        colours.fill(QColor(200, 60, 40))
        w.final_image = colours
        w.use_color.setEnabled(True); w.use_color.setChecked(True)
        w.reveal_mode.showPopup(); self.app.processEvents()
        dialog = w.paint_mode_dialog
        dialog.list.setCurrentItem(dialog.items['Top to bottom (rows)'])
        mode = 'Top to bottom (rows)'
        for _ in range(400):
            self.app.processEvents()
            dialog.render_next()
            if len(dialog._frames.get(mode, [])) >= 18:
                break
        self.assertEqual(len(dialog._frames[mode]), 18)
        dialog.reject()

    def test_no_preview_without_colours(self):
        w = self.w
        w.reveal_mode.showPopup(); self.app.processEvents()
        dialog = w.paint_mode_dialog
        self.assertTrue(dialog.preview.text())                           # a short note instead
        dialog.reject()


@unittest.skipIf(SKIP, 'needs Qt')
class HandSideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_right_left_switches(self):
        import tools_kit
        from app import Window
        w = Window()
        try:
            right, left = w.left_handed_toggle.buttons
            self.assertTrue(right.isChecked())
            left.click()
            self.assertTrue(w.left_handed.isChecked())
            self.assertTrue(w.settings_state()['left_handed'])
            # Same as drawing hand: the painting switch follows and is not separate.
            w.paint_hand.setCurrentText(tools_kit.PAINT_SAME); w.update_paint_hand_label()
            self.assertFalse(w.paint_left_handed_toggle.isEnabled())
            self.assertTrue(w.paint_left_handed.isChecked())
            # Its own painting hand: its own side.
            w.paint_hand.setCurrentText(tools_kit.PAINT_BRUSH); w.update_paint_hand_label()
            self.assertTrue(w.paint_left_handed_toggle.isEnabled())
            w.paint_left_handed_toggle.buttons[0].click()
            self.assertFalse(w.paint_left_handed.isChecked())
            self.assertTrue(w.left_handed.isChecked())                   # the drawing hand stays left
            state = w.settings_state()
            self.assertFalse(state['paint_left_handed'])
        finally:
            w.close()

    def test_painting_hand_side_is_its_own(self):
        import tools_kit
        from PySide6.QtGui import QImage
        hand = QImage(str(HERE / 'assets' / 'default_hand.png'))
        base = {'paint_hand': tools_kit.PAINT_BRUSH, 'show_paint_hand': True}
        right = tools_kit.painting_hand(dict(base, left_handed=True, paint_left_handed=False), hand)
        left = tools_kit.painting_hand(dict(base, left_handed=False, paint_left_handed=True), hand)
        old = tools_kit.painting_hand(dict(base, left_handed=True), hand)          # older projects
        self.assertIsNot(right, left)
        self.assertIs(old, left)


if __name__ == '__main__':
    unittest.main()
