"""exp.21: an element's finished picture as a PNG (transparent) or an SVG, for Filmora."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtGui import QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
from test_part_c import sample_font  # noqa: E402

FONT = sample_font()


class TextSvg(unittest.TestCase):
    @unittest.skipIf(FONT is None, 'needs a TrueType font')
    def test_text_is_saved_as_smooth_filled_letter_shapes_in_its_colour(self):
        from font_stroke_reveal import create_font_drawing
        from element_export import _text_svg
        d = create_font_drawing('Bo', FONT, 68)
        d.font_color = '#aa3311'
        text = _text_svg(d, 'Bo')
        self.assertIn('fill="#aa3311"', text)
        self.assertIn('fill-rule="evenodd"', text)          # the hole of the 'o' stays a hole
        self.assertGreaterEqual(text.count('M'), 3)
        self.assertTrue(QSvgRenderer(text.encode()).isValid())


class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window as W
        from engine import import_svg
        cls.w = W(); cls.w.show(); APP.processEvents()
        cls.w.set_drawing(import_svg('samples/drawing.svg')); APP.processEvents()
        cls.dir = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def test_the_export_tab_has_the_picture_button(self):
        self.assertIn('PNG / SVG', self.w.export_picture_button.text())

    def test_png_keeps_its_place_in_the_video_frame_on_a_transparent_background(self):
        from element_export import save_png
        path, = save_png(self.w, self.dir / 'full', True)
        image = QImage(str(path))
        size = self.w.res.currentText().replace(' ', '').split('×')
        self.assertEqual((image.width(), image.height()), (int(size[0]), int(size[1])))
        self.assertEqual(image.pixelColor(1, 1).alpha(), 0)
        self.assertTrue(image.hasAlphaChannel())

    def test_png_can_be_cropped_to_the_picture(self):
        from element_export import save_png
        full, = save_png(self.w, self.dir / 'a', True)
        crop, = save_png(self.w, self.dir / 'b', False)
        a, b = QImage(str(full)), QImage(str(crop))
        self.assertLess(b.width() * b.height(), a.width() * a.height())

    def test_a_line_drawing_is_saved_as_its_lines(self):
        from element_export import save_svg
        path, = save_svg(self.w, self.dir / 'lines')
        text = path.read_text(encoding='utf-8')
        self.assertIn('<path', text)
        self.assertTrue(QSvgRenderer(str(path)).isValid())


if __name__ == '__main__':
    unittest.main()
