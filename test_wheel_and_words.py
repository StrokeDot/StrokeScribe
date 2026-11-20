"""exp.69 (the user: the wheel must only change a control that was clicked; "where is the option
to return to the corner?"; explanations; one name for the hand's way in and back)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from unittest import mock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel

APP = QApplication.instance() or QApplication([])


def pump(n=15):
    for _ in range(n): APP.processEvents()


def wheel(widget, steps=1):
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    ev = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120 * steps), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev); del ev; pump(3)


class Words(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show(); w.resize(1500, 950)
        w.set_drawing(import_svg('samples/drawing.svg')); pump()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def test_the_wheel_only_changes_a_clicked_control(self):
        from PySide6.QtWidgets import QDoubleSpinBox, QScrollArea, QVBoxLayout, QWidget
        area = QScrollArea(); inner = QWidget(); lay = QVBoxLayout(inner)
        box = QDoubleSpinBox(); box.setRange(0, 100); box.setValue(50)
        lay.addWidget(box); lay.addSpacing(2000)
        area.setWidget(inner); area.resize(300, 300); area.show(); pump()
        try:
            area.setFocus(); pump()
            wheel(box, -1)                                         # down
            self.assertEqual(box.value(), 50)                      # not clicked: it does not change
            self.assertGreater(area.verticalScrollBar().value(), 0)   # the panel scrolls instead
            wheel(box.lineEdit())
            self.assertEqual(box.value(), 50)                      # nor through its text field
            box.setFocus(); pump()
            wheel(box)
            self.assertNotEqual(box.value(), 50)                   # clicked: the wheel changes it
        finally:
            area.close()

    def test_back_to_its_corner_with_an_explanation(self):
        w = self.w
        seen = {}

        def look(dialog):
            boxes = dialog.findChildren(QComboBox)
            seen['ends'] = next(b for b in boxes if b.count() and b.itemText(0).startswith('Back to its corner'))
            seen['labels'] = [l.text() for l in dialog.findChildren(QLabel)]
            seen['title'] = dialog.windowTitle()
            return QDialog.DialogCode.Rejected
        with mock.patch.object(QDialog, 'exec', look):
            w.edit_hand_glide(0)
        self.assertEqual(seen['ends'].itemText(0), 'Back to its corner (and waits there)')
        self.assertTrue(any(t.startswith('After drawing, the hand goes back to its corner') for t in seen['labels']))
        self.assertTrue(any(t.startswith('The hand comes from where it is now') for t in seen['labels']))
        self.assertTrue(seen['title'].startswith('Hand way in and back'))

    def test_the_sticker_says_corner_and_uses_the_same_name(self):
        import stickers
        w = self.w
        item = w.add_sticker('Circle'); item['drawing'] = 'Hand: outline'
        w.select_overlay(item['id']); pump()
        self.assertEqual(stickers.hand_summary(item), 'From where the hand is → back to its corner')
        self.assertEqual(w.sticker_hand_ways.text(), 'Hand way in and back…')

    def test_the_number_boxes_show_their_whole_value(self):
        box = self.w.sticker_aspect
        need = box.fontMetrics().horizontalAdvance(box.textFromValue(box.maximum()) + box.suffix())
        self.assertGreater(box.minimumWidth(), need)


if __name__ == '__main__':
    unittest.main()
