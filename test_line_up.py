"""exp.33 (the user, like Filmora): dragged clips snap to the playhead and the other clips; the
right-click menu lines a clip up with another one (start together, when it ends, end together)."""
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu

APP = QApplication.instance() or QApplication([])


def settle():
    for _ in range(3):
        for _ in range(30):
            APP.processEvents()
        time.sleep(.05)


class LineUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.resize(1500, 950); w.show()
        w.set_drawing(import_svg('samples/drawing.svg')); settle()
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); settle()
        w.preview_scope.setCurrentIndex(1); settle()
        cls.item = w.add_sticker('Circle'); settle()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def test_a_dragged_sticker_snaps_to_an_element_end(self):
        t = self.w.stage_timeline
        end = t.items[0][2] + t.items[0][3]
        pps = t._px_per_sec()
        start, length = t._snap_clip(self.item['id'], 'move', end + 3. / pps, 2., pps)
        self.assertAlmostEqual(start, end)
        self.assertAlmostEqual(t._clip_snap, end)
        start, _ = t._snap_clip(self.item['id'], 'move', end + 40. / pps, 2., pps)   # far: free
        self.assertAlmostEqual(start, end + 40. / pps)
        self.assertIsNone(t._clip_snap)

    def actions(self, menu):
        out = {}
        for a in menu.actions():
            if a.menu():
                for name, act in self.actions(a.menu()).items():
                    out[a.text() + ' > ' + name] = act
            elif a.text():
                out[a.text()] = a
        return out

    def test_line_up_a_sticker_with_an_element(self):
        w, t = self.w, self.w.stage_timeline
        el = t.items[1]
        moved = []

        def choose(words):
            self.menu = QMenu()                      # one menu per choice, as in the app
            t._line_up_skip = ('overlay', self.item['id'])
            t._line_up_menu(self.menu, (0., 2.), lambda new: moved.append(new))
            acts = self.actions(self.menu)
            acts[next(k for k in acts if k.startswith(f'Line up with > {el[0] + 1} · ') and words in k)].trigger()
        choose('Start when it ends')
        self.assertAlmostEqual(moved[-1], el[2] + el[3])
        choose('End together')
        self.assertAlmostEqual(moved[-1], el[2] + el[3] - 2.)
        choose('Start together')
        self.assertAlmostEqual(moved[-1], el[2])

    def test_the_menu_moves_the_sticker_in_the_window(self):
        w, t = self.w, self.w.stage_timeline
        oid = self.item['id']
        t.overlay_changed.emit(oid, 7.25, float(self.item['duration']), int(self.item['track']))
        t.overlay_done.emit(oid); settle()
        self.assertAlmostEqual(w.find_overlay(oid)['start'], 7.25)


if __name__ == '__main__':
    unittest.main()
