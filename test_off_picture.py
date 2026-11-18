"""exp.40 (the user): a hand whose spot is outside the picture came from far away (too fast) and
the Edit path window did not show the green dot. Now: every dot is in view; a hand from outside
the picture comes in from below the middle; its green dot can be dragged (its own start)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


class Canvas(unittest.TestCase):
    def test_every_dot_is_in_view(self):
        from glide_path_dialog import PathCanvas
        frame = QImage(400, 225, QImage.Format.Format_ARGB32); frame.fill(QColor('white'))
        c = PathCanvas(frame, (200., 2000.), (100., 100.), [(.5, .2)])     # the start far below
        c.resize(800, 520)
        for q in [c.a, c.b] + list(c.points()):
            p = c.to_widget(q)
            self.assertTrue(0 <= p.x() <= c.width() and 0 <= p.y() <= c.height(), q)
        c2 = PathCanvas(frame, (300., 150.), (100., 100.), [])
        c2.resize(800, 520)
        p = c2.to_widget((0., 0.)); q = c2.to_widget((400., 225.))
        self.assertGreater(q.x() - p.x(), 400)             # nothing far: the video stays big


class InTheWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg'))
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(40): APP.processEvents()
        w.hand_rest.setChecked(True)
        w.preview_scope.setCurrentIndex(1)
        for _ in range(40): APP.processEvents()
        w.board_frames = lambda: [(0., 0., 1.), (0., 0., 1.)]

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def fresh(self):
        self.w._scene_cache = {}; self.w.__dict__.pop('_memo', None)

    def test_a_hand_left_outside_comes_in_from_below_the_middle(self):
        import camera_clips
        w = self.w
        snap = w.glide_snapshot(1, 'in')
        self.assertFalse(snap['outside'])                      # its corner: as before
        lay = w.timeline_layout()
        c = camera_clips.new_clip('Hand motion', round(lay.items[0].end + .05, 2))
        c['duration'] = .8; c['back'] = False; c['path'] = [[.5, .5], [.1, 2.2]]     # far below
        w.cameras.append(c); self.fresh()
        snap = w.glide_snapshot(1, 'in')
        W, H = snap['size']
        self.assertTrue(snap['outside'])
        self.assertAlmostEqual(snap['a'][0], W / 2., delta=1)
        self.assertGreater(snap['a'][1], H); self.assertLess(snap['a'][1], H * 1.4)   # just below

        real = QDialog.exec

        def fake(dialog):
            w._start_pending = ('own', 1, (.2, 1.1))           # dragged the green dot
            return QDialog.DialogCode.Accepted
        QDialog.exec = fake
        try:
            w.edit_hand_glide(1)
        finally:
            QDialog.exec = real
        self.assertEqual(w.scenes[1]['hand_start'], [.2, 1.1])
        self.fresh()
        snap = w.glide_snapshot(1, 'in')
        self.assertAlmostEqual(snap['a'][0], .2 * W, delta=1); self.assertAlmostEqual(snap['a'][1], 1.1 * H, delta=1)
        w.cameras.remove(c); self.fresh()                      # back in its corner: its own start is not used
        snap = w.glide_snapshot(1, 'in')
        self.assertFalse(snap['outside'])
        self.assertLess(snap['a'][1], H)
        w.scenes[1].pop('hand_start', None); self.fresh()


if __name__ == '__main__':
    unittest.main()
