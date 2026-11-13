"""exp.243 (the user: Ctrl+Z put Edge fade back but its bar did not move; an undone Animation
change left the picture as it was): undo tells every control it changed, as a hand change."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QSlider

APP = QApplication.instance() or QApplication([])


class UndoFollows(unittest.TestCase):
    def setUp(self):
        from app import Window
        self.w = Window()
        self.addCleanup(self.w.close)

    def commit(self):
        APP.processEvents()
        if self.w.history_timer.isActive():
            self.w.commit_history()

    def test_the_bar_beside_a_number_follows_undo_and_redo(self):
        w = self.w
        spin = w.ink_edge_size
        bar = spin.parent().findChildren(QSlider)[0]
        start = spin.value()
        spin.setValue(start + 20); self.commit()
        self.assertEqual(bar.value(), round(start + 20))
        w.undo(); APP.processEvents()
        self.assertEqual(spin.value(), start)
        self.assertEqual(bar.value(), round(start))
        w.redo(); APP.processEvents()
        self.assertEqual(bar.value(), round(start + 20))

    def test_undo_runs_the_change_handlers_but_records_nothing(self):
        w = self.w
        heard = []
        w.ink_edges.currentIndexChanged.connect(lambda i: heard.append(i))
        first = w.ink_edges.currentIndex()
        w.ink_edges.setCurrentIndex((first + 1) % w.ink_edges.count()); self.commit()
        heard.clear()
        steps = len(w.history.undo_stack) if hasattr(w.history, 'undo_stack') else None
        w.undo(); APP.processEvents()
        self.assertEqual(w.ink_edges.currentIndex(), first)
        self.assertEqual(heard, [first])                       # told once, like a hand change
        self.assertFalse(w.history_timer.isActive())            # and not a new undo step
        if steps is not None:
            self.assertLessEqual(len(w.history.undo_stack), steps)


if __name__ == '__main__':
    unittest.main()
