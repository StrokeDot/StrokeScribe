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
        # Source joined the right panel as the last page (the rail shows it first),
        # so the long-standing indexes of the other pages are unchanged.
        self.assertEqual(w.inspector_tabs.count(),5)
        self.assertEqual([w.inspector_tabs.tabText(i) for i in range(5)],
                         ['Animation','Hand','Export','Image','AI'])
        self.assertEqual([w.left_tabs.tabText(i) for i in range(w.left_tabs.count())],
                         ['Text','Sound','Music','Camera'])
        self.assertEqual(list(w.left_rail_buttons),['text','sound','music','camera'])
        self.assertFalse(w.create_image_button.isVisible())     # the AI panel replaces it
        self.assertFalse(w.inspector_tabs.tabBar().isVisible())
        self.assertEqual(list(w.rail_buttons),['source','ai','animation','hand','export'])
        self.assertTrue(w.left_rail.isVisible() and w.right_rail.isVisible())
        # No project selector or resolution/FPS in the top bar any more.
        self.assertFalse(w.project_menu.isVisible())
        self.assertFalse(w.output_summary.isVisible())
        split=w.findChild(QSplitter,'workspaceSplit')
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
        w.reveal_mode.setCurrentIndex(w.reveal_mode.findText('Adaptive Hand Painting'))
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

    def test_builtin_hand_loaded_with_default_calibration(self):
        w=self.window
        from app import DEFAULT_HAND
        self.assertTrue(DEFAULT_HAND.is_file())
        self.assertIsNotNone(w.hand)
        self.assertFalse(w.hand.isNull())
        self.assertEqual((w.hand.width(),w.hand.height()),(1230,1278))
        self.assertIn('built-in',w.hand_name.text())
        # Calibration defaults match the pencil tip in the bundled image.
        self.assertAlmostEqual(w.ax.value(),.08); self.assertAlmostEqual(w.ay.value(),.13)
        self.assertAlmostEqual(w.handsize.value(),.75)
        w.hand=None; w.use_builtin_hand()
        self.assertFalse(w.hand.isNull())

    def test_export_panel_additions(self):
        w=self.window
        from app import format_seconds
        # MP4 option follows the preview background choice.
        self.assertEqual([w.mp4_background.itemText(i) for i in range(3)],
                         ['White','Dark','Black'])
        w.preview_background.setCurrentIndex(2)
        self.assertEqual(w.mp4_background.currentText(),'Dark')
        w.preview_background.setCurrentIndex(1)
        self.assertEqual(w.mp4_background.currentText(),'White')
        w.mp4.setChecked(True); APP.processEvents()
        self.assertTrue(w.mp4_background.isEnabled())
        self.assertTrue(w.keep_png.isEnabled())
        # Timer formatting.
        self.assertEqual(format_seconds(176.57),'2:57')
        self.assertEqual(format_seconds(3725),'1:02:05')
        # Number boxes get real arrow buttons whose images exist.
        style=w.styleSheet()
        self.assertIn('QAbstractSpinBox::up-arrow',style)
        from pathlib import Path
        import re
        for path in re.findall(r'url\("([^"]+)"\)',style):
            self.assertTrue(Path(path).is_file(),path)

    def test_retired_paint_modes_are_not_offered(self):
        items=[self.window.reveal_mode.itemText(i)
               for i in range(self.window.reveal_mode.count())]
        self.assertEqual(items,['Brush painting','Adaptive Hand Painting','Zigzag sweep',
                               'Top to bottom (rows)','Left to right (columns)',
                               'Adaptive — Short up/down strokes',
                               'Painter — real parts, strokes follow the shape'])
        from app import REVEAL_MODES
        self.assertEqual(REVEAL_MODES,('brush','adaptive','zigzag','rows','columns','short_zigzag','painter'))
        self.assertEqual(self.window.reveal_mode.currentText(),'Adaptive Hand Painting')

    def test_line_list_starts_collapsed_and_canvas_click_toggles_highlight(self):
        from unittest.mock import patch
        w=self.window
        self.assertFalse(w.lines_toggle.isChecked())
        self.assertFalse(w.lines_group.isVisible())
        self.assertGreater(w.order.count(), 0)
        with patch.object(w,'line_at',return_value=0):
            w.click_preview(100,100)
            self.assertEqual(w.selected_rows(), [0])
            self.assertFalse(w.lines_toggle.isChecked())  # selecting never expands the panel
            w.click_preview(100,100)
            self.assertEqual(w.selected_rows(), [])
            w.click_preview(100,100)
            self.assertEqual(w.selected_rows(), [0])
            w.click_preview(100,100,add=True)  # Ctrl+click also toggles
            self.assertEqual(w.selected_rows(), [])
        w.lines_toggle.setChecked(True)
        APP.processEvents()
        self.assertTrue(w.lines_group.isVisible())
        w.order.item(0).setSelected(True)
        w.order.setFocus()
        QTest.keyClick(w.order,Qt.Key.Key_Escape)
        self.assertEqual(w.selected_rows(),[])
        w.lines_toggle.setChecked(False)
        self.assertFalse(w.lines_group.isVisible())

    def test_image_and_export_controls_preserved(self):
        w=self.window
        from studio_workspace import TABS
        w.inspector_tabs.setCurrentIndex(TABS['export'])
        self.assertTrue(w.webm.isVisible())
        self.assertTrue(w.keep_png.isVisible())
        self.assertEqual(w.webm_quality.value(),28)
        w.webm.setChecked(True)
        w.keep_png.setChecked(False)
        self.assertTrue(w.webm.isChecked())
        actual=w.drawing
        w.source_type.setCurrentIndex(1)
        APP.processEvents()
        self.assertIs(w.drawing,actual)
        w.show_right_panel('source')
        APP.processEvents()
        self.assertEqual(w.import_button.text(),'Import SVG…')       # two fixed buttons now
        self.assertEqual(w.import_image_button.text(),'Import image…')
        self.assertTrue(w.image_controls.isVisible())
        self.assertTrue(w.export.isEnabled())  # the current SVG is still available
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
        from studio_workspace import TABS
        self.assertEqual(w.inspector_tabs.currentIndex(),TABS['export'])
        w.fps.setValue(60)
        self.assertIn('60 fps',w.output_summary.text())
        w.inspector_tabs.setCurrentIndex(0)
        w.source_type.setCurrentIndex(1)
        # The import selector does not turn the existing SVG into an image.
        self.assertFalse(w.is_image_artwork())
        self.assertTrue(w.load_color_button.isEnabled())
        self.assertTrue(w.reveal_mode.isVisible())
        self.assertTrue(w.reveal_mode.model().item(0).isEnabled())
        self.assertTrue(w.reveal_mode.model().item(2).isEnabled())
        self.assertFalse(w.image_duration.isVisible())
        w.source_type.setCurrentIndex(0)
        self.assertTrue(w.reveal_mode.isVisible())
        self.assertTrue(w.reveal_mode.model().item(0).isEnabled())
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
