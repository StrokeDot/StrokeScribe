"""exp.56: handwriting that writes like a hand (down strokes go down, letters are one
smooth line), Natural pen for fonts, font change re-writes the text, a clear Hand tab,
steady effect caching."""
import math
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


def sample_font(oblique=False):
    names = (('DejaVuSans-Oblique.ttf', 'arialbi.ttf', 'ariali.ttf') if oblique else
             ('DejaVuSans.ttf', 'arial.ttf', 'segoeui.ttf'))
    for folder in ('/usr/share/fonts/truetype/dejavu', 'C:/Windows/Fonts'):
        for name in names:
            p = Path(folder) / name
            if p.is_file():
                return p
    return None


@unittest.skipIf(SKIP, 'needs Qt')
class FontTests(unittest.TestCase):
    def check_l(self, font):
        from font_stroke_reveal import create_font_drawing
        d = create_font_drawing('l', font, 68)
        long = [s for s in d.strokes if s.length > 20]
        self.assertEqual(len(long), 1, [len(s.points) for s in d.strokes])
        (x0, y0), (x1, y1) = long[0].points[0], long[0].points[-1]
        self.assertLess(y0, y1)                                  # written downwards

    def test_down_strokes_go_down_upright_and_slanted(self):
        for oblique in (False, True):
            font = sample_font(oblique)
            if font is None:
                continue
            self.check_l(font)

    def test_round_letters_are_few_lines(self):
        font = sample_font()
        if font is None:
            self.skipTest('no TTF here')
        from font_stroke_reveal import create_font_drawing
        for ch, most in (('o', 2), ('w', 3), ('e', 3)):
            d = create_font_drawing(ch, font, 68)
            self.assertLessEqual(len([s for s in d.strokes if s.length > 6]), most, ch)

    def test_natural_pen_changes_font_timing(self):
        font = sample_font()
        if font is None:
            self.skipTest('no TTF here')
        from font_stroke_reveal import create_font_drawing, _ink_ownership, _pen_state
        import numpy as np
        d = create_font_drawing('Hello world', font, 68)
        plain = _ink_ownership(d)[0].copy(); tip = _pen_state(d, .23)[0]
        d.pen_ease = 'natural'
        natural = _ink_ownership(d)[0]
        self.assertGreater(float(np.abs(plain - natural).max()), .01)
        self.assertNotEqual(tip, _pen_state(d, .23)[0])


class CacheKeyTests(unittest.TestCase):
    @unittest.skipIf(SKIP, 'needs Qt')
    def test_same_options_same_key(self):
        from frame_render import _erase_key

        class D:
            strokes = []
        d = D()
        a = _erase_key(d, dict(audio=dict(path='x', volume=1.), anchor=[.1, .2]), {'mode': 'finished'})
        b = _erase_key(d, dict(audio=dict(path='x', volume=1.), anchor=[.1, .2]), {'mode': 'finished'})
        self.assertEqual(a, b)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_hand_tab_and_letter_detail(self):
        from app import Window
        from PySide6.QtWidgets import QLabel
        w = Window(); w.show(); self.app.processEvents()
        try:
            texts = [l.text().upper() for l in w.findChildren(QLabel)]
            # Section headers since exp.96 ("Drawing hand", "Painting hand").
            self.assertTrue(any('DRAWING HAND' in t for t in texts))
            self.assertTrue(any('PAINTING HAND' in t for t in texts))
            self.assertEqual(set(w.hand_pictures), {'draw', 'paint', 'move'})
            w.font_select.setCurrentText('Built-in single-line pen'); self.app.processEvents()
            self.assertFalse(w.font_size.isEnabled())            # Letter detail: real fonts only
            # A new element made with AI: nothing is added when the window is closed unused.
            from unittest import mock
            w.ai_engine = mock.Mock()
            with mock.patch('create_image_dialog.CreateImageDialog') as dialog:
                dialog.return_value.exec.return_value = 0
                self.assertFalse(w.new_element('ai'))
                self.assertTrue(dialog.called)
            self.assertEqual(len(w.scenes), 1)
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
