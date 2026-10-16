"""Complete transparency for colour PNGs and imported images; the Sound tab."""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'

from png_cleanup import background_colours, clean_background

W, H = 400, 300


def artwork():
    art = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)
    d.ellipse((80, 50, 320, 250), fill=(230, 120, 40, 255), outline=(20, 20, 20, 255), width=6)
    d.ellipse((170, 110, 230, 170), fill=(255, 255, 255, 255))          # white inside: must stay
    return art


def on_checkerboard(dark=False):
    bg = Image.new('RGBA', (W, H))
    d = ImageDraw.Draw(bg)
    a, b = ((40, 40, 40, 255), (64, 64, 64, 255)) if dark else ((255, 255, 255, 255), (204, 204, 204, 255))
    for y in range(0, H, 16):
        for x in range(0, W, 16):
            d.rectangle((x, y, x + 15, y + 15), fill=a if (x // 16 + y // 16) % 2 == 0 else b)
    bg.alpha_composite(artwork())
    return bg


def alpha(image):
    return np.asarray(image.convert('RGBA'))[..., 3]


class CleanupTests(unittest.TestCase):
    def test_fake_checkerboard_becomes_transparent(self):
        for dark in (False, True):
            out = alpha(clean_background(on_checkerboard(dark)))
            self.assertEqual(out[5, 5], 0)                 # background gone
            self.assertEqual(out[150, 110], 255)           # orange kept
            self.assertEqual(out[140, 200], 255)           # white inside the artwork kept
            self.assertEqual(out[H - 3, W - 3], 0)

    def test_white_sheet_and_faint_leftovers(self):
        sheet = Image.new('RGBA', (W, H), (255, 255, 255, 255)); sheet.alpha_composite(artwork())
        out = alpha(clean_background(sheet))
        self.assertEqual((out[3, 3], out[140, 200]), (0, 255))
        faint = artwork()
        ImageDraw.Draw(faint).rectangle((5, 5, 40, 40), fill=(0, 0, 0, 30))   # haze
        self.assertEqual(alpha(clean_background(faint))[20, 20], 0)
        self.assertEqual(alpha(clean_background(faint, faint=False))[20, 20], 30)

    def test_real_pictures_are_left_alone(self):
        photo = Image.fromarray((np.random.default_rng(3).random((H, W, 3)) * 255).astype(np.uint8)).convert('RGBA')
        self.assertEqual(background_colours(np.asarray(photo)[..., :3].astype(int), alpha(photo)), [])
        self.assertTrue((alpha(clean_background(photo)) == 255).all())
        art = artwork()
        self.assertTrue(np.array_equal(alpha(clean_background(art)), alpha(art)))   # already transparent

    @unittest.skipIf(SKIP, 'needs Qt')
    def test_image_import_clean_option(self):
        from image_reconstruct import clean_faint_pixels
        cleaned, box = clean_faint_pixels(on_checkerboard(), with_box=True)
        self.assertLess(box[2] - box[0], W - 50)            # cropped to the artwork, not the sheet


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_matching_png_is_cleaned_and_sound_tab(self):
        from app import Window
        w = Window(); self.addCleanup(w.close)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'colours.png'
            on_checkerboard().save(path)
            w.color_path = str(path)
            self.assertTrue(w.clean_color.isChecked())
            self.assertTrue(w.reload_color())
            self.assertLess(w.final_image.width(), W - 50)      # cropped to the artwork
            self.assertEqual(w.final_image.pixelColor(2, w.final_image.height() // 2).alpha(), 0)
            self.assertIn('cleaned', w.color_note.text())
            w.clean_color.setChecked(False)                     # reloads as it is
            self.assertEqual((w.final_image.width(), w.final_image.height()), (W, H))
        names = [w.inspector_tabs.tabText(i) for i in range(w.inspector_tabs.count())]
        self.assertEqual(names, ['Animation', 'Hand', 'Export', 'Sound'])
        sound_page = w.inspector_tabs.widget(3)
        self.assertTrue(sound_page.isAncestorOf(w.sound_on))
        self.assertTrue(sound_page.isAncestorOf(w.load_audio_button))
        self.assertFalse(w.inspector_tabs.widget(2).isAncestorOf(w.sound_on))


if __name__ == '__main__':
    unittest.main(verbosity=2)
