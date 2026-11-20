"""exp.60 (the user: a sticker double-clicked opens its own window with what is around it; move,
size, rotate, colour, shadow)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


def pump(n=15):
    for _ in range(n): APP.processEvents()


def drag(widget, a, b, mods=Qt.KeyboardModifier.NoModifier):
    a, b = QPoint(int(a.x()), int(a.y())), QPoint(int(b.x()), int(b.y()))
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, mods, a)
    for i in range(1, 6):
        QTest.mouseMove(widget, QPoint(a.x() + (b.x() - a.x()) * i // 5, a.y() + (b.y() - a.y()) * i // 5))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, mods, b)
    pump(3)


class StickerWindow(unittest.TestCase):
    def setUp(self):
        import stickers
        from app import Window
        from engine import import_svg
        self.w = w = Window(); w.show(); w.resize(1500, 950)
        w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); pump()
        self.item = stickers.new('Arrow', 1., 20.); self.item.update(x=.45, y=.4)
        w.overlays.append(self.item); w.sync_titles_timeline(); pump()

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); pump()

    def run_window(self, act):
        import sticker_dialog
        old = sticker_dialog.StickerDialog.exec
        def go(d):
            d.resize(1100, 650); d.show(); pump(10)
            return act(d)
        sticker_dialog.StickerDialog.exec = go
        try:
            return self.w.open_sticker_window(self.item['id'])
        finally:
            sticker_dialog.StickerDialog.exec = old

    def test_double_click_opens_the_window_with_the_video_around(self):
        import numpy as np
        from PySide6.QtGui import QImage
        seen = {}
        def act(d):
            img = d.canvas.base.convertToFormat(QImage.Format.Format_RGB32)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
            seen['ink'] = int((a[..., :3].max(axis=2) < 120).sum())     # the drawing's dark lines
            return QDialog.DialogCode.Rejected
        import sticker_dialog
        old = sticker_dialog.StickerDialog.exec
        sticker_dialog.StickerDialog.exec = lambda d: (d.show(), pump(5), act(d))[-1]
        try:
            self.w.edit_overlay(self.item['id'])
        finally:
            sticker_dialog.StickerDialog.exec = old
        self.assertGreater(seen['ink'], 200)

    def test_turn_move_and_size_with_the_mouse(self):
        def act(d):
            c = d.canvas
            centre = c.frame()[0]
            h = c.handle()
            drag(c, h, centre + (centre - h).transposed() * 0 + type(h)(h.x() + 80, centre.y()))
            self.assertNotAlmostEqual(float(d.item.get('rotation', 0)), 0., places=0)
            x0 = d.item['x']
            centre = c.frame()[0]
            drag(c, centre, type(centre)(centre.x() + 60, centre.y()))
            self.assertGreater(d.item['x'], x0)
            s0 = d.item['size']
            QTest.mouseMove(c, QPoint(int(c.frame()[0].x()), int(c.frame()[0].y())))
            from PySide6.QtGui import QWheelEvent
            from PySide6.QtCore import QPointF
            ev = QWheelEvent(c.frame()[0], c.mapToGlobal(c.frame()[0]), QPoint(0, 0), QPoint(0, 120),
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(c, ev)
            del ev
            self.assertGreater(d.item['size'], s0)
            return QDialog.DialogCode.Accepted
        self.assertTrue(self.run_window(act))
        self.assertNotAlmostEqual(float(self.item['rotation']), 0., places=0)
        self.assertGreater(self.item['x'], .45)
        self.w.undo(); pump()
        back = self.w.find_overlay(self.item['id'])
        self.assertAlmostEqual(float(back.get('rotation', 0) or 0), 0.)

    def test_colour_and_shadow(self):
        def act(d):
            d.item['color'] = '#00AA00'; d.shadow.setChecked(True); d.shadow_distance.setValue(30)
            return QDialog.DialogCode.Accepted
        self.run_window(act)
        self.assertEqual(self.item['color'], '#00AA00')
        import overlays
        sh = overlays.shadow_of(self.item)
        self.assertIsNotNone(sh)
        self.assertAlmostEqual(sh['distance'], .03)
        self.assertTrue(self.w.sticker_shadow.isChecked())

    def test_cancel_changes_nothing(self):
        def act(d):
            d.item['rotation'] = 90; d.item['color'] = '#123456'
            return QDialog.DialogCode.Rejected
        self.assertFalse(self.run_window(act))
        self.assertEqual(float(self.item.get('rotation', 0) or 0), 0.)
        self.assertNotEqual(self.item['color'], '#123456')


class Shadow(unittest.TestCase):
    def test_a_shadow_darkens_under_the_sticker(self):
        import numpy as np
        import overlays
        import stickers
        from PySide6.QtGui import QColor, QImage
        def render(shadow):
            img = QImage(480, 270, QImage.Format.Format_ARGB32_Premultiplied); img.fill(QColor('white'))
            s = stickers.new('Circle', 0., 5.); s.update(x=.5, y=.5, size=.4)
            if shadow:
                s['shadow'] = dict(on=True, distance=.03, opacity=.8)
            overlays.paint(img, [s], 4., hands=False)
            img = img.convertToFormat(QImage.Format.Format_RGB32)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(270, img.bytesPerLine() // 4, 4)
            return int((a[..., :3].max(axis=2) < 200).sum())       # grey or black pixels
        self.assertGreater(render(True), render(False) + 200)

    def test_off_means_no_shadow(self):
        import overlays
        self.assertIsNone(overlays.shadow_of({'shadow': {'on': False}}))
        self.assertIsNone(overlays.shadow_of({}))



def tearDownModule():
    """exp.68 (Windows crashed at exit after every test passed): the windows waiting to be
    deleted are deleted now, while Qt is still running, not while Python shuts down."""
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        gc.collect()


if __name__ == '__main__':
    unittest.main()
