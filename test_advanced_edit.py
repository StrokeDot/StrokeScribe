"""exp.17: Advanced edit, an element in a big window with the real preview and panels."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
from test_part_c import sample_font  # noqa: E402

FONT = sample_font()


@unittest.skipIf(FONT is None, 'needs a TrueType font')
class AdvancedEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        cls.w = Window(); cls.w.resize(1500, 900); cls.w.show(); APP.processEvents()
        cls.w.font_select.addItem('Local: test', str(FONT))
        cls.w.font_select.setCurrentIndex(cls.w.font_select.count() - 1)
        cls.w.text.setPlainText('lolo'); cls.w.letter(); APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def open(self, part, inside):
        seen = {}

        def go():
            d = self.w._advanced
            tabs = self.w.inspector_tabs
            seen['tab'] = tabs.tabText(tabs.currentIndex())
            seen['tabs'] = [tabs.tabText(i) for i in range(tabs.count()) if tabs.isTabVisible(i)]
            seen['monitor_inside'] = d.isAncestorOf(self.w.canvas)
            seen['tabs_inside'] = d.isAncestorOf(tabs)
            inside(d, seen)
        QTimer.singleShot(0, go)
        self.w.open_advanced(0, part)
        APP.processEvents()
        return seen

    def test_each_part_opens_its_tab_with_the_real_panels(self):
        expected = {'draw': 'Text', 'paint': 'Animation', 'glide': 'Hand', 'hold': 'Hand', 'erase': 'Animation'}
        for part, tab in expected.items():
            seen = self.open(part, lambda d, s: d.reject())
            self.assertEqual(seen['tab'], tab, part)
            self.assertTrue(seen['monitor_inside'] and seen['tabs_inside'])
            self.assertEqual(seen['tabs'], ['Text', 'Animation', 'Hand', 'Image', 'Camera'])

    def test_panels_go_back_after(self):
        w = self.w
        before = (w.workspace_splitter.indexOf(w.canvas.window() and w.workspace_splitter.widget(1)),
                  w.left_tabs.count(), w.inspector_tabs.count())
        monitor = w.workspace_splitter.widget(1)
        self.open('draw', lambda d, s: d.accept())
        self.assertIs(w.workspace_splitter.widget(1), monitor)
        self.assertEqual((w.left_tabs.count(), w.inspector_tabs.count()), before[1:])
        self.assertEqual(w.left_tabs.indexOf(w.text_scroll), 0)
        self.assertFalse(any(d.isVisible() for d in [w.inspector_tabs.window()] if d is not w))
        self.assertTrue(all(w.inspector_tabs.isTabVisible(i) for i in range(w.inspector_tabs.count())))

    def test_cancel_puts_the_element_back(self):
        w = self.w
        italic = w.text_italic.isChecked()

        def change(d, s):
            w.text_italic.setChecked(not italic)
            w.letter_timer.stop(); w.reletter(); APP.processEvents()
            d.reject()
        self.open('draw', change)
        self.assertEqual(bool(w.drawing.font_layout['italic']), italic)

    def test_apply_keeps_the_change(self):
        w = self.w

        def change(d, s):
            w.text_fx['shadow']['on'].setChecked(True)
            d.accept()
        self.open('draw', change)
        self.assertTrue(w.drawing.text_effects['shadow']['on'])
        w.text_fx['shadow']['on'].setChecked(False)

    def test_the_source_editor_names_the_element(self):
        from source_editor import SourceEditor
        ed = SourceEditor(self.w, 'draw')
        self.assertIn('Element 1', ed.name.text())
        ed.reject()


if __name__ == '__main__':
    unittest.main()
