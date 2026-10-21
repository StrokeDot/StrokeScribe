"""Regression tests for the existing three-pane Studio layout (no renderer changes)."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication, QScrollArea
from app import Window

APP = QApplication.instance() or QApplication([])
KEYS = ('workspace/source_width', 'workspace/inspector_width',
        'workspace/source_open', 'workspace/inspector_open')


class WorkspaceLayoutTests(unittest.TestCase):
    def setUp(self):
        self.settings = QSettings('StrokeScribe', 'Studio')
        self.prior = {key: self.settings.value(key) for key in KEYS}
        for key in KEYS:
            self.settings.remove(key)
        self.settings.sync()
        self.windows = []

    def make_window(self, width=1490, height=890):
        w = Window()
        self.windows.append(w)
        w.resize(width, height)
        w.show()
        APP.processEvents()
        APP.processEvents()  # scheduled sidebar restore / resize
        return w

    def tearDown(self):
        for w in self.windows:
            w.playing = False
            w.close()
        APP.processEvents()
        for key, value in self.prior.items():
            if value is None:
                self.settings.remove(key)
            else:
                self.settings.setValue(key, value)
        self.settings.sync()

    def test_default_sidebars_and_timeline_survive_window_resizing(self):
        for width, height in ((1040, 768), (1490, 890),
                              (1920, 1080), (2560, 1440)):
            w = self.make_window(width, height)
            split = w.workspace_splitter
            parts = split.sizes()
            self.assertEqual(len(parts), 3)
            self.assertTrue(w.source_sidebar_button.isChecked())
            self.assertTrue(w.inspector_sidebar_button.isChecked())
            self.assertTrue(w.findChild(type(split.widget(0)), 'assetPanel').isVisible())
            self.assertTrue(w.findChild(type(split.widget(2)), 'inspectorPanel').isVisible())
            self.assertGreaterEqual(parts[0], 225)
            self.assertGreaterEqual(parts[2], 270)
            self.assertGreaterEqual(parts[1], 390)
            self.assertLessEqual(parts[0], 460)
            self.assertLessEqual(parts[2], 480)
            # Gaps are only the two narrow splitter handles.
            self.assertLessEqual(abs(sum(parts) - split.width()), 20)
            self.assertTrue(w.canvas.isVisible())
            self.assertTrue(w.stage_timeline.isVisible())
            self.assertGreater(w.stage_timeline.height(), 25)

    def test_independent_collapse_expands_the_preview_and_restores_width(self):
        w = self.make_window(1920, 1080)
        split = w.workspace_splitter
        before = split.sizes()
        split.moveSplitter(360, 1)
        APP.processEvents()
        source_width = split.sizes()[0]
        self.assertGreater(source_width, before[0])
        self.assertEqual(w.sidebar_layout.widths['source'], source_width)
        w.source_sidebar_button.click()
        APP.processEvents()
        self.assertTrue(split.widget(0).isHidden())
        self.assertFalse(w.source_sidebar_button.isChecked())
        self.assertGreater(split.sizes()[1], before[1])
        self.assertFalse(split.widget(2).isHidden())

        w.inspector_sidebar_button.click()
        APP.processEvents()
        self.assertTrue(split.widget(2).isHidden())
        self.assertGreater(split.sizes()[1], 1700)
        self.assertTrue(w.stage_timeline.isVisible())
        w.source_sidebar_button.click()
        APP.processEvents()
        self.assertFalse(split.widget(0).isHidden())
        self.assertAlmostEqual(split.sizes()[0], source_width, delta=12)
        self.assertTrue(split.widget(2).isHidden())
        w.inspector_sidebar_button.click()
        APP.processEvents()
        self.assertFalse(split.widget(2).isHidden())

    def test_sidebar_widths_and_collapse_survive_reopening_window(self):
        w = self.make_window()
        w.workspace_splitter.moveSplitter(355, 1)
        APP.processEvents()
        recorded = w.sidebar_layout.widths['source']
        w.sidebar_layout.set_expanded('inspector', False)
        w.close()
        APP.processEvents()
        reopened = self.make_window()
        self.assertTrue(reopened.sidebar_layout.expanded['source'])
        self.assertFalse(reopened.sidebar_layout.expanded['inspector'])
        self.assertTrue(reopened.workspace_splitter.widget(2).isHidden())
        self.assertAlmostEqual(reopened.workspace_splitter.sizes()[0], recorded, delta=12)
        reopened.sidebar_layout.set_expanded('inspector', True)
        APP.processEvents()
        self.assertGreaterEqual(reopened.workspace_splitter.sizes()[2], 270)

    def test_source_and_inspector_scroll_independently_without_horizontal_overflow(self):
        w = self.make_window(1040, 768)
        source = [w.text_scroll]                     # left panel: Text page
        inspector = w.inspector_tabs.findChildren(QScrollArea)
        self.assertEqual(len(source), 1)
        self.assertEqual(len(inspector), 5)          # Animation, Hand, Export, Image, AI
        self.assertTrue(all(area.horizontalScrollBarPolicy() ==
                            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                            for area in source + inspector))
        self.assertTrue(all(area.widgetResizable() for area in source + inspector))
        self.assertGreater(source[0].verticalScrollBar().maximum(), 0)
        w.show_right_panel('animation')
        APP.processEvents()
        active = w.inspector_tabs.currentWidget()
        self.assertIn(active, inspector)
        self.assertGreater(active.verticalScrollBar().maximum(), 0)
        active.verticalScrollBar().setValue(0)
        source[0].verticalScrollBar().setValue(
            min(80, source[0].verticalScrollBar().maximum()))
        APP.processEvents()
        self.assertEqual(active.verticalScrollBar().value(), 0)
        # The icon rail replaced the tab strip (experimental.76).
        self.assertFalse(w.inspector_tabs.tabBar().isVisible())
        self.assertTrue(w.right_rail.isVisible())

    def test_narrow_inspector_controls_remain_inside_viewport(self):
        from PySide6.QtWidgets import QFormLayout
        w = self.make_window(1040, 768)
        tab = w.inspector_tabs
        for index in range(tab.count()):
            tab.setCurrentIndex(index)
            APP.processEvents()
            area = tab.widget(index)
            self.assertIsInstance(area, QScrollArea)
            self.assertGreater(area.viewport().width(), 185)
            for form in area.widget().findChildren(QFormLayout):
                from studio_workspace import TABS
                expected=(QFormLayout.RowWrapPolicy.DontWrapRows if index==0
                          else QFormLayout.RowWrapPolicy.WrapAllRows if index==TABS['source']
                          else QFormLayout.RowWrapPolicy.WrapLongRows)
                self.assertEqual(form.rowWrapPolicy(),expected)
        # The source and inspector must remain navigable at the minimum size.
        self.assertTrue(w.export.isEnabled())
        self.assertTrue(w.source_type.isEnabled())


    def test_rails_open_pages_and_collapse_both_sides(self):
        from studio_workspace import TABS
        w = self.make_window(1490, 890)
        split = w.workspace_splitter
        w.rail_buttons['source'].click()
        APP.processEvents()
        self.assertEqual(w.inspector_tabs.currentIndex(), TABS['source'])
        self.assertTrue(w.rail_buttons['source'].isChecked())
        self.assertFalse(w.rail_buttons['animation'].isChecked())
        self.assertTrue(w.import_button.isVisible())
        # Clicking the open page's icon again collapses the right panel only.
        w.rail_buttons['source'].click()
        APP.processEvents()
        self.assertTrue(split.widget(2).isHidden())
        self.assertFalse(split.widget(0).isHidden())
        self.assertTrue(w.right_rail.isVisible())
        w.rail_buttons['export'].click()
        APP.processEvents()
        self.assertFalse(split.widget(2).isHidden())
        self.assertEqual(w.inspector_tabs.currentIndex(), TABS['export'])
        # Left rail: Text shows / hides the Handwriting panel.
        self.assertTrue(w.rail_text.isChecked())
        w.rail_text.click()
        APP.processEvents()
        self.assertTrue(split.widget(0).isHidden())
        self.assertFalse(w.source_sidebar_button.isChecked())
        w.show_handwriting_panel()
        APP.processEvents()
        self.assertFalse(split.widget(0).isHidden())
        self.assertTrue(w.rail_text.isChecked())


if __name__ == '__main__':
    unittest.main(verbosity=2)
