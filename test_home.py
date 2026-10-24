"""exp.107: the Home screen (new project, open, projects as cards)."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


class WhenTests(unittest.TestCase):
    def test_times_read_naturally(self):
        from home_screen import when
        now = time.mktime((2026, 10, 24, 15, 0, 0, 0, 0, -1))
        self.assertEqual(when(now - 10, now), 'Just now')
        self.assertEqual(when(now - 300, now), '5 minutes ago')
        self.assertTrue(when(now - 7200, now).startswith('Today'))
        self.assertTrue(when(now - 86400, now).startswith('Yesterday'))
        self.assertIn('2026', when(now - 86400 * 20, now))


@unittest.skipIf(SKIP, 'needs Qt')
class HomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {'STROKESCRIBE_PROJECTS_FOLDER': str(self.tmp / 'projects')})
        self.env.start()
        (self.tmp / 'projects').mkdir()
        from app import Window
        from engine import import_svg
        self.w = Window(); self.w.resize(1300, 800); self.w.show()
        self.w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        self.app.processEvents()

    def tearDown(self):
        self.w.close(); self.app.processEvents()
        self.env.stop()

    def save_as(self, name):
        from PySide6.QtWidgets import QFileDialog
        target = str(self.tmp / 'projects' / name)
        with mock.patch.object(QFileDialog, 'getSaveFileName', return_value=(target, '')):
            return self.w.save_project(save_as=True)

    def test_home_covers_the_window_and_lists_saved_projects(self):
        path = self.save_as('My first animation.strokescribe')
        self.assertTrue(path)
        home = self.w.show_home()
        self.app.processEvents()
        self.assertTrue(self.w.home_visible())
        self.assertEqual(home.geometry(), self.w.centralWidget().rect())
        names = [c.info.get('name') for c in home.visible_cards() if not c.new]
        self.assertIn('My first animation', names)
        self.assertTrue(home.visible_cards()[0].new)            # "New project" comes first
        card = [c for c in home.cards if not c.new and c.info['name'] == 'My first animation'][0]
        self.assertIsNotNone(card.preview)                      # saving kept a preview picture

    def test_search_filters_the_cards(self):
        self.save_as('Cats.strokescribe'); self.save_as('Dogs.strokescribe')
        home = self.w.show_home()
        home.search.setText('cat'); self.app.processEvents()
        names = [c.info['name'] for c in home.visible_cards() if not c.new]
        self.assertEqual(names, ['Cats'])

    def test_opening_a_card_opens_the_project_and_leaves_home(self):
        path = self.save_as('Open me.strokescribe')
        home = self.w.show_home()
        with mock.patch.object(type(self.w), 'confirm_leave_project', return_value=True):
            home.open_requested.emit(str(path))
        self.app.processEvents()
        self.assertFalse(self.w.home_visible())
        self.assertEqual(Path(self.w.project_path).name, 'Open me.strokescribe')

    def test_new_project_leaves_home(self):
        home = self.w.show_home()
        with mock.patch.object(type(self.w), 'confirm_leave_project', return_value=True):
            home.new_requested.emit()
        self.app.processEvents()
        self.assertFalse(self.w.home_visible())
        self.assertIsNone(self.w.project_path)

    def test_save_defaults_to_the_projects_folder(self):
        from PySide6.QtWidgets import QFileDialog
        self.w.project_path = None
        with mock.patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')) as ask:
            self.w.save_project()
        self.assertTrue(ask.call_args[0][2].startswith(str(self.tmp / 'projects')))

    def test_home_follows_the_window_size(self):
        home = self.w.show_home()
        self.w.resize(1500, 900); self.app.processEvents()
        self.assertEqual(home.geometry(), self.w.centralWidget().rect())

    def test_x_in_a_project_goes_back_home(self):
        self.save_as('Keep open.strokescribe')
        self.w.close_to_home = True
        self.w.close(); self.app.processEvents()
        self.assertTrue(self.w.isVisible())
        self.assertTrue(self.w.home_visible())
        self.w.close_to_home = False                 # let tearDown close it

    def test_exit_closes_even_from_a_project(self):
        self.w.close_to_home = True
        with mock.patch.object(type(self.w), 'confirm_leave_project', return_value=True):
            self.w.quit_app()
        self.app.processEvents()
        self.assertFalse(self.w.isVisible())

    def test_projects_without_a_preview_get_one(self):
        import home_screen
        path = self.save_as('Old one.strokescribe')
        home_screen.preview_path(path).unlink()
        self.assertTrue(home_screen.needs_preview(path))
        self.assertTrue(home_screen.make_preview(path, self.w.hand))
        self.assertFalse(home_screen.needs_preview(path))
        home_screen.preview_path(path).unlink()
        home = self.w.show_home()
        from PySide6.QtTest import QTest
        for _ in range(60):
            QTest.qWait(50)
            if not home_screen.needs_preview(path):
                break
        card = [c for c in home.cards if not c.new and c.info['name'] == 'Old one'][0]
        self.assertIsNotNone(card.preview)

    def test_menu_has_home(self):
        texts = [a.text() for a in self.w.menus['file'].actions()]
        self.assertIn('Home', texts)


if __name__ == '__main__':
    unittest.main()
