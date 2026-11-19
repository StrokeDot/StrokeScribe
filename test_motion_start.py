"""exp.49 (the user: why is the green dot there? what does "goes back to its corner" mean?): the
Hand motion window says where its green dot comes from and has Starts (where the hand is / Free
beginning); "Goes back to where it started" returns to the green dot."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


class Back(unittest.TestCase):
    def at(self, moves, t):
        from frame_render import hand_motion_at
        return hand_motion_at(dict(_hand_moves=moves), t, (0., 0.), (0., 0., 100., 100.), (100, 100))

    def test_back_returns_to_where_it_started(self):
        stay = dict(start=0., duration=1., how='Steady', path=((.5, .5),), back=False, until=None)
        loop = dict(start=2., duration=1., how='Steady', path=((.9, .1),), back=True, until=None)
        self.assertEqual(self.at((stay, loop), 1.5), (50., 50.))           # parked at its point
        self.assertAlmostEqual(self.at((stay, loop), 2.999)[0], 50., delta=1.)   # back to it
        self.assertEqual(self.at((stay, loop), 3.5), (50., 50.))           # and stays there
        lone = dict(loop, start=0.)
        self.assertIsNone(self.at((lone,), 1.5))                            # nothing before: its corner


class Window(unittest.TestCase):
    def test_the_green_dot_is_explained_and_can_be_put(self):
        import camera_clips
        from app import Window
        from engine import import_svg
        w = Window(); w.show()
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(40): APP.processEvents()
            w.hand_rest.setChecked(True); w.preview_scope.setCurrentIndex(1)
            for _ in range(40): APP.processEvents()
            w.board_frames = lambda: [(0., 0., 1.), (0., 0., 1.)]
            end = max(b for a, b in w.hand_busy_spans())
            first = camera_clips.new_clip('Hand motion', round(end + .2, 2))
            first.update(duration=.6, back=False, path=[[.5, .5], [.3, .4]])
            second = camera_clips.new_clip('Hand motion', round(end + 1.5, 2)); second['duration'] = .6
            w.cameras += [first, second]; w.refresh(); APP.processEvents()
            seen = {}
            real = QDialog.exec

            def fake(d):
                seen['note'] = d.note.text(); seen['ends'] = [d.end.itemText(i) for i in range(d.end.count())]
                seen['movable'] = d.canvas.movable_start
                d.starts.setCurrentIndex(1)                                   # Free beginning
                seen['free_movable'] = d.canvas.movable_start
                W, H = 960, round(960 * w.board_aspect())
                # exp.50 (the user: the green dot did not drag): dragged with the mouse
                from PySide6.QtCore import Qt
                from PySide6.QtGui import QMouseEvent
                c = d.canvas; c.resize(800, 500)
                keys_before = list(c.keys)

                def ev(kind, p, b):
                    return QMouseEvent(kind, p, p, Qt.MouseButton.LeftButton, b, Qt.KeyboardModifier.NoModifier)
                c.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, c.to_widget(c.a), Qt.MouseButton.LeftButton))
                target = c.to_widget((.7 * W, .2 * H))
                c.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, target, Qt.MouseButton.LeftButton))
                c.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton))
                seen['keys_kept'] = list(c.keys) == keys_before
                return QDialog.DialogCode.Accepted
            QDialog.exec = fake
            try:
                w.edit_hand_motion(second['id'])
            finally:
                QDialog.exec = real
            self.assertIn('Hand motion left the hand', seen['note'])
            self.assertIn('Goes back to where it started', seen['ends'])
            self.assertTrue(seen['free_movable'])
            self.assertTrue(seen['keys_kept'])                                # its points stay put
            self.assertAlmostEqual(first['path'][-1][0], .7, delta=.01)       # the spot it came from moved
            self.assertAlmostEqual(first['path'][-1][1], .2, delta=.01)
            self.assertEqual(second.get('hand_begin'), 'free')
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
