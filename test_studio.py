"""Headless interface regression tests for StrokeScribe Studio.

The UI layout has changed; old animation code paths and options must remain.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from pathlib import Path
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSplitter, QTabWidget
from PySide6.QtGui import QImage
from app import Window

APP=QApplication.instance() or QApplication([])


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.window=Window()
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.playing=False
        self.window.close()
        APP.processEvents()

    def test_three_part_workspace_and_visible_timeline(self):
        w=self.window
        self.assertIn('Studio',w.windowTitle())
        self.assertIn('Prototype',w.windowTitle())
        self.assertEqual(w.inspector_tabs.count(),3)
        self.assertEqual([w.inspector_tabs.tabText(i) for i in range(3)],
                         ['Animation','Hand','Export'])
        split=w.findChild(QSplitter)
        self.assertIsNotNone(split)
        self.assertEqual(split.count(),3)
        self.assertTrue(w.canvas.isVisible())
        self.assertTrue(w.stage_timeline.isVisible())
        self.assertTrue(w.version_button.isVisible())
        self.assertIsNotNone(w.canvas.frame)
        self.assertGreater(w.canvas.width(),350)
        self.assertTrue(w.quick_export.isVisible())
        self.assertEqual(w.source_type.currentIndex(),0)

    def test_stage_timeline_tracks_drawing_paint_and_hold(self):
        w=self.window
        self.assertGreater(w.stage_timeline.draw_seconds,0)
        self.assertEqual(w.stage_timeline.paint_seconds,0)
        original=QImage(40,35,QImage.Format.Format_ARGB32)
        original.fill(0xffd2a370)
        w.final_image=original
        w.use_color.setEnabled(True)
        w.use_color.setChecked(True)
        w.reveal_mode.setCurrentIndex(4)
        w.color_fade.setValue(3.5)
        w.color_hold.setValue(1.25)
        APP.processEvents()
        self.assertAlmostEqual(w.stage_timeline.paint_seconds,3.5)
        self.assertAlmostEqual(w.stage_timeline.hold_seconds,1.25)
        x=w.stage_timeline.width()//2
        QTest.mouseClick(w.stage_timeline,Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(x,28))
        self.assertGreater(w.slider.value(),100)
        self.assertLess(w.slider.value(),900)

    def test_image_and_export_controls_preserved(self):
        w=self.window
        w.inspector_tabs.setCurrentIndex(2)
        self.assertTrue(w.webm.isVisible())
        self.assertTrue(w.keep_png.isVisible())
        self.assertEqual(w.webm_quality.value(),28)
        w.webm.setChecked(True)
        w.keep_png.setChecked(False)
        self.assertTrue(w.webm.isChecked())
        w.source_type.setCurrentIndex(1)
        APP.processEvents()
        self.assertEqual(w.import_button.text(),'Import image…')
        self.assertTrue(w.image_controls.isVisible())
        self.assertFalse(w.export.isEnabled())
        w.source_type.setCurrentIndex(0)
        APP.processEvents()
        self.assertEqual(w.import_button.text(),'Import SVG…')
        self.assertTrue(w.export.isEnabled())
        self.assertFalse(w.image_controls.isVisible())

    def test_preview_background_does_not_change_frame(self):
        w=self.window
        original=bytes(w.canvas.frame.bits())
        w.preview_background.setCurrentIndex(1)
        APP.processEvents()
        self.assertEqual(bytes(w.canvas.frame.bits()),original)
        w.preview_background.setCurrentIndex(2)
        self.assertEqual(bytes(w.canvas.frame.bits()),original)

    def test_source_inspector_and_export_navigation(self):
        w=self.window
        w.quick_export.click()
        self.assertEqual(w.inspector_tabs.currentIndex(),2)
        w.fps.setValue(60)
        self.assertIn('60 fps',w.output_summary.text())
        w.inspector_tabs.setCurrentIndex(0)
        w.source_type.setCurrentIndex(1)
        self.assertFalse(w.load_color_button.isEnabled())
        self.assertFalse(w.reveal_mode.isVisible())
        self.assertTrue(w.image_duration.isVisible())
        w.source_type.setCurrentIndex(0)
        self.assertTrue(w.reveal_mode.isVisible())
        self.assertFalse(w.image_duration.isVisible())

    def test_timeline_keyboard_and_export_busy_guard(self):
        w=self.window
        w.stage_timeline.setFocus()
        QTest.keyClick(w.stage_timeline,Qt.Key.Key_Home)
        self.assertEqual(w.slider.value(),0)
        QTest.keyClick(w.stage_timeline,Qt.Key.Key_Right)
        self.assertEqual(w.slider.value(),10)
        class Busy:
            def isRunning(self): return True
        w.worker=Busy()
        w.sync_workspace()
        self.assertFalse(w.export.isEnabled())
        self.assertFalse(w.quick_export.isEnabled())
        w.save()  # Must return before opening a destination dialog.
        w.worker=None
        w.sync_workspace()
        self.assertTrue(w.export.isEnabled())

    def test_render_at_playhead_not_changed_by_ui(self):
        w=self.window
        w.slider.setValue(500)
        APP.processEvents()
        self.assertAlmostEqual(w.position,.5)
        self.assertFalse(w.canvas.frame.isNull())


if __name__=='__main__':
    unittest.main(verbosity=2)
