"""exp.239 (UI clean-up step 3): small notices that fade, and Ctrl+K command search."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMainWindow

import command_palette
import toast

APP = QApplication.instance() or QApplication([])


class Notices(unittest.TestCase):
    def setUp(self):
        self.win = QMainWindow(); self.win.resize(900, 600); self.win.show()

    def tearDown(self):
        self.win.close()

    def test_a_notice_shows_in_the_corner_and_stacks(self):
        first = toast.notify(self.win, 'One', seconds=30)
        second = toast.notify(self.win, 'Two', 'warning', seconds=30)
        APP.processEvents()
        self.assertTrue(first.isVisible() and second.isVisible())
        self.assertLess(first.y(), second.y())                       # the newest at the bottom
        self.assertEqual(second.x() + second.width(), self.win.width() - toast.MARGIN)

    def test_the_same_notice_twice_shows_once(self):
        a = toast.notify(self.win, 'Same', seconds=30)
        b = toast.notify(self.win, 'Same', seconds=30)
        self.assertIs(a, b)

    def test_at_most_three_stay(self):
        for k in range(5):
            toast.notify(self.win, f'n{k}', seconds=30)
        live = [t for t in self.win._toasts if not t._closing]
        self.assertEqual(len(live), toast.MAX_SHOWN)


class Commands(unittest.TestCase):
    def test_menu_commands_are_found_by_words_in_any_order(self):
        win = QMainWindow()
        menu = win.menuBar().addMenu('&File')
        hits = []
        menu.addAction('Save project\tCtrl+S', lambda: hits.append('save'))
        menu.addAction('Export animation', lambda: hits.append('export'))
        found = command_palette.menu_commands(win)
        labels = [f[0] for f in found]
        self.assertIn('File › Save project', labels)
        self.assertEqual(dict((f[0], f[1]) for f in found)['File › Save project'], 'Ctrl+S')
        self.assertTrue(command_palette.matches('File › Export animation', 'anim exp'))
        self.assertFalse(command_palette.matches('File › Export animation', 'camera'))
        palette = command_palette.CommandPalette(win)
        palette.search.setText('save')
        self.assertEqual(palette.list.count(), 1)
        palette.run(palette.list.item(0))
        for _ in range(5): APP.processEvents()
        self.assertEqual(hits, ['save'])


if __name__ == '__main__':
    unittest.main()
