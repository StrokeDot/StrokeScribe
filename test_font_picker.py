"""exp.15: the font list shows every font in its own style, with Recent and Favorites on top;
notices are compact and glide in."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['XDG_CONFIG_HOME'] = tempfile.mkdtemp()        # a clean settings file
from PySide6.QtWidgets import QApplication, QComboBox

APP = QApplication.instance() or QApplication([])

import font_picker  # noqa: E402
from font_library import STARTER_FONTS, font_slug  # noqa: E402


class FontPickerTests(unittest.TestCase):
    def setUp(self):
        s = font_picker._settings()
        s.remove(font_picker.RECENT_KEY); s.remove(font_picker.FAVOURITES_KEY)

    def test_every_listed_font_has_a_preview_without_downloading(self):
        for family in STARTER_FONTS:
            self.assertTrue((font_picker.PREVIEWS / f'{font_slug(family)}.png').is_file(), family)
        pix = font_picker.picture('Caveat', '#ffffff', 22)
        self.assertIsNotNone(pix)
        self.assertAlmostEqual(pix.height() / pix.devicePixelRatio(), 22, delta=1)

    def test_recent_keeps_the_last_five_newest_first(self):
        for name in ('A', 'B', 'C', 'D', 'E', 'F', 'B'):
            font_picker.note_recent(name)
        self.assertEqual(font_picker.recent(), ['B', 'F', 'E', 'D', 'C'])
        font_picker.note_recent(font_picker.BUILT_IN)
        self.assertNotIn(font_picker.BUILT_IN, font_picker.recent())

    def test_favourites_toggle(self):
        self.assertTrue(font_picker.toggle_favourite('Caveat'))
        self.assertEqual(font_picker.favourites(), ['Caveat'])
        self.assertFalse(font_picker.toggle_favourite('Caveat'))
        self.assertEqual(font_picker.favourites(), [])

    def test_recent_and_favourites_at_the_top_and_headings_cannot_be_chosen(self):
        combo = QComboBox()
        combo.addItem(font_picker.BUILT_IN)
        font_picker.add_heading(combo, 'HANDWRITING')
        for name in ('Caveat', 'Kalam', 'Lora'):
            combo.addItem(name)
        combo.setCurrentIndex(combo.findText('Lora'))
        font_picker.note_recent('Kalam'); font_picker.toggle_favourite('Caveat')
        font_picker.refresh_quick(combo)
        texts = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(texts[:5], [font_picker.BUILT_IN, 'RECENT', 'Kalam', 'FAVORITES', 'Caveat'])
        self.assertEqual(combo.currentText(), 'Lora')                 # the choice is kept
        head = combo.model().item(texts.index('HANDWRITING'))
        self.assertFalse(head.isEnabled() or head.isSelectable())
        font_picker.refresh_quick(combo)                               # refreshing doesn't pile up
        self.assertEqual(combo.count(), len(texts))
        self.assertEqual(len(font_picker.font_rows(combo)), 4)


class NoticeTests(unittest.TestCase):
    def test_a_short_notice_is_compact(self):
        from PySide6.QtWidgets import QMainWindow
        from PySide6.QtTest import QTest
        import toast
        win = QMainWindow(); win.resize(800, 400); win.show()
        n = toast.notify(win, 'Saved New Book', 'done', 30)
        QTest.qWait(320)
        self.assertLess(n.width(), toast.WIDTH)                       # as wide as its words
        self.assertEqual(n.pos(), n.home)                              # glided into place
        win.close()


if __name__ == '__main__':
    unittest.main()
