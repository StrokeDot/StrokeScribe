"""exp.66 (the user: the elements take too much room; the timeline needs it): one row of
miniatures with the name beside each, the buttons in one row."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class CompactStrip(unittest.TestCase):
    def test_one_row_of_miniatures(self):
        from app import Window
        from engine import import_svg
        w = Window(); w.show(); w.resize(1500, 950)
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
            w.scenes[1]['name'] = 'Arthur bad news2'; w.fill_scenes()
            for _ in range(20): APP.processEvents()
            self.assertLessEqual(w.scene_list.height(), 48)
            card = w.scene_list.item(1)
            self.assertNotIn('\n', card.text())
            self.assertIn('Arthur bad news2', card.text())
            self.assertIn('s', card.toolTip().split('\n')[1])                # its times: in the tooltip
            fm = w.scene_list.fontMetrics()
            room = w.scene_list.gridSize().width() - w.scene_list.iconSize().width() - 16
            self.assertGreater(room, fm.horizontalAdvance('2 · Arthur'))     # room for the name, not "..."
            self.assertEqual(w.scene_add.y(), w.scene_edit.y())              # the buttons: one row
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
