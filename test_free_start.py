"""exp.39 (the user): the green dot (where the next hand comes from) is where the hand really is
(a Free ending, a Hand motion that stays), and dragging it moves that spot."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


class Canvas(unittest.TestCase):
    def test_the_green_dot_can_be_dragged_and_the_keyframes_stay(self):
        from glide_path_dialog import PathCanvas
        frame = QImage(400, 225, QImage.Format.Format_ARGB32); frame.fill(QColor('white'))
        c = PathCanvas(frame, (50., 50.), (300., 150.), [(.5, .2)])
        c.resize(800, 520)

        def ev(kind, p, b):
            return QMouseEvent(kind, p, p, Qt.MouseButton.LeftButton, b, Qt.KeyboardModifier.NoModifier)
        c.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, c.to_widget(c.a), Qt.MouseButton.LeftButton))
        self.assertNotEqual(c.drag, 'start')                    # not movable: it stays
        c.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, c.to_widget(c.a), Qt.MouseButton.NoButton))
        c.movable_start = True
        before = c.points()[1]
        c.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, c.to_widget(c.a), Qt.MouseButton.LeftButton))
        c.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, c.to_widget((120., 180.)), Qt.MouseButton.LeftButton))
        c.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, c.to_widget((120., 180.)), Qt.MouseButton.NoButton))
        self.assertAlmostEqual(c.a[0], 120., delta=1); self.assertAlmostEqual(c.a[1], 180., delta=1)
        after = c.points()[1]
        self.assertAlmostEqual(after[0], before[0], delta=.5); self.assertAlmostEqual(after[1], before[1], delta=.5)


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
        w.board_frames = lambda: [(0., 0., 1.), (0., 0., 1.)]          # both on one page

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def fresh(self):
        self.w._scene_cache = {}; self.w.__dict__.pop('_memo', None)

    def start_of_next(self):
        self.fresh()
        snap = self.w.glide_snapshot(1, 'in')
        self.assertIsInstance(snap, dict)
        W, H = snap['size']
        return snap, (snap['a'][0] / W, snap['a'][1] / H)

    def accept_with(self, pending):
        """The Hand window of element 2, OK'd after the green dot was dragged (Edit path)."""
        w = self.w
        real = QDialog.exec

        def fake(dialog):
            w._start_pending = pending
            return QDialog.DialogCode.Accepted
        QDialog.exec = fake
        try:
            w.edit_hand_glide(1)
        finally:
            QDialog.exec = real

    def tearDown(self):
        w = self.w
        w.cameras[:] = [c for c in w.cameras if c.get('kind') != 'Hand motion']
        for s in w.scenes:
            s.pop('hand_flow', None); s.pop('hand_end', None)
        self.fresh()

    def test_a_corner(self):
        snap, _ = self.start_of_next()
        self.assertEqual(self.w.way_in_source(1, snap['times'][0]), ('corner', None))

    def test_b_free_ending_before(self):
        w = self.w
        w.scenes[0]['hand_flow'] = 'free'; w.scenes[0]['hand_end'] = [.15, .25]
        snap, spot = self.start_of_next()
        self.assertEqual(w.way_in_source(1, snap['times'][0]), ('end', 0))
        self.assertAlmostEqual(spot[0], .15, delta=.01); self.assertAlmostEqual(spot[1], .25, delta=.01)
        self.accept_with(('end', 0, (.6, .7)))                   # dragged the green dot
        self.assertEqual(w.scenes[0]['hand_end'], [.6, .7])
        _, spot = self.start_of_next()
        self.assertAlmostEqual(spot[0], .6, delta=.01); self.assertAlmostEqual(spot[1], .7, delta=.01)

    def test_c_hand_motion_that_stays(self):
        import camera_clips
        w = self.w
        lay = w.timeline_layout()
        c = camera_clips.new_clip('Hand motion', round(lay.items[0].end + .05, 2))
        c['duration'] = .8; c['back'] = False; c['path'] = [[.5, .5], [.3, .4]]
        w.cameras.append(c)
        snap, spot = self.start_of_next()
        kind, clip = w.way_in_source(1, snap['times'][0])
        self.assertEqual((kind, clip['id']), ('motion', c['id']))
        self.assertAlmostEqual(spot[0], .3, delta=.01); self.assertAlmostEqual(spot[1], .4, delta=.01)
        self.accept_with(('motion', c['id'], (.8, .2)))
        self.assertEqual(c['path'][-1], [.8, .2]); self.assertEqual(c['path'][0], [.5, .5])
        _, spot = self.start_of_next()
        self.assertAlmostEqual(spot[0], .8, delta=.01); self.assertAlmostEqual(spot[1], .2, delta=.01)


if __name__ == '__main__':
    unittest.main()
