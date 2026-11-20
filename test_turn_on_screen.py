"""exp.61 (the user: Ctrl+T turns too, not only resizes): the Ctrl+T box on the preview has a
round handle that turns the chosen sticker / text / picture on top."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def pump(n=20):
    for _ in range(n): APP.processEvents()


class TurnOnScreen(unittest.TestCase):
    def setUp(self):
        import stickers
        from app import Window
        from engine import import_svg
        self.w = w = Window(); w.show(); w.resize(1500, 950)
        w.set_drawing(import_svg('samples/drawing.svg')); pump()
        self.item = stickers.new('Arrow', 0., 30.); self.item.update(x=.5, y=.5)
        w.overlays.append(self.item); w.select_overlay(self.item['id']); pump()
        w.position = .5; w.refresh(); pump(40)
        w.toggle_transform(True); pump(20)

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); pump()

    def drag(self, a, b, mods=Qt.KeyboardModifier.NoModifier):
        """A real drag; the moves carry the keys held (QTest.mouseMove does not)."""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        c = self.w.canvas
        a, b = QPoint(round(a.x()), round(a.y())), QPoint(round(b.x()), round(b.y()))
        QTest.mousePress(c, Qt.MouseButton.LeftButton, mods, a)
        for i in range(1, 7):
            q = QPointF(a.x() + (b.x() - a.x()) * i / 6, a.y() + (b.y() - a.y()) * i / 6)
            ev = QMouseEvent(QEvent.Type.MouseMove, q, c.mapToGlobal(q), Qt.MouseButton.NoButton,
                             Qt.MouseButton.LeftButton, mods)
            QApplication.sendEvent(c, ev); del ev
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton, mods, b); pump()

    def test_the_handle_turns_the_sticker_and_one_undo_puts_it_back(self):
        c = self.w.canvas
        handle = c._rotate_handle()
        self.assertIsNotNone(handle)
        centre = c._transform_rect().center()
        self.drag(handle, QPointF(centre.x() + 120, centre.y()))          # a quarter turn to the right
        self.assertAlmostEqual(float(self.item['rotation']), 90., delta=12)
        self.w.undo(); pump()
        self.assertAlmostEqual(float(self.w.find_overlay(self.item['id']).get('rotation', 0) or 0), 0.)

    def test_shift_turns_in_steps_of_15(self):
        c = self.w.canvas
        handle = c._rotate_handle(); centre = c._transform_rect().center()
        self.drag(handle, QPointF(centre.x() + 100, centre.y() - 37), Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(float(self.item['rotation']) % 15, 0.)

    def test_over_the_handle_the_cursor_is_a_turning_arrow(self):
        import app
        c = self.w.canvas
        h = c._rotate_handle()
        QTest.mouseMove(c, QPoint(round(h.x()), round(h.y()))); pump(3)
        self.assertEqual(c.cursor().pixmap().cacheKey(), app.rotate_cursor().pixmap().cacheKey())

    def test_corners_still_resize(self):
        c = self.w.canvas
        r = c._transform_rect(); s0 = float(self.item['size'])
        corner = c._turned(r)[2]
        self.drag(corner, QPointF(corner.x() + 60, corner.y() + 30))
        self.assertGreater(float(self.item['size']), s0)

    def test_an_element_has_no_turn_handle(self):
        self.w.select_overlay(''); pump(20)
        self.assertIsNone(self.w.canvas._rotate_handle())

    def test_a_turned_text_is_drawn_turned(self):
        import numpy as np
        import overlays
        from PySide6.QtGui import QColor, QImage
        def ink(turn):
            img = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied); img.fill(QColor('white'))
            t = overlays.new_text('WIDE TITLE', 0., 5.); t.update(x=.5, y=.5, size=.08, rotation=turn,
                                                                   effect_in='None')
            overlays.paint(img, [t], 2.)
            rgb = img.convertToFormat(QImage.Format.Format_RGB32)          # kept while it is read
            a = np.frombuffer(rgb.constBits(), np.uint8).reshape(400, rgb.bytesPerLine() // 4, 4)
            rows = np.where((a[..., :3].min(axis=2) < 128).any(axis=1))[0]
            return rows.max() - rows.min()
        self.assertGreater(ink(90), ink(0) * 2)       # turned on its side: much taller


if __name__ == '__main__':
    unittest.main()
