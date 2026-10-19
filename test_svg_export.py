"""Clean drawing style and SVG export tests."""
import math
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

import lineart
import svg_export
from test_lineart import transparent_art, length


def sketch_like(size=700, seed=3):
    """Grey pencil-style head: an outline plus lots of short hatching."""
    import numpy as np
    rng = np.random.default_rng(seed)
    img = Image.new('RGB', (size, size), (236, 232, 222))
    d = ImageDraw.Draw(img)
    d.ellipse((180, 120, 520, 560), outline=(40, 40, 40), width=5)
    for _ in range(900):
        x, y = rng.integers(220, 480, 2)
        d.line((x, y, x + int(rng.integers(4, 14)), y + int(rng.integers(-6, 6))),
               fill=(int(rng.integers(70, 140)),) * 3, width=1)
    return img


class CleanStyleTests(unittest.TestCase):
    def test_clean_has_far_fewer_longer_strokes_than_detailed(self):
        image = sketch_like()
        detailed, _ = lineart.line_art_strokes(image, 'medium', 'detailed')
        clean, _ = lineart.line_art_strokes(image, 'medium', 'clean')
        self.assertLess(len(clean), len(detailed) * .6)
        self.assertLessEqual(len(clean), lineart.CLEAN['medium']['max_strokes'])
        mean = lambda s: sum(map(length, s)) / max(1, len(s))
        self.assertGreater(mean(clean), mean(detailed))
        # The head outline survives as a long stroke.
        self.assertTrue(any(length(s) > 600 for s in clean))

    def test_clean_keeps_structure_of_illustrations(self):
        strokes, outlines = lineart.line_art_strokes(transparent_art(), 'medium', 'clean')
        self.assertGreaterEqual(outlines, 1)
        ring = [s for s in strokes[outlines:]
                if all(abs(math.dist(p, (240, 240)) - 90) < 10 for p in s)]
        self.assertTrue(ring, 'inner ring kept in Clean style')

    def test_styles_and_details_validated(self):
        with self.assertRaises(ValueError):
            lineart.line_art_strokes(transparent_art(200), 'medium', 'sketchy')
        for detail in ('low', 'medium', 'high', 'max'):
            self.assertIn(detail, lineart.CLEAN)


