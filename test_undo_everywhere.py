"""exp.95: Undo / redo for every change.

* Ctrl+Y works on Windows (two shortcuts on the same key cancelled each other).
* Ctrl+Z in a number box undoes the program, not only the typing.
* Each element keeps its undo history when you switch to another one and back.
* Adding, deleting and moving elements can be undone, in order with everything else.
* The painting order and AI parts are part of undo too.
"""
import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


@unittest.skipIf(SKIP, 'needs Qt')
class UndoTests(unittest.TestCase):
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
        self.w.playing = False
        self.w.close()
        self.app.processEvents()

    def change(self, widget, value):
        widget.setValue(value)
        self.w.commit_history()

    def test_redo_keys_are_not_ambiguous(self):
        keys = [s.key().toString() for s in self.w.redo_shortcuts]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn('Ctrl+Y', keys)
        self.assertIn('Ctrl+Shift+Z', keys)

    def test_ctrl_z_in_a_number_box_undoes_the_program(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        w = self.w
        before = w.thickness.value()
        self.change(w.thickness, before + 2)
        w.thickness.setFocus(); self.app.processEvents()
        QTest.keyClick(w.thickness.lineEdit(), Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertAlmostEqual(w.thickness.value(), before)
        QTest.keyClick(w.thickness.lineEdit(), Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertAlmostEqual(w.thickness.value(), before + 2)
        self.assertIn('Redone', w.status.text())

    def test_keys_in_a_window_with_a_window_attribute_do_not_crash(self):
        """exp.100: a dialog that keeps the main window as `self.window` hid
        QWidget.window(), and Ctrl+Z there raised "'Window' object is not callable"."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QDialog
        dialog = QDialog(self.w)
        dialog.window = self.w
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(self.w.undo_keys.eventFilter(dialog, event))
        dialog.deleteLater()

    def test_each_element_keeps_its_history(self):
        w = self.w
        w.add_scene()                                    # element 2 (a copy)
        before = w.thickness.value()
        self.change(w.thickness, before + 3)
        w.select_scene(0); self.app.processEvents()
        w.select_scene(1); self.app.processEvents()
        self.assertAlmostEqual(w.thickness.value(), before + 3)
        w.undo()
        self.assertAlmostEqual(w.thickness.value(), before)

    def test_delete_element_can_be_undone(self):
        from PySide6.QtWidgets import QMessageBox
        w = self.w
        w.add_scene()
        self.assertEqual(len(w.scenes), 2)
        with mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            w.delete_scene()
        self.assertEqual(len(w.scenes), 1)
        w.undo()
        self.assertEqual(len(w.scenes), 2)
        w.redo()
        self.assertEqual(len(w.scenes), 1)

    def test_changes_undo_in_the_order_they_were_made(self):
        w = self.w
        before = w.thickness.value()
        self.change(w.thickness, before + 1)            # 1. a setting
        w.add_scene()                                    # 2. a new element
        self.assertEqual(len(w.scenes), 2)
        w.undo()                                         # undoes 2
        self.assertEqual(len(w.scenes), 1)
        self.assertAlmostEqual(w.thickness.value(), before + 1)
        w.undo()                                         # then 1
        self.assertAlmostEqual(w.thickness.value(), before)

    def test_painting_order_is_undone(self):
        w = self.w
        w.drawing.paint_part_order = [3, 1, 2]
        w.commit_history()
        w.undo()
        self.assertFalse(hasattr(w.drawing, 'paint_part_order'))
        w.redo()
        self.assertEqual(list(w.drawing.paint_part_order), [3, 1, 2])

    def test_nothing_to_undo_says_so(self):
        w = self.w
        w.reset_history(); w.project_undo.clear()
        w.undo()
        self.assertIn('Nothing to undo', w.status.text())


if __name__ == '__main__':
    unittest.main()
