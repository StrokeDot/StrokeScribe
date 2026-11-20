"""exp.28 (the user, like Photoshop's Free Transform): Ctrl+T shows corner handles on the preview;
dragging a corner makes the chosen text / sticker, or the element's picture, bigger or smaller."""
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class FreeTransform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.resize(1500, 950); w.show()
        w.set_drawing(import_svg('samples/drawing.svg')); cls.settle()
        w.position = 1.; w.refresh(); cls.settle()

    @classmethod
    def tearDownClass(cls):
        cls.w.toggle_transform(False)
        cls.w.close()

    @staticmethod
    def settle():
        for _ in range(4):
            for _ in range(30):
                APP.processEvents()
            time.sleep(.08)

    def drag_corner(self, grow):
        c = self.w.canvas
        r = c._transform_rect()
        self.assertIsNotNone(r)
        start = r.bottomRight(); centre = r.center()
        end = QPointF(centre.x() + (start.x() - centre.x()) * grow, centre.y() + (start.y() - centre.y()) * grow)

        def ev(kind, p, b):
            return QMouseEvent(kind, p, p, Qt.MouseButton.LeftButton, b, Qt.KeyboardModifier.NoModifier)
        c.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton))
        c.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton))
        c.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton))
        self.settle()

    def test_the_picture_is_resized_by_its_corner(self):
        w = self.w
        w.select_overlay(None); self.settle()
        w.transform_key.activated.emit(); self.settle()
        self.assertTrue(w.transforming)
        self.assertEqual(w.transform_target()[0], 'element')
        before = w.artwork_size.value()
        self.drag_corner(.6)
        self.assertLess(w.artwork_size.value(), before * .8)
        w.transform_done_key.activated.emit()
        self.assertFalse(w.transforming)
        self.assertIsNone(w.canvas._transform_rect())

    def test_a_sticker_is_resized_by_its_corner(self):
        w = self.w
        item = w.add_sticker('Circle'); item.update(start=0., duration=30.)
        w.position = .5; w.refresh(); self.settle()
        w.toggle_transform(True); self.settle()
        for _ in range(10):                     # the box is worked out just after a paint
            if w.canvas._transform_rect() is not None: break
            w.canvas.repaint(); self.settle()
        self.assertEqual(w.transform_target()[1], item)
        size = item['size']
        self.drag_corner(1.5)
        self.assertGreater(item['size'], size * 1.25)
        w.transform_esc_key.activated.emit()
        self.assertFalse(w.transforming)

    def test_only_one_esc_shortcut_is_on_at_a_time(self):
        w = self.w
        w.toggle_transform(True)
        on = [k for k in (w.transform_esc_key, w.exit_fullscreen_key) if k.isEnabled()]
        self.assertLessEqual(len(on), 1)
        w.toggle_transform(False)


if __name__ == '__main__':
    unittest.main()
