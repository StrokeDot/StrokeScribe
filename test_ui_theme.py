"""Themes, the loading state and the hand layer above scaled artwork."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class HandLayerTests(unittest.TestCase):
    def test_hand_is_not_cut_when_artwork_is_smaller(self):
        from engine import Drawing, Stroke, render, scale_animation_frame
        from hand_layer import capture
        hand = QImage(100, 100, QImage.Format.Format_ARGB32)
        hand.fill(QColor('#ff0000'))
        d = Drawing([Stroke('line', [(0., 0.), (100., 100.)])], (0, 0, 100, 100), [])
        # Old behaviour: the hand was painted into the frame, then shrunk with
        # it, so it ended at the shrunken frame's edge (x=300 here).
        old = scale_animation_frame(render(d, .99, 400, 300, hand=hand, hand_scale=1.,
                                           anchor=(0, 0)), .5)
        self.assertEqual(old.pixelColor(350, 215).alpha(), 0)
        with capture() as hands:
            frame = render(d, .99, 400, 300, hand=hand, hand_scale=1., anchor=(0, 0))
        self.assertEqual(len(hands), 1)
        self.assertEqual(frame.pixelColor(390, 290).alpha(), 0, 'hand not in the artwork layer')
        new = scale_animation_frame(frame, .5, hands)
        self.assertEqual(new.pixelColor(350, 215).name(), '#ff0000', 'hand continues past the old edge')
        # Same final hand size as before (half of 400 px wide).
        row = [new.pixelColor(x, 215).alpha() for x in range(400)]
        first = row.index(255)
        self.assertGreater(first, 240)
        self.assertLess(first, 275)

    def test_without_capture_hand_is_painted_directly(self):
        from engine import Drawing, Stroke, render
        hand = QImage(20, 20, QImage.Format.Format_ARGB32)
        hand.fill(QColor('#00ff00'))
        d = Drawing([Stroke('line', [(0., 0.), (100., 100.)])], (0, 0, 100, 100), [])
        frame = render(d, .5, 400, 300, hand=hand, hand_scale=.05, anchor=(0, 0))
        greens = sum(1 for x in range(0, 400, 2) for y in range(0, 300, 2)
                     if frame.pixelColor(x, y).name() == '#00ff00')
        self.assertGreater(greens, 10)


class ThemeAndBusyTests(unittest.TestCase):
    def setUp(self):
        import theme
        theme.save('dark')
        from app import Window
        self.w = Window()
        self.w.show()
        APP.processEvents()

    def tearDown(self):
        self.w.close()
        import theme
        theme.save('dark')

    def test_dark_is_default_and_light_can_be_chosen(self):
        import theme
        w = self.w
        self.assertEqual(theme.current(), 'dark')
        dark_style = w.styleSheet()
        self.assertIn(theme.PALETTES['dark']['window'], dark_style)
        self.assertEqual(w.theme_button.text(), '☀')
        w.theme_button.click()
        self.assertEqual(theme.current(), 'light')
        self.assertIn(theme.PALETTES['light']['window'], w.styleSheet())
        self.assertIn('spin_up_light', w.styleSheet())
        self.assertEqual(w.theme_button.text(), '☾')
        self.assertIn(theme.PALETTES['light']['brand'], w.brand_wordmark.text())
        self.assertEqual(theme.load_saved(), 'light')
        w.theme_button.click()
        self.assertEqual(theme.current(), 'dark')
        import re
        from pathlib import Path
        for name in ('dark', 'light'):
            for path in re.findall(r'url\("([^"]+)"\)', theme.stylesheet(name, w.theme_assets)):
                self.assertTrue(Path(path).is_file(), path)

    def test_timeline_is_locked_while_preparing(self):
        w = self.w
        w.slider.setValue(300)
        w.set_busy('Preparing your drawing', 40, 'Tracing lines')
        self.assertTrue(w.busy)
        self.assertFalse(w.play.isEnabled())
        self.assertFalse(w.export.isEnabled())
        QTest.mouseClick(w.stage_timeline, Qt.MouseButton.LeftButton,
                         pos=QPoint(w.stage_timeline.width() - 20, 50))
        self.assertEqual(w.slider.value(), 300, 'no scrubbing while busy')
        w.toggle()
        self.assertFalse(w.playing)
        grab = w.canvas.grab()
        self.assertFalse(grab.isNull())
        w.clear_busy()
        self.assertTrue(w.play.isEnabled())
        QTest.mouseClick(w.stage_timeline, Qt.MouseButton.LeftButton,
                         pos=QPoint(w.stage_timeline.width() - 20, 50))
        self.assertGreater(w.slider.value(), 900)

    def test_missing_brush_plan_is_prepared_behind_loading_card(self):
        import numpy as np
        from adaptive_hand import plan_ready, pil_image
        w = self.w
        image = QImage(200, 150, QImage.Format.Format_ARGB32)
        image.fill(QColor(40, 110, 220, 255))
        w.final_image = image
        w.use_color.setEnabled(True)
        w.use_color.setChecked(True)
        w.reveal_mode.setCurrentIndex(w.reveal_mode.findText('Zigzag sweep'))
        APP.processEvents()
        self.assertTrue(plan_ready(w.drawing, image, w.brush_width.value(), w.stroke_spacing.value()))
        self.assertFalse(w.busy)
        self.assertTrue(w.play.isEnabled())

    def test_timecode_display(self):
        from app import timecode
        self.assertEqual(timecode(0), '00:00.00')
        self.assertEqual(timecode(65.5), '01:05.50')
        self.w.slider.setValue(0)
        self.assertEqual(self.w.clock.text(), '00:00.00')
        self.assertTrue(self.w.clock_total.text().startswith('00:'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
