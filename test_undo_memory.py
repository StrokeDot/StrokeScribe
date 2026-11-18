"""exp.42 (the user: a lot of memory): undo steps share the copy of an element that did not
change (each step used to keep a whole new copy), and undo still brings back the right state."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class UndoMemory(unittest.TestCase):
    def test_unchanged_element_is_shared_and_undo_still_works(self):
        from app import Window
        from engine import import_svg
        w = Window(); w.show()
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(20): APP.processEvents()
            for i in range(4):
                w.record_structure(f'step {i}')
            steps = [u[1][u[2]]['state'] for u in w.project_undo[-4:]]
            self.assertTrue(all(s['drawing'] is steps[0]['drawing'] for s in steps))   # one copy
            count = len(w.drawing.strokes)
            w.record_structure('before a change')
            w.drawing.strokes.pop()                                # a real change to the element
            w.record_structure('after a change')
            last, before = w.project_undo[-1][1][0]['state'], w.project_undo[-2][1][0]['state']
            self.assertIsNot(last['drawing'], before['drawing'])
            self.assertEqual(len(before['drawing']['strokes']), count)
            self.assertEqual(len(last['drawing']['strokes']), count - 1)
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
