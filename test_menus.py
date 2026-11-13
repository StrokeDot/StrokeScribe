"""Menu bar, check marks, and quiet brush planning."""
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'


class AssetTests(unittest.TestCase):
    def test_check_mark_images(self):
        from PIL import Image
        root = Path(__file__).parent / 'assets'
        for name in ('check.png', 'check_disabled.png'):
            image = Image.open(root / name).convert('RGBA')
            self.assertGreater(max(image.getchannel('A').getdata()), 100, name)
        self.assertFalse((root / 'export_done.wav').exists())          # no built-in sounds


@unittest.skipIf(SKIP, 'needs Qt')
class MenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        return w

    def titles(self, menu):
        return [a.text() for a in menu.actions()]

    def test_menu_bar(self):
        w = self.window()
        names = [a.text().replace('&', '') for a in w.menuBar().actions()]
        self.assertEqual(names, ['File', 'Edit', 'View', 'Help'])      # exp.240: no Effects menu
        file_items = self.titles(w.menus['file'])
        for wanted in ('Open project…\tCtrl+O', 'Save project\tCtrl+S', 'Import SVG artwork…', 'Batch export…',
                       'Exit'):
            self.assertIn(wanted, file_items)
        self.assertNotIn('Update StrokeScribe…', file_items)                 # once, in Help
        self.assertIn('Check for updates…', self.titles(w.menus['help']))
        # View -> Preview background is the same setting as the box above the preview.
        view = w.menus['view']
        background = w.submenus['Preview background']
        background.aboutToShow.emit()
        choices = [a for a in background.actions()]
        self.assertEqual([a.text() for a in choices],
                         [w.preview_background.itemText(i) for i in range(w.preview_background.count())])
        other = next(k for k in range(len(choices)) if k != w.preview_background.currentIndex())
        choices[other].trigger()
        self.assertEqual(w.preview_background.currentIndex(), other)
        background.aboutToShow.emit()
        self.assertTrue(background.actions()[other].isChecked())
        # A setting changed from the window can be undone.
        w.sound_on.setChecked(True)
        # Edit -> Undo goes back.
        w.undo()
        self.assertFalse(w.sound_on.isChecked())
        # Ticked boxes show a check mark.
        self.assertIn('check.png', w.styleSheet())

    def test_brush_width_change_has_no_loading_card(self):
        from PIL import Image, ImageDraw
        w = self.window()
        with tempfile.TemporaryDirectory() as tmp:
            img = Image.new('RGBA', (320, 240), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((40, 30, 280, 210), fill=(230, 120, 40, 255), outline=(20, 20, 20, 255), width=5)
            path = Path(tmp) / 'art.png'
            img.save(path)
            w.source_type.setCurrentIndex(1)
            w.build_image(str(path))
            w.builder.wait(60000)
            self.app.processEvents()
            self.assertTrue(w.builder.success)
            w.slider.setValue(800); self.app.processEvents()
            cards = []
            original = w.show_busy_now
            w.show_busy_now = lambda *a, **k: (cards.append(a), original(*a, **k))
            w.brush_width.setValue(w.brush_width.value() + .05)
            deadline = time.time() + 60
            started = False
            while time.time() < deadline:
                self.app.processEvents()
                worker = getattr(w, 'plan_worker', None)
                started = started or worker is not None
                if started and not worker.isRunning() and not w.timeline_status.text():
                    break
                time.sleep(.05)
            self.assertTrue(started)                 # planned in the background…
            self.assertEqual(cards, [])              # …without the loading card
            self.assertFalse(w.busy)
            self.assertFalse(w.canvas.frame.isNull())


if __name__ == '__main__':
    unittest.main(verbosity=2)
