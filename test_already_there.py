"""exp.206: an element Already there is finished on its page from the start of the video."""
import unittest

from timeline_model import layout, state_at


class AlreadyThereTests(unittest.TestCase):
    def test_finished_from_the_start_and_camera_goes_there_in_turn(self):
        lay = layout([4., 1., 3.], [0., 1., 0.], already=[False, True, False])
        self.assertFalse(lay.sequential)
        self.assertEqual([it.start for it in lay.items], [0., 4., 6.])
        early = state_at(lay, .5)
        self.assertIn(1, early.finished)
        self.assertNotIn(1, [k for k, _ in early.active])
        self.assertEqual(early.current, 0)
        self.assertEqual(state_at(lay, 4.5).current, 1)      # the camera looks at it in its turn
        self.assertEqual(state_at(lay, 4.5).top, -1)         # no hand

    def test_seconds_and_no_effect(self):
        from frame_render import timeline_seconds, move_seconds, ALREADY_LOOK
        self.assertEqual(move_seconds({'entrance': 'Already'}), 0.)
        self.assertEqual(timeline_seconds(None, {'entrance': 'Already'}), ALREADY_LOOK)
        self.assertEqual(timeline_seconds(None, {'entrance': 'Already', 'pause': 2.5}), 2.5)


if __name__ == '__main__':
    unittest.main()
