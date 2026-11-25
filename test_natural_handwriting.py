"""exp.13 Natural handwriting (experiment): every letter a little different, a line that drifts,
uneven ink and a breath between words; the same text always looks the same."""
import os
import unittest

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from test_part_c import sample_font

FONT = sample_font()


@unittest.skipIf(FONT is None, 'needs a TrueType font')
class NaturalHandwritingTests(unittest.TestCase):
    TEXT = 'lolo lolo\nlolo'

    def test_off_by_default_and_unchanged(self):
        from font_stroke_reveal import create_font_drawing
        a = create_font_drawing(self.TEXT, FONT, 68)
        b = create_font_drawing(self.TEXT, FONT, 68, natural=False)
        self.assertFalse(a.hand_natural)
        self.assertEqual(np.asarray(a.font_ink).tobytes(), np.asarray(b.font_ink).tobytes())

    def test_repeated_letters_differ(self):
        from font_stroke_reveal import create_font_drawing
        d = create_font_drawing(self.TEXT, FONT, 68, natural=True)
        self.assertTrue(d.hand_natural)
        # the same letter, written four times on the first line: not four identical copies
        os_ = [s for s in d.strokes if s.name.startswith('Pen o ')]
        shapes = set()
        for s in os_:
            xs, ys = zip(*s.points)
            shapes.add((round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)))
        self.assertGreater(len(shapes), 1)

    def test_same_text_gives_the_same_result(self):
        from font_stroke_reveal import create_font_drawing
        a = create_font_drawing(self.TEXT, FONT, 68, natural=True)
        b = create_font_drawing(self.TEXT, FONT, 68, natural=True)
        self.assertEqual(np.asarray(a.font_ink).tobytes(), np.asarray(b.font_ink).tobytes())
        self.assertEqual([s.points for s in a.strokes], [s.points for s in b.strokes])

    def test_letters_stay_readable_and_complete(self):
        from font_stroke_reveal import create_font_drawing
        plain = create_font_drawing(self.TEXT, FONT, 68)
        natural = create_font_drawing(self.TEXT, FONT, 68, natural=True)
        self.assertEqual(len(plain.strokes), len(natural.strokes))
        ink_a = (np.asarray(plain.font_ink)[..., 3] > 60).sum()
        ink_b = (np.asarray(natural.font_ink)[..., 3] > 60).sum()
        self.assertLess(abs(ink_a - ink_b) / ink_a, .15)       # no letter lost or smeared

    def test_a_breath_between_words(self):
        from font_stroke_reveal import create_font_drawing, _stroke_schedule
        plain = create_font_drawing(self.TEXT, FONT, 68)
        natural = create_font_drawing(self.TEXT, FONT, 68, natural=True)
        self.assertGreater(_stroke_schedule(natural)[1], _stroke_schedule(plain)[1])



@unittest.skipIf(FONT is None, 'needs a TrueType font')
class NaturalHandwritingSwitchTests(unittest.TestCase):
    def test_switch_rewrites_and_is_kept_with_the_element(self):
        os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from app import Window
        w = Window()
        try:
            w.font_select.addItem('Local: test', str(FONT))
            w.font_select.setCurrentIndex(w.font_select.count() - 1)
            w.text.setPlainText('lolo lolo')
            w.letter(); app.processEvents()
            self.assertFalse(w.natural_hand.isChecked())
            self.assertFalse(w.drawing.hand_natural)
            w.natural_hand.setChecked(True); app.processEvents()
            self.assertTrue(w.drawing.hand_natural)              # written again, naturally
            self.assertTrue(w.letter_state()['natural'])
            w.natural_hand.blockSignals(True); w.natural_hand.setChecked(False); w.natural_hand.blockSignals(False)
            w.restore_letter_words(w.letter_state() | {'natural': True})
            self.assertTrue(w.natural_hand.isChecked())
        finally:
            w.close()


class WindowsFontTests(unittest.TestCase):
    """exp.14: Ink Free comes from Windows itself (never downloaded or copied)."""

    def test_ink_free_is_found_in_the_windows_fonts_folder(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        import font_library
        with tempfile.TemporaryDirectory() as tmp:
            fonts = Path(tmp) / 'Fonts'; fonts.mkdir()
            with mock.patch.dict(os.environ, {'WINDIR': tmp, 'LOCALAPPDATA': tmp}):
                self.assertIsNone(font_library.installed_font('Ink Free'))
                with self.assertRaises(ValueError):            # a clear message, no Google download
                    font_library.download_google_font('Ink Free')
                (fonts / 'Inkfree.ttf').write_bytes(b'x' * 2000)
                self.assertEqual(font_library.installed_font('Ink Free'), fonts / 'Inkfree.ttf')
                self.assertEqual(font_library.download_google_font('Ink Free'), fonts / 'Inkfree.ttf')
        self.assertNotIn('Ink Free', font_library.STARTER_FONTS)


if __name__ == '__main__':
    unittest.main()
