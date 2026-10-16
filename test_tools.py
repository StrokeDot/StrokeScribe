"""Built-in pencil/marker/brush and the separate painting hand."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'


class AssetTests(unittest.TestCase):
    def test_builtin_tools_have_their_tip_where_the_tool_is(self):
        from PIL import Image
        import tools_kit
        for name, (file, tip, _) in tools_kit.BUILTIN.items():
            if name == 'hand':
                continue                  # the hand's tip is the user's own calibration
            image = Image.open(tools_kit.ASSETS / file).convert('RGBA')
            w, h = image.size
            x, y = round(tip[0] * w), round(tip[1] * h)
            box = image.getchannel('A').crop((x - 10, y - 10, x + 11, y + 11))
            self.assertGreater(max(box.getdata()), 200, name)       # something solid at the tip
            # The tip is the upper-left end: nothing solid further up-left.
            corner = image.getchannel('A').crop((0, 0, max(1, x - 14), max(1, y - 14)))
            self.assertLess(max(corner.getdata()), 40, name)


@unittest.skipIf(SKIP, 'needs Qt')
class PaintingHandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ['STROKESCRIBE_CONFIG_DIR'] = str(self.dir / 'config')
        import library
        settings = library.load_settings()
        settings['root'] = str(self.dir / 'Lib')
        library.save_settings(settings)

    def tearDown(self):
        del os.environ['STROKESCRIBE_CONFIG_DIR']
        self.tmp.cleanup()

    def settings(self, **extra):
        s = dict(show_paint_hand=True, paint_hand='Same as drawing hand', paint_hand_size=30,
                 handsize=.75, ax=.08, ay=.13)
        s.update(extra)
        return s

    def test_tool_tip_lands_on_the_pen_tip(self):
        from PySide6.QtGui import QImage, QPainter
        from color_reveal import draw_hand
        from hand_layer import capture
        import tools_kit
        hand = tools_kit.builtin_image('hand')
        brush = tools_kit.painting_hand(self.settings(paint_hand=tools_kit.PAINT_BRUSH), hand)
        self.assertIsNotNone(getattr(brush, 'own_tip', None))
        frame = QImage(1920, 1080, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(frame)
        with capture() as hands:
            draw_hand(painter, (900., 500.), brush, 1920, .75, (.08, .13))
        painter.end()
        rect, image = hands[-1]
        self.assertIs(image, brush)
        self.assertAlmostEqual(rect.width(), 1920 * .30, delta=1)
        tip = tools_kit.BUILTIN['brush'][1]
        self.assertAlmostEqual(rect.x() + tip[0] * rect.width(), 900, delta=1)
        self.assertAlmostEqual(rect.y() + tip[1] * rect.height(), 500, delta=1)
        # The ordinary hand is placed exactly as before.
        with capture() as hands:
            painter = QPainter(frame)
            draw_hand(painter, (900., 500.), hand, 1920, .75, (.08, .13))
            painter.end()
        rect, _ = hands[-1]
        self.assertAlmostEqual(rect.x(), 900 - .08 * 1920 * .75, delta=1)

    def test_painting_hand_choices(self):
        import tools_kit
        hand = tools_kit.builtin_image('hand')
        self.assertIs(tools_kit.painting_hand(self.settings(), hand), hand)
        self.assertIsNone(tools_kit.painting_hand(self.settings(show_paint_hand=False), hand))
        a = tools_kit.painting_hand(self.settings(paint_hand=tools_kit.PAINT_BRUSH), hand)
        b = tools_kit.painting_hand(self.settings(paint_hand=tools_kit.PAINT_BRUSH), hand)
        self.assertIs(a, b)                                 # cached: frame caches stay valid
        # Library hand that no longer exists: falls back to the drawing hand.
        gone = self.settings(paint_hand=tools_kit.PAINT_LIBRARY, paint_hand_path=str(self.dir / 'x.png'))
        self.assertIs(tools_kit.painting_hand(gone, hand), hand)

    def window(self):
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        return w

    def test_builtin_pencil_and_brush_in_the_window_and_projects(self):
        import projects
        import tools_kit
        w = self.window()
        w.use_builtin_tool('pencil')
        self.assertEqual(w.hand_builtin, 'pencil')
        self.assertAlmostEqual(w.ax.value(), tools_kit.BUILTIN['pencil'][1][0], places=3)
        self.assertAlmostEqual(w.handsize.value(), tools_kit.BUILTIN['pencil'][2])
        w.paint_hand.setCurrentText(tools_kit.PAINT_BRUSH); w.paint_hand_changed()
        options = w.options()
        self.assertIsNotNone(getattr(options['painting_hand'], 'own_tip', None))
        w.slider.setValue(980); self.app.processEvents()
        self.assertFalse(w.canvas.frame.isNull())
        saved = projects.save(self.dir / 'tools', w.project_state())
        other = self.window()
        self.assertTrue(other.open_project(str(saved)))
        self.assertEqual(other.hand_builtin, 'pencil')
        self.assertEqual(other.paint_hand.currentText(), tools_kit.PAINT_BRUSH)
        self.assertEqual(other.hand.size(), w.hand.size())
        # Undo goes back to the drawing hand while painting.
        w.undo()
        self.assertEqual(w.paint_hand.currentText(), tools_kit.PAINT_SAME)

    def test_library_painting_hand_survives_in_the_project(self):
        from PIL import Image, ImageDraw
        import library
        import projects
        import tools_kit
        path = self.dir / 'brush hand.png'
        img = Image.new('RGBA', (300, 300), (0, 0, 0, 0))
        ImageDraw.Draw(img).polygon([(40, 30), (290, 250), (290, 299), (230, 299)], fill=(120, 80, 60, 255))
        img.save(path)
        item = library.Library().add('hands', path)
        w = self.window()
        w.set_paint_hand(str(item.path))
        self.assertEqual(w.paint_hand.currentText(), tools_kit.PAINT_LIBRARY)
        self.assertLess(w.paint_hand_tip[0], .3)                 # tip found at the upper left
        self.assertIn('brush hand', w.paint_hand_name.text())
        saved = projects.save(self.dir / 'p', w.project_state())
        Path(item.path).unlink()                                 # the library file disappears
        other = self.window()
        self.assertTrue(other.open_project(str(saved)))
        self.assertTrue(Path(other.paint_hand_path).is_file())   # re-created from the project
        tool = other.options()['painting_hand']
        self.assertIsNotNone(getattr(tool, 'own_tip', None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
