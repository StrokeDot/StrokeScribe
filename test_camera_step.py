"""exp.54 (the user: a camera position as the next element, anywhere on the board, with or
without anything there; stickers should count for Match camera): + Add element → Camera
position: a step with no picture and no hand, whose camera goes where it is set."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


class CameraStep(unittest.TestCase):
    def test_a_camera_step_anywhere(self):
        import numpy as np
        from app import Window
        from engine import import_svg
        from timeline_model import state_at
        w = Window(); w.show()
        real = QDialog.exec
        seen = {}

        def fake(d):
            seen['match'] = [d.match.itemText(i) for i in range(d.match.count())]
            f = list(d.board.frame); d.board.frame = [f[0] + 3., f[1] + .4, f[2] * 1.3]   # an empty spot
            return QDialog.DialogCode.Accepted
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(20): APP.processEvents()
            w.hand_rest.setChecked(True)
            w.add_sticker('Circle')
            QDialog.exec = fake
            self.assertTrue(w.add_camera_step())
            for _ in range(20): APP.processEvents()
            QDialog.exec = real
            step = w.scenes[1]
            self.assertTrue(step['camera_step'] and step['art_off'] and step['hand_off'])
            self.assertEqual(w.scene_label(1), 'Camera')
            self.assertTrue(any(m.startswith('Sticker · Circle') for m in seen['match']))   # stickers count
            self.assertAlmostEqual(step['board']['view'][2], seen and step['board']['view'][2])
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(20): APP.processEvents()
            w.preview_scope.setCurrentIndex(1)
            for _ in range(20): APP.processEvents()
            lay = w.timeline_layout()
            self.assertEqual(len(lay.items), 3)
            self.assertNotIn(1, [m[4] for m in w.hand_marks()])                   # no hand for it
            mid = lay.items[1].start + lay.items[1].length / 2
            img = w.timeline_frame(state_at(lay, mid), 480, 270, mid)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(270, img.bytesPerLine() // 4, 4)[:, :480]
            self.assertEqual(len(np.unique(a.reshape(-1, 4)[:, :3], axis=0)), 1)   # the empty spot, nothing drawn
            end = lay.items[2].start + lay.items[2].length - .1
            img = w.timeline_frame(state_at(lay, end), 480, 270, end)
            b = np.frombuffer(img.constBits(), np.uint8).reshape(270, img.bytesPerLine() // 4, 4)[:, :480]
            self.assertGreater(len(np.unique(b.reshape(-1, 4)[:, :3], axis=0)), 5)   # the next element shows
        finally:
            QDialog.exec = real
            w.close()


if __name__ == '__main__':
    unittest.main()