class SvgExportTests(unittest.TestCase):
    def test_path_data_is_smooth_cubic_and_closes_loops(self):
        open_line = svg_export.path_data([(0, 0), (10, 5), (20, 0), (30, 5)])
        self.assertTrue(open_line.startswith('M0 0 C'))
        self.assertEqual(open_line.count('C'), 3)
        loop = svg_export.path_data([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
        self.assertTrue(loop.endswith('Z'))
        self.assertEqual(svg_export.path_data([(1, 1), (5, 5)]), 'M1 1 L5 5')
        self.assertEqual(svg_export.path_data([(1, 1)]), '')

    def test_document_is_valid_ordered_and_named(self):
        doc = svg_export.svg_document([('outline 1', [(0, 0), (50, 0), (50, 40)]),
                                       ('line 2', [(5, 5), (20, 30)])], 100, 80)
        root = ET.fromstring(doc)
        self.assertEqual(root.attrib['viewBox'], '0 0 100 80')
        self.assertEqual(root.attrib['data-strokescribe-frame'], '0 0 100 80')
        ids = [p.attrib['id'] for p in root.iter('{http://www.w3.org/2000/svg}path')]
        self.assertEqual(ids, ['001-outline-1', '002-line-2'])

    def test_export_writes_matching_pair_aligned_to_visible_area(self):
        image = Image.new('RGBA', (300, 200), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((50, 40, 249, 159), fill=(200, 100, 50, 255))
        strokes = [('outline 1', [(50, 40), (249, 40), (249, 159), (50, 159), (50, 40)])]
        with tempfile.TemporaryDirectory() as tmp:
            svg, png = svg_export.export_drawing(strokes, image, tmp, 'box')
            self.assertEqual((svg.name, png.name), ('box.svg', 'box_color.png'))
            with Image.open(png) as saved:
                self.assertEqual(saved.size, (200, 120))      # cropped to visible area
            root = ET.fromstring(svg.read_text(encoding='utf-8'))
            self.assertEqual(root.attrib['data-strokescribe-frame'], '0 0 200 120')
            first = re.findall(r'-?\d+(?:\.\d+)?', next(
                root.iter('{http://www.w3.org/2000/svg}path')).attrib['d'])[:2]
            self.assertEqual([float(v) for v in first], [0., 0.])  # shifted with the crop


@unittest.skipIf(os.environ.get('STROKESCRIBE_SKIP_QT') == '1', 'needs Qt')
class RoundTripTests(unittest.TestCase):
    def test_exported_svg_reimports_with_exact_frame_and_order(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from engine import import_svg
        from color_reveal import load_color_image
        image = sketch_like(500)
        strokes, _ = lineart.line_art_strokes(image, 'medium', 'clean')
        named = [(f'line {i + 1}', s) for i, s in enumerate(strokes)]
        with tempfile.TemporaryDirectory() as tmp:
            svg, png = svg_export.export_drawing(named, image.convert('RGBA'), tmp, 'head')
            drawing = import_svg(svg)
            colour = load_color_image(png)
        self.assertEqual(drawing.bounds, (0., 0., 500., 500.))
        self.assertEqual((colour.width(), colour.height()), (500, 500))
        self.assertEqual(len(drawing.strokes), len(strokes))
        self.assertTrue(drawing.strokes[0].name.startswith('001-line-1'))
        # Re-imported curves follow the original strokes closely.
        for original, back in zip(strokes[:10], drawing.strokes[:10]):
            self.assertLess(math.dist(original[0], back.points[0]), 1.)
            self.assertLess(math.dist(original[-1], back.points[-1]), 1.)
            self.assertAlmostEqual(back.length, length(original), delta=length(original) * .1 + 2)

    def test_long_straight_svg_edges_need_only_endpoints(self):
        from engine import import_svg
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'straight.svg'
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg">'
                            '<path stroke="black" fill="none" '
                            'd="M 0 0 L 100000 0 L 100000 100000"/></svg>')
            drawing = import_svg(path)
        self.assertEqual(drawing.strokes[0].points,
                         [(0., 0.), (100000., 0.), (100000., 100000.)])
        self.assertAlmostEqual(drawing.strokes[0].length, 200000.)

    def test_dense_curved_svg_imports_without_point_overflow(self):
        from engine import import_svg
        # Would use >500,000 samples with the old fixed 0.4-unit step.
        d = 'M 0 0 ' + ' '.join(
            f'C {x+30} 70 {x+70} -70 {x+100} 0'
            for x in (100 * i for i in range(1800)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'complex-original.svg'
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg">'
                            '<path stroke="black" fill="none" d="' + d + '"/></svg>')
            drawing = import_svg(path)
        self.assertEqual(len(drawing.strokes), 1)
        pts = drawing.strokes[0].points
        self.assertLess(len(pts), 90000)
        self.assertGreater(len(pts), 10000)
        self.assertEqual(pts[0], (0., 0.))
        self.assertEqual(pts[-1], (180000., 0.))

    def test_adaptive_curve_tracks_bezier_geometry_and_preserves_fill_warning(self):
        from engine import import_svg
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'filled-curve.svg'
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg">'
                            '<path style="fill:#b0b0b0" '
                            'd="M 0 0 C 100 220 200 -180 300 40"/></svg>')
            drawing = import_svg(path)
        self.assertEqual(len(drawing.strokes), 1)
        poly = drawing.strokes[0].points
        self.assertTrue(any('Filled shapes are drawn as outlines' in w
                            for w in drawing.warnings))
        def segment_distance(p, a, b):
            dx, dy = b[0]-a[0], b[1]-a[1]
            denom = dx*dx+dy*dy
            if denom == 0:
                return math.dist(p, a)
            t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/denom))
            return math.dist(p, (a[0]+t*dx, a[1]+t*dy))
        for i in range(101):
            t = i/100
            a=(1-t)**3; b=3*(1-t)**2*t; c=3*(1-t)*t*t; d=t**3
            real = (100*b+200*c+300*d, 220*b-180*c+40*d)
            self.assertLess(min(segment_distance(real, x, y)
                                for x, y in zip(poly, poly[1:])), 1.0)

    def test_app_has_style_choice_and_svg_export(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from app import Window
        from image_reconstruct import reconstruct
        w = Window()
        try:
            self.assertEqual([w.image_style.itemText(i) for i in range(2)],
                             ['Clean drawing', 'Detailed (all lines)'])
            self.assertEqual(w.image_style.currentIndex(), 0)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'art.png'
                transparent_art(400).save(path)
                result = reconstruct(path, 'line_art', 'medium', style='clean')
                self.assertEqual(result.drawing.line_style, 'clean')
                w.source_type.setCurrentIndex(1)
                w.image_ready(result)
                svg, png = w.export_svg(folder=tmp)
                self.assertTrue(svg.is_file() and png.is_file())
                self.assertEqual(svg.name, 'art_drawing.svg')
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
