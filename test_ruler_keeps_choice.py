"""exp.58 (the user: changing a sticker's settings, a click on the timeline let go of it and the
camera element there was chosen instead): the ruler only moves the playhead; what is chosen stays."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def pump(n=20):
    for _ in range(n): APP.processEvents()


class RulerKeepsTheChoice(unittest.TestCase):
    def setUp(self):
        import stickers
        from app import Window
        from engine import import_svg
        self.w = w = Window(); w.show(); w.resize(1600, 1000)
        w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.set_camera = lambda k=None: None
        w.add_camera_step(); pump()
        w.preview_scope.setCurrentIndex(1); pump()
        it = w.timeline_layout().items[2]
        self.sticker = stickers.new('Clock', it.start - .5, 4.)
        w.overlays.append(self.sticker); w.sync_titles_timeline(); pump()
        self.camera_time = it.start + .5

    def tearDown(self):
        self.w.close()

    def click(self, x, y):
        QTest.mouseClick(self.w.stage_timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(x), int(y))); pump()

    def test_a_sticker_stays_chosen(self):
        w, tl = self.w, self.w.stage_timeline
        tl_item = next(o for o in tl.overlays if o.get('id') == self.sticker['id'])
        r = tl._overlay_rect(tl_item)
        self.click(r.center().x(), r.center().y())            # the user chooses the sticker
        self.assertEqual(w.selected_overlay, self.sticker['id'])
        x = tl._x(tl.title_offset + self.camera_time)
        before = w.position
        self.click(x, tl._rows()[0] - 6)                       # the ruler, over the camera element
        self.assertEqual(w.selected_overlay, self.sticker['id'])
        self.assertTrue(tl._something_else_chosen())          # the camera element does not look chosen
        self.assertNotAlmostEqual(w.position, before)          # the playhead moved

    def test_a_camera_clip_stays_chosen(self):
        w, tl = self.w, self.w.stage_timeline
        clip = w.add_camera_clip('Zoom in', at=.5); pump()
        self.assertEqual(w.selected_camera, clip['id'])
        self.click(tl._x(tl.title_offset + self.camera_time), tl._rows()[0] - 6)
        self.assertEqual(w.selected_camera, clip['id'])


if __name__ == '__main__':
    unittest.main()
