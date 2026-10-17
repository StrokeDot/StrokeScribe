"""Line art reconstruction tests (synthetic images; no personal artwork)."""
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import lineart


def transparent_art(size=600):
    """A beige disc with a dark ring inside and a box, on transparency."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 60, 420, 420), fill=(230, 215, 180, 255))
    d.ellipse((150, 150, 330, 330), outline=(25, 25, 25, 255), width=6)
    d.rectangle((430, 380, 560, 560), fill=(120, 70, 30, 255))
    return img


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


class LineArtTests(unittest.TestCase):
    def test_model_file_ships_and_runs(self):
        self.assertTrue(lineart.MODEL_PATH.is_file())
        self.assertTrue((lineart.MODEL_PATH.parent / 'TEED_LICENSE.txt').is_file())
        rgb = np.full((96, 120, 3), 255, np.uint8)
        rgb[30:70, 40:80] = 0
        edges = lineart.teed_edges(rgb)
        self.assertEqual(edges.shape, (96, 120))
        self.assertGreater(edges[30, 40:80].max(), .5)     # square border is a line
        self.assertLess(edges[5, 5], .2)                   # empty paper is not

    def test_outline_first_closed_and_inner_ring_found(self):
        image = transparent_art()
        strokes, outlines = lineart.line_art_strokes(image, 'medium')
        self.assertGreaterEqual(outlines, 1)
        first = strokes[0]
        self.assertLessEqual(math.dist(first[0], first[-1]), 3, 'outline is closed')
        # Every point lies on the canvas.
        for s in strokes:
            for x, y in s:
                self.assertTrue(-2 <= x <= 602 and -2 <= y <= 602)
        # The dark ring (radius ~90 around 240,240) becomes a single stroke.
        ring = [s for s in strokes[outlines:]
                if all(abs(math.dist(p, (240, 240)) - 90) < 9 for p in s)]
        self.assertTrue(ring, 'inner ring traced')
        self.assertGreater(max(length(s) for s in ring), 2 * math.pi * 90 * .7)

    def test_thick_dark_line_becomes_one_centre_stroke(self):
        img = Image.new('RGB', (500, 300), 'white')
        ImageDraw.Draw(img).line((50, 150, 450, 150), fill='black', width=9)
        strokes, outlines = lineart.line_art_strokes(img, 'medium')
        self.assertEqual(outlines, 0)                     # no transparency
        long_ones = [s for s in strokes if length(s) > 200]
        self.assertEqual(len(long_ones), 1, 'one line, not two parallel edges')
        self.assertTrue(all(abs(y - 150) < 4 for _, y in long_ones[0]))

    def test_texture_grain_is_not_drawn(self):
        img = Image.new('RGB', (600, 600), 'white')
        d = ImageDraw.Draw(img)
        d.rectangle((80, 80, 520, 520), fill=(150, 90, 45), outline=(40, 25, 10), width=5)
        rng = np.random.default_rng(1)
        for _ in range(260):                               # short faint grain dashes
            x, y = rng.integers(100, 500, 2)
            d.line((x, y, x + 1, y + int(rng.integers(6, 16))), fill=(132, 78, 38), width=1)
        strokes, _ = lineart.line_art_strokes(img, 'medium')
        short = [s for s in strokes if length(s) < 30]
        self.assertLess(len(short), 25, f'{len(short)} grain strokes drawn')
        self.assertTrue(any(length(s) > 1000 for s in strokes), 'box outline kept')

    def test_link_joins_broken_line_but_not_unrelated_ends(self):
        a = [(0., 0.), (10., 0.), (20., 0.)]
        b = [(23., 0.), (40., 0.)]
        c = [(23., 30.), (23., 50.)]                       # perpendicular, farther
        joined = lineart.link_strokes([a, b, c], gap=6)
        self.assertEqual(len(joined), 2)
        self.assertIn(40., [p[0] for s in joined for p in s if len(s) == 5])

    def test_thinning_gives_one_pixel_lines(self):
        mask = np.zeros((40, 80), bool)
        mask[15:22, 5:75] = True
        skel = lineart.thin(mask)
        cols = skel[:, 10:70].sum(0)
        self.assertTrue((cols == 1).all())

    def test_sketch_detection(self):
        gray = np.full((100, 100, 3), 200, np.uint8)
        colour = gray.copy(); colour[..., 0] = 230; colour[..., 2] = 60
        support = np.ones((100, 100), bool)
        self.assertTrue(lineart.is_sketch(gray, support))
        self.assertFalse(lineart.is_sketch(colour, support))

    def test_repeatable_and_fast(self):
        image = transparent_art(1000)
        started = time.perf_counter()
        first = lineart.line_art_strokes(image, 'medium')
        elapsed = time.perf_counter() - started
        self.assertEqual(first, lineart.line_art_strokes(image, 'medium'))
        self.assertLess(elapsed, 20)

    def test_small_object_on_large_canvas_keeps_detail(self):
        big = Image.new('RGBA', (3000, 3000), (0, 0, 0, 0))
        big.alpha_composite(transparent_art(600), (1200, 1200))
        strokes, outlines = lineart.line_art_strokes(big, 'medium')
        ring = [s for s in strokes[outlines:]
                if all(abs(math.dist(p, (1440, 1440)) - 90) < 10 for p in s)]
        self.assertTrue(ring, 'detail found after cropping to the object')


@unittest.skipIf(os.environ.get('STROKESCRIBE_SKIP_QT') == '1', 'needs Qt')
class LineArtReconstructionTests(unittest.TestCase):
    def test_reconstruct_line_art_mode(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from image_reconstruct import reconstruct
        from adaptive_hand import plan_for
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'art.png'
            transparent_art().save(path)
            result = reconstruct(path, 'line_art', 'medium')
        d = result.drawing
        self.assertEqual(d.source_mode, 'line_art')
        self.assertTrue(d.image_region_priority)
        self.assertTrue(d.strokes[0].name.startswith('outline'))
        self.assertGreater(len(d.strokes), 2)
        plan = plan_for(d, result.image)
        self.assertGreater(len(plan.segments), 0)

    def test_line_art_is_the_only_image_method(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from app import Window
        w = Window()
        try:
            self.assertFalse(hasattr(w, 'image_mode'))      # no method menu any more
            self.assertFalse(hasattr(w, 'ai_model'))
            self.assertEqual([w.image_detail.itemText(i) for i in range(w.image_detail.count())],
                             ['Low', 'Medium', 'High', 'Max'])
            self.assertEqual(w.image_detail.currentText(), 'Medium')
            self.assertFalse(w.clean_faint.isChecked())
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
