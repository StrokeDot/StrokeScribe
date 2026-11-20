"""exp.37 (the user: "a quick start with a curved way"): a hand way's shape and speed combine."""
import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class WayStyle(unittest.TestCase):
    def test_the_older_choices_mean_the_same(self):
        from frame_render import split_style, join_style, _glide_ease
        for old in ('Smooth', 'Steady', 'Quick start', 'Slow start', 'Overshoot', 'Curve', 'Swoop', 'Circle'):
            self.assertEqual(join_style(*[(x or 'Smooth') for x in split_style(old)]), old)
        # their timing is unchanged (the same numbers as before exp.37)
        p = .3
        self.assertAlmostEqual(_glide_ease(p, 'Curve'), p ** 3 * (p * (6 * p - 15) + 10))
        self.assertAlmostEqual(_glide_ease(p, 'Swoop'), p * p * (3 - 2 * p))
        self.assertAlmostEqual(_glide_ease(p, 'Quick start'), 1 - (1 - p) ** 5)

    def test_a_curve_with_a_quick_start(self):
        from frame_render import _glide_ease, glide_point
        style = 'Curve + Quick start'
        self.assertAlmostEqual(_glide_ease(.3, style), _glide_ease(.3, 'Quick start'))   # its speed
        a, b = (0., 0.), (100., 0.)
        mid_curve = glide_point(a, b, .5, 'Curve', (50., 50.))
        mid_combo = glide_point(a, b, .5, style, (50., 50.))
        mid_straight = glide_point(a, b, .5, 'Quick start', (50., 50.))
        bend = max(abs(glide_point(a, b, i / 50., style, (50., 50.))[1]) for i in range(51))
        self.assertGreater(bend, 20)                                   # it bends like a Curve
        self.assertAlmostEqual(mid_straight[1], 0.)
        self.assertGreater(mid_combo[0], mid_curve[0])                # and is further along (quick start)

    def test_the_box_reads_and_writes_the_text(self):
        from app import WayStyleBox
        box = WayStyleBox('Swoop + Overshoot')
        self.assertEqual((box.shape.currentText(), box.speed.currentText()), ('Swoop', 'Overshoot'))
        box.shape.setCurrentText('Straight')
        self.assertEqual(box.currentText(), 'Overshoot')
        box.setCurrentText('Curve')
        self.assertEqual((box.shape.currentText(), box.speed.currentText(), box.currentText()), ('Curve', 'Smooth', 'Curve'))


if __name__ == '__main__':
    unittest.main()
