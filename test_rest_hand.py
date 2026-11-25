"""exp.68 (the user: a resting hand, the left hand; under or over the pictures, the writing hand
always on top; the photos are the user's own, kept in the project, mirrored)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def pump(n=20):
    for _ in range(n): APP.processEvents()


def pixels(img):
    import numpy as np
    rgb = img.convertToFormat(QImage.Format.Format_RGB32)
    a = np.frombuffer(rgb.constBits(), np.uint8).reshape(rgb.height(), rgb.bytesPerLine() // 4, 4)[:, :rgb.width(), :3]
    return a.astype(int).copy()


class CutOut(unittest.TestCase):
    def test_the_white_around_goes_the_white_inside_stays(self):
        import numpy as np
        import rest_hands
        img = QImage(200, 160, QImage.Format.Format_ARGB32); img.fill(QColor('white'))
        p = QPainter(img); p.fillRect(40, 30, 120, 100, QColor('#a0602c')); p.fillRect(80, 60, 30, 30, QColor('white')); p.end()
        out = rest_hands.cut_out(img).convertToFormat(QImage.Format.Format_ARGB32)
        a = np.frombuffer(out.constBits(), np.uint8).reshape(out.height(), out.bytesPerLine() // 4, 4)[:, :out.width()]
        self.assertLess(out.width(), 130)                      # trimmed to the hand
        self.assertEqual(int(a[0, 0, 3]), 0)                    # the white around: gone
        self.assertEqual(int(a[out.height() // 2, out.width() // 2, 3]), 255)   # the white inside: kept


class Layers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        import rest_hands
        cls.w = w = Window(); w.show(); w.resize(1400, 900)
        w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.preview_scope.setCurrentIndex(1); pump()
        block = QImage(40, 40, QImage.Format.Format_ARGB32); block.fill(QColor('#ff0000'))
        cls.item = rest_hands.new(rest_hands.png_data(block), 'block')
        cls.item.update(x=.5, y=.5, size=3., effect_in='None', effect_out='None', start=0., duration=60.)
        it = w.timeline_layout().items[0]
        cls.t = it.start + it.length * .55                     # element 1 being drawn by the hand

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def painted(self):
        """The plain frame's painted pixels (its background is clear)."""
        import numpy as np
        w = self.w
        w.overlays[:] = []
        w.project_changes.mark_changed(); w.clear_frames(); w.__dict__.pop('_memo', None); w._scene_cache = {}
        img = w.render_view(self.t / w.timeline_layout().total, 480).convertToFormat(QImage.Format.Format_ARGB32)
        a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()]
        return (a[..., 3] > 200) & (a[..., :3].max(axis=2) < 120)

    def frame(self, layer=None):
        w = self.w
        w.overlays[:] = [dict(self.item, layer=layer)] if layer else []
        w.project_changes.mark_changed(); w.clear_frames()       # as the app does after a change
        w.__dict__.pop('_memo', None); w._scene_cache = {}
        lay = w.timeline_layout()
        return pixels(w.render_view(self.t / lay.total, 480))

    @staticmethod
    def red(a):
        # the bytes of an RGB32 picture are blue, green, red
        return (a[..., 2] > 200) & (a[..., 1] < 60) & (a[..., 0] < 60)

    def test_over_the_pictures_but_under_the_writing_hand(self):
        import numpy as np
        plain, over = self.frame(), self.frame('over')
        uncovered = ~self.red(over)
        self.assertGreater(int(uncovered.sum()), 200)          # the writing hand is still seen
        same = np.abs(over - plain).sum(axis=2) < 30
        self.assertGreater(float(same[uncovered].mean()), .9)  # and it is the plain frame's hand

    def test_under_the_pictures(self):
        drawn = self.painted()                                 # the drawing's dark lines
        under = self.frame('under')
        self.assertGreater(int(drawn.sum()), 100)
        self.assertLess(float(self.red(under)[drawn].mean()), .1)   # the lines are over it
        self.assertGreater(float(self.red(under).mean()), .3)       # and it is there

    def test_a_resting_hand_makes_the_frame_with_its_layers(self):
        self.w.overlays[:] = [dict(self.item)]
        self.w.__dict__.pop('_memo', None)
        self.assertFalse(self.w.timeline_layout().sequential)


class AddingOne(unittest.TestCase):
    def test_the_button_and_the_window(self):
        from unittest import mock
        from app import Window
        from engine import import_svg
        from PySide6.QtWidgets import QComboBox, QDialog, QMenu
        import rest_hands
        w = Window(); w.show()
        try:
            w.set_drawing(import_svg('samples/drawing.svg')); pump()
            self.assertTrue(w.add_rest_hand_button.toolTip().startswith('Resting hand'))
            photo = tempfile.mktemp(suffix='.png')
            img = QImage(120, 120, QImage.Format.Format_ARGB32); img.fill(QColor('white'))
            p = QPainter(img); p.fillRect(30, 20, 60, 90, QColor('#a0602c')); p.end(); img.save(photo)

            choices = w.rest_hand_choices()
            self.assertEqual([c[0] for c in choices if c[1] is None], list(rest_hands.POSES))   # both poses
            first = next(c[1] for c in choices if c[0] == 'Choose a photo…')
            with mock.patch('app.QFileDialog.getOpenFileName', return_value=(photo, '')):
                item = w.add_rest_hand(choice=first)
            again = [c[0] for c in w.rest_hand_choices()]
            self.assertIn('Photo: ' + item['photo_name'], again)                  # the photo again, no file
            self.assertTrue(rest_hands.is_rest_hand(item))
            self.assertTrue(item['flip'])                       # mirrored: the left hand
            self.assertEqual(item['layer'], 'under')

            def over(dialog):
                box = next(b for b in dialog.findChildren(QComboBox) if b.findData('over') >= 0)
                box.setCurrentIndex(box.findData('over'))
                return QDialog.DialogCode.Accepted
            with mock.patch.object(QDialog, 'exec', over):
                w.edit_overlay(item['id'])
            self.assertEqual(item['layer'], 'over')
            w.undo(); pump()
            self.assertEqual(w.find_overlay(item['id'])['layer'], 'under')
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
