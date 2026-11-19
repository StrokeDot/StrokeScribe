"""exp.46 (the user: a Hand motion should have the same kind of choices): its shape (a curve
through the points, or straight from point to point) goes with any of its speeds."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class MotionShape(unittest.TestCase):
    def at(self, line, how, t):
        from frame_render import hand_motion_at
        move = dict(start=0., duration=1., how=how, path=((.5, .0), (1., .5)), back=False, until=None, line=line)
        return hand_motion_at(dict(_hand_moves=(move,)), t, (0., 0.), (0., 0., 100., 100.), (100, 100))

    def test_straight_goes_along_the_lines(self):
        for how in ('Smooth', 'Steady', 'Quick start'):
            for t in (.1, .3, .6, .9):
                x, y = self.at('straight', how, t)
                on_first = abs(y) < 1e-6 and 0 <= x <= 50 + 1e-6               # (0,0) -> (50,0)
                on_second = abs((y - 0) - (x - 50)) < 1e-6 and 50 - 1e-6 <= x <= 100   # (50,0) -> (100,50)
                self.assertTrue(on_first or on_second, (how, t, x, y))

    def test_curve_is_the_old_way_and_speeds_differ(self):
        x, y = self.at(None, 'Smooth', .3)
        self.assertGreater(abs(y), 1e-3)                       # a curve leaves the straight line
        self.assertNotEqual(self.at('straight', 'Steady', .2), self.at('straight', 'Quick start', .2))

    def test_it_travels_with_the_clip(self):
        import camera_clips
        clip = dict(id='m', kind=camera_clips.MOVE, start=1., duration=2., path=[[.5, .5]], line='straight')
        self.assertEqual(camera_clips.hand_moves([clip])[0]['line'], 'straight')
        from frame_render import _moves_of
        sig = camera_clips.hand_signature([clip])
        self.assertEqual(_moves_of(dict(hand_away=sig))[0]['line'], 'straight')


if __name__ == '__main__':
    unittest.main()
