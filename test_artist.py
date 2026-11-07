"""Artist (layered) animation tests."""
import math
import os
import tempfile
import unittest
from pathlib import Path

import lineart
from test_lineart import transparent_art, length
from test_svg_export import sketch_like


class ArtistPlanTests(unittest.TestCase):
    def test_layers_in_order_guides_lines_accents(self):
        plan = lineart.artist_strokes(transparent_art(), 'medium')
        layers = [layer for layer, _, _ in plan]
        self.assertTrue(layers[0] == 'guide' and layers[-1] == 'accent')
        # Never goes back to an earlier layer.
        rank = {'guide': 0, 'line': 1, 'accent': 2}
        self.assertEqual([rank[l] for l in layers], sorted(rank[l] for l in layers))
        self.assertLessEqual(layers.count('guide'), 20)
        self.assertGreater(layers.count('line'), layers.count('accent'))

    def test_guides_fast_detail_slower_accents_quick(self):
        plan = lineart.artist_strokes(sketch_like(), 'medium')
        paces = {layer: [p for l, _, p in plan if l == layer] for layer in ('guide', 'line', 'accent')}
        self.assertTrue(all(p < 1 for p in paces['guide']))
        self.assertTrue(all(p < 1 for p in paces['accent']))
        self.assertGreater(max(paces['line']), 1.2, 'dense detail is drawn more slowly')

    def test_main_lines_match_clean_drawing(self):
        image = transparent_art()
        clean, _ = lineart.line_art_strokes(image, 'medium', 'clean')
        lines = [s for l, s, _ in lineart.artist_strokes(image, 'medium') if l == 'line']
        self.assertEqual(len(lines), len(clean))
        self.assertAlmostEqual(sum(map(length, lines)), sum(map(length, clean)), delta=1)


@unittest.skipIf(os.environ.get('STROKESCRIBE_SKIP_QT') == '1', 'needs Qt')
class ArtistAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])

    def build(self, animation):
        from image_reconstruct import reconstruct
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'art.png'
            transparent_art().save(path)
            return reconstruct(path, 'line_art', 'medium', animation=animation)

    def test_reconstruct_artist_strokes_have_layer_colours_and_pace(self):
        from lineart import ARTIST_COLORS
        d = self.build('artist').drawing
        self.assertEqual(d.animation_style, 'artist')
        self.assertTrue(d.strokes[0].name.startswith('guide'))
        self.assertTrue(d.strokes[-1].name.startswith('accent'))
        guide = d.strokes[0]
        self.assertEqual(guide.color, ARTIST_COLORS['guide'])
        self.assertLess(guide.pace, 1)
        line = next(s for s in d.strokes if s.name.startswith('line'))
        self.assertLess(guide.width, line.width)
        with self.assertRaises(ValueError):
            self.build('sketchy')

    def test_timing_honours_pace(self):
        from image_drawing import drawing_state
        from engine import Drawing, Stroke
        slow = Drawing([Stroke('a', [(0, 0), (100, 0)], pace=3.),
                        Stroke('b', [(0, 10), (100, 10)], pace=1.)], (0, 0, 100, 10), [])
        # The slow first stroke uses about 3/4 of the time, so at 50% of the
        # time only part of the first stroke's ink is down.
        self.assertLess(drawing_state(slow, .5).stroke_progress, .45)
        even = Drawing([Stroke('a', [(0, 0), (100, 0)]), Stroke('b', [(0, 10), (100, 10)])],
                       (0, 0, 100, 10), [])
        self.assertGreater(drawing_state(even, .9).stroke_progress, .8)

    def test_artist_is_default_and_export_keeps_layer_colours(self):
        from app import Window
        w = Window()
        try:
            self.assertEqual(w.image_animation_style.currentText(), 'Artist (layered)')
            result = self.build('artist')
            w.source_type.setCurrentIndex(1)
            w.image_ready(result)
            with tempfile.TemporaryDirectory() as tmp:
                svg, _ = w.export_svg(folder=tmp)
                text = svg.read_text(encoding='utf-8')
                from engine import import_svg
                back = import_svg(svg)
            self.assertIn('stroke="#A3ABB6"', text)
            self.assertEqual(back.strokes[0].color.lower()[:7], '#a3abb6')
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
