"""exp.53: one Background for everything, more fonts, Letter detail, Natural pen, left hand."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

import backgrounds
from export_job import backgrounds_from_settings

HERE = Path(__file__).parent


class PlainTests(unittest.TestCase):
    def test_background_choices(self):
        self.assertEqual(backgrounds.spec('Transparent'), 'transparent')
        self.assertEqual(backgrounds.spec('Transparency grid'), 'transparent')       # older projects
        self.assertEqual(backgrounds.spec('White background'), 'white')
        self.assertEqual(backgrounds.spec('Paper'), 'paper')
        self.assertEqual(backgrounds.spec('Custom colour…', '#123456'), '#123456')
        self.assertEqual(backgrounds_from_settings({'preview_background': 'Chalkboard'}),
                         dict(mp4_background='chalkboard', background='chalkboard'))
        self.assertEqual(backgrounds_from_settings({'preview_background': 'Transparent'})['background'], None)
        self.assertEqual(backgrounds_from_settings({'preview_background': 'Custom colour…',
                                                    'background_color': '#ff8800'})['mp4_background'], '#ff8800')

    @unittest.skipIf(SKIP, 'needs Qt')
    def test_fonts(self):
        from font_library import FONT_GROUPS, STARTER_FONTS, font_slug
        self.assertGreaterEqual(len(STARTER_FONTS), 50)
        self.assertEqual(len(set(STARTER_FONTS)), len(STARTER_FONTS))
        self.assertIn('Permanent Marker', FONT_GROUPS['Handwriting'])
        for family in STARTER_FONTS:
            font_slug(family)

    @unittest.skipIf(SKIP or not shutil.which('ffmpeg'), 'needs Qt and FFmpeg')
    def test_background_png_and_videos(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path = backgrounds.picture_png('#ff0000', 64, 36, Path(tmp) / 'bg.png')
            self.assertEqual(Image.open(path).getpixel((10, 10))[:3], (255, 0, 0))
            backgrounds.picture_png('paper', 64, 36, Path(tmp) / 'paper.png')
            # Frames on a transparent canvas → MOV / WebM / MP4 on the chosen background.
            folder = Path(tmp) / 'frames'; folder.mkdir()
            for i in range(4):
                im = Image.new('RGBA', (64, 36), (0, 0, 0, 0))
                im.putpixel((5, 5), (0, 0, 255, 255)); im.save(folder / f'frame_{i:06d}.png')
            (folder / 'sequence.json').write_text(json.dumps(dict(width=64, height=36, fps=4, frames=4)))
            from engine import encode_mp4, encode_mov, encode_webm
            for out in (encode_mp4(folder, 4, '#00ff00'), encode_webm(folder, 4, 28, None, '#00ff00'),
                        encode_mov(folder, 4, None, 'paper')):
                self.assertTrue(out.is_file() and out.stat().st_size > 0, out)


@unittest.skipIf(SKIP, 'needs Qt')
class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_left_handed_mirrors_hand_and_tip(self):
        from PySide6.QtGui import QImage
        from export_job import options_from_settings
        hand = QImage(str(HERE / 'assets' / 'default_hand.png'))
        right = options_from_settings({'ax': .08, 'ay': .13}, None, hand=hand)
        left = options_from_settings({'ax': .08, 'ay': .13, 'left_handed': True}, None, hand=hand)
        self.assertAlmostEqual(right['anchor'][0], .08)
        self.assertAlmostEqual(left['anchor'][0], .92)
        a, b = right['hand'], left['hand']
        w = a.width()
        for x, y in ((40, 300), (600, 500), (900, 900)):
            self.assertEqual(a.pixelColor(x, y), b.pixelColor(w - 1 - x, y))
        self.assertIs(options_from_settings({'left_handed': True}, None, hand=hand)['hand'], b)   # cached
        er = options_from_settings({'left_handed': True, 'erase_mode': 'Zigzag (follows the shapes)'}, None, hand=hand)
        from eraser import ERASER_TIP
        if er['erase']:
            self.assertAlmostEqual(er['erase']['anchor'][0], 1 - ERASER_TIP[0])

    def test_window_background_and_controls(self):
        from PySide6.QtGui import QColor
        from app import Window
        w = Window(); w.show(); self.app.processEvents()
        try:
            items = [w.preview_background.itemText(i) for i in range(w.preview_background.count())]
            self.assertEqual(items[0], 'Transparent')
            self.assertIn('Custom colour…', items)
            self.assertFalse(w.font_bg_mode.isVisibleTo(w))            # no second background any more
            self.assertFalse(w.mp4_background.isVisibleTo(w))
            index = items.index('Custom colour…')
            with mock.patch('app.QColorDialog.getColor', return_value=QColor('#336699')):
                w.preview_background.setCurrentIndex(index); w.background_chosen(index)
            self.assertEqual(w.background_spec(), '#336699')
            self.assertEqual(w.export_backgrounds(), dict(mp4_background='#336699', background='#336699'))
            self.assertEqual(w.settings_state()['background_color'], '#336699')
            # Letter detail (was "Glyph detail size") explains itself.
            self.assertIn('NOT change', w.font_size.toolTip())
            # Left-handed in the Hand tab.
            w.left_handed.setChecked(True)
            self.assertTrue(w.settings_state()['left_handed'])
            self.assertGreater(w.options()['anchor'][0], .5)
            # Natural pen movement changes the timing.
            w.pen_ease.setCurrentIndex(1)
            self.assertEqual(w.drawing.pen_ease, 'natural')
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
