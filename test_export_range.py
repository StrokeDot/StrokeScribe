"""exp.25 (like Filmora's right-click): Export Selected Clip, Select Clip Range (X), Cancel the
Selected Range (Shift+X), Export Selected Range."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMenu

APP = QApplication.instance() or QApplication([])


class ExportRange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg')); cls.settle()
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); cls.settle()
        w.res.setCurrentIndex(0)                           # the smallest size: quick
        w.fps.setValue(6)
        for box in (w.webm, w.mov, w.mp4):
            box.setChecked(False)
        w.keep_png.setChecked(True)
        w.export_all_scenes.setChecked(True)
        w.preview_scope.setCurrentIndex(1)                # Whole video: the timeline shows the clips
        cls.settle(); w.refresh(); cls.settle()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    @staticmethod
    def settle():
        for _ in range(3):
            for _ in range(30):
                APP.processEvents()
            time.sleep(.1)

    def run_export(self, call):
        out = tempfile.mkdtemp()
        with mock.patch('app.QFileDialog.getExistingDirectory', return_value=out):
            call()
        worker = self.w.worker
        self.assertIsNotNone(worker)
        while worker.isRunning():
            APP.processEvents(); time.sleep(.05)
        self.settle()
        folder, = [p for p in Path(out).iterdir() if p.is_dir()]
        return folder, json.loads((folder / 'sequence.json').read_text())

    def test_the_timeline_selects_and_cancels_a_range(self):
        t = self.w.stage_timeline
        self.assertTrue(t.items)
        t.setFocus()
        t.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier))
        item = next(i for i in t.items if i[0] == t.current_scene)
        self.assertEqual(t.clip_range, (item[2], item[2] + item[3]))
        menu = QMenu(); t._export_actions(menu, item)
        names = [a.text().split('\t')[0] for a in menu.actions() if a.text()]
        for wanted in ('Export Selected Clip…', 'Select Clip Range', 'Cancel the Selected Range'):
            self.assertIn(wanted, names)
        self.assertTrue(any(n.startswith('Export Selected Range') for n in names))
        t.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.ShiftModifier))
        self.assertIsNone(t.clip_range)

    def test_export_selected_range_has_only_that_part(self):
        folder, info = self.run_export(lambda: self.w.export_range(1., 3.))
        self.assertEqual(info['frames'], 12)               # 2 s at 6 fps
        self.assertEqual(info['from_seconds'], 1.)
        self.assertEqual(len(list(folder.glob('frame_*.png'))), 12)

    def test_export_selected_clip_is_the_element_from_its_start_to_its_end(self):
        item = next(it for it in self.w.timeline_layout().items if it.k == 1)
        folder, info = self.run_export(lambda: self.w.export_clip(1))
        self.assertEqual(info['frames'], round((item.start + item.length) * 6) - round(item.start * 6))
        self.assertEqual(info['from_seconds'], round(round(item.start * 6) / 6, 3))


if __name__ == '__main__':
    unittest.main()
