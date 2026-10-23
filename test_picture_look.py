"""exp.98: Colour, Light and Ink on the page (picture_look)."""
import os
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


def scene():
    """A grey 'room' (the square problem) with dark ink lines on it, fully opaque."""
    rgba = np.ones((60, 90, 4), np.float32)
    rgba[..., :3] = .62                       # the picture's own grey paper
    rgba[20:40, 10:80, :3] = .1               # ink
    return rgba


class LookMathTests(unittest.TestCase):
    def test_nothing_on_changes_nothing(self):
        import picture_look as pl
        a = scene()
        self.assertTrue(np.allclose(pl.adjust_array(a, {}), a))
        self.assertTrue(np.allclose(pl.colour(a[..., :3]), a[..., :3]))
        self.assertTrue(np.allclose(pl.light(a[..., :3]), a[..., :3], atol=1e-6))

    def test_ink_removes_the_paper_square_and_keeps_the_lines(self):
        import picture_look as pl
        out = pl.adjust_array(scene(), {'ink_on': True, 'ink_edges': 'No fading'})
        self.assertLess(out[5, 45, 3], .05)                  # the grey paper: see-through
        self.assertGreater(out[30, 45, 3], .9)               # the lines: ink
        self.assertTrue(np.allclose(out[30, 45, :3], np.array([41, 41, 44]) / 255.))

    def test_a_picture_that_is_all_paper_disappears(self):
        import picture_look as pl
        flat = np.ones((20, 30, 4), np.float32); flat[..., :3] = .62
        out = pl.adjust_array(flat, {'ink_on': True, 'ink_edges': 'No fading'})
        self.assertLess(out[..., 3].max(), .05)

    def test_edges(self):
        import picture_look as pl
        soft = pl.adjust_array(scene(), {'ink_on': True, 'ink_edges': 'Soft edges', 'ink_edge_size': 30})
        oval = pl.adjust_array(scene(), {'ink_on': True, 'ink_edges': 'Oval fade', 'ink_edge_size': 15})
        self.assertLess(soft[30, 10, 3], soft[30, 45, 3])    # the ink near the border fades
        self.assertLess(oval[22, 12, 3], oval[30, 45, 3])    # and further toward the corners in an oval
        self.assertEqual(soft[30, 0, 3], 0.)

    def test_more_removal_and_strength(self):
        import picture_look as pl
        a = scene(); a[..., :3] += np.linspace(0, .25, 90)[None, :, None]   # an uneven paper tone
        base = {'ink_on': True, 'ink_edges': 'No fading'}
        low = pl.adjust_array(a, dict(base, ink_removal=10))[..., 3].mean()
        high = pl.adjust_array(a, dict(base, ink_removal=90))[..., 3].mean()
        self.assertLess(high, low)
        weak = pl.adjust_array(a, dict(base, ink_strength=50))[..., 3].mean()
        self.assertLess(weak, pl.adjust_array(a, base)[..., 3].mean())

    def test_light_and_colour_move_the_right_way(self):
        import picture_look as pl
        rgb = np.full((4, 4, 3), .5, np.float32)
        self.assertGreater(pl.light(rgb, exposure=50).mean(), .5)
        self.assertLess(pl.light(rgb, blacks=-60).mean(), .5)
        self.assertGreater(pl.light(np.full((2, 2, 3), .8, np.float32), whites=80).mean(), .8)
        warm = pl.colour(rgb, temperature=60)
        self.assertGreater(warm[..., 0].mean(), warm[..., 2].mean())
        grey = pl.colour(np.array([[[.8, .2, .2]]], np.float32), saturation=-100)
        self.assertAlmostEqual(float(grey.std()), 0., places=5)


@unittest.skipIf(SKIP, 'needs Qt')
class LookAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def picture(self):
        from PySide6.QtGui import QColor, QImage
        im = QImage(90, 60, QImage.Format.Format_ARGB32_Premultiplied)
        im.fill(QColor(158, 158, 158))
        return im

    def test_export_options_use_the_look(self):
        from engine import import_svg
        from export_job import options_from_settings
        d = import_svg(HERE / 'samples' / 'drawing.svg')
        im = self.picture()
        plain = options_from_settings({'use_color': True}, d, color_image=im)
        self.assertIs(plain['final_image'], im)                       # nothing on: the same picture
        inked = options_from_settings({'use_color': True, 'ink_on': True}, d, color_image=im)
        self.assertIsNot(inked['final_image'], im)
        again = options_from_settings({'use_color': True, 'ink_on': True}, d, color_image=im)
        self.assertIs(again['final_image'], inked['final_image'])     # cached: frame caches stay valid
        self.assertLess(inked['final_image'].pixelColor(45, 30).alpha(), 20)   # grey paper: see-through

    def test_panel_and_projects(self):
        from app import Window
        from engine import import_svg
        w = Window()
        try:
            w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
            self.assertFalse(w.ink_on.isChecked())
            w.section_ink.switch.click()
            self.assertTrue(w.ink_on.isChecked())
            self.assertTrue(w.section_ink.expanded)                     # turning it on opens it
            w.ink_edges.setCurrentText('Oval fade'); w.ink_removal.setValue(70); w.commit_history()
            state = w.settings_state()
            self.assertTrue(state['ink_on']); self.assertEqual(state['ink_edges'], 'Oval fade')
            self.assertEqual(state['ink_removal'], 70)
            w.ink_removal.setValue(10); w.commit_history(); w.undo()
            self.assertEqual(w.ink_removal.value(), 70)                 # undo works for it
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
