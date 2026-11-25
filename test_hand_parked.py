"""exp.236 (the user: at the end of the new picture the hand did not go back to its corner,
it left the frame): a Hand motion clip that stays leaves the hand parked only until the next
drawing's hand has come in; after that, the waiting hand is in its own corner again."""
import unittest

import camera_clips


class ParkedUntil(unittest.TestCase):
    def clip(self, start=2., duration=1.):
        return {'start': start, 'duration': duration, 'kind': camera_clips.MOVE}

    def test_ends_when_the_next_hand_has_come_in(self):
        self.assertEqual(camera_clips.parked_until(self.clip(), [(5., 1.5), (10., 1.)]), 6.5)

    def test_a_hand_that_started_before_the_clip_ended_does_not_count(self):
        self.assertEqual(camera_clips.parked_until(self.clip(), [(1., 1.), (2.5, 1.), (8., 1.)]), 9.)

    def test_no_next_hand_parks_to_the_end(self):
        self.assertIsNone(camera_clips.parked_until(self.clip(), [(0., 1.)]))
        self.assertIsNone(camera_clips.parked_until(self.clip()))


if __name__ == '__main__':
    unittest.main()
