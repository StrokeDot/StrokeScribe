"""exp.22 (the user: an element made longer overlapped the next one): when an element's own time
changes, everything after its end moves by the same time; gaps and free placement stay."""
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from app import Window  # noqa: E402
from timeline_model import layout  # noqa: E402


def stub(scenes, lengths, joins=None, cameras=None, overlays=None, tracks=None):
    joins = joins or [0.] * len(scenes)
    w = SimpleNamespace(scenes=scenes, drawing=object(), scene_index=0, cameras=cameras or [],
                        overlays=overlays or [], video_end=None, lengths=lengths,
                        status=SimpleNamespace(text='', setText=lambda t: setattr(w.status, 'text', t)),
                        project_changes=SimpleNamespace(mark_changed=lambda: None))
    w.timeline_layout = lambda: layout(w.lengths, joins, [s.get('start') for s in scenes],
                                       tracks or [0] * len(scenes))
    w.scene_timeline = lambda: (w.lengths, joins)
    w.follow = lambda: Window.follow_lengths(w)
    return w


class FollowLengths(unittest.TestCase):
    def test_a_longer_element_pushes_what_comes_after_and_keeps_the_gaps(self):
        scenes = [dict(start=None), dict(start=5.), dict(start=11.)]
        hand = dict(id='h', kind='Hand motion', start=6., duration=1.)
        early = dict(id='z', start=1., duration=1.)
        w = stub(scenes, [4., 4., 4.], cameras=[hand, early], overlays=[dict(start=9.)])
        w.follow()                                   # first look
        w.lengths = [6., 4., 4.]
        w.follow()
        self.assertEqual([s['start'] for s in scenes], [None, 7., 13.])
        self.assertEqual(hand['start'], 8.)
        self.assertEqual(early['start'], 1.)        # before its end: stays
        self.assertEqual(w.overlays[0]['start'], 11.)
        self.assertIn('later by 2.0', w.status.text)
        w.lengths = [3., 4., 4.]                    # shorter (or an undo): pulled back
        w.follow()
        self.assertEqual([s['start'] for s in scenes], [None, 4., 10.])
        self.assertEqual(hand['start'], 5.)

    def test_an_element_that_follows_by_itself_is_not_moved_twice(self):
        scenes = [dict(start=None), dict(start=None), dict(start=9.)]
        w = stub(scenes, [4., 4., 4.], joins=[1., 0., 0.])
        w.follow()
        w.lengths = [5., 4., 4.]
        w.follow()
        self.assertIsNone(scenes[1]['start'])       # still right after it (now at 6 s)
        self.assertEqual(scenes[2]['start'], 10.)

    def test_a_change_in_the_middle_leaves_the_earlier_elements(self):
        scenes = [dict(start=None), dict(start=None), dict(start=None)]
        w = stub(scenes, [4., 4., 4.])
        w.follow()
        w.lengths = [4., 6., 4.]
        w.follow()
        self.assertEqual([s['start'] for s in scenes], [None, None, None])   # they follow by themselves

    def test_something_placed_to_overlap_it_on_another_track_stays(self):
        scenes = [dict(start=None), dict(start=2., track=1)]
        w = stub(scenes, [4., 4.], tracks=[0, 1])
        w.follow()
        w.lengths = [6., 4.]
        w.follow()
        self.assertEqual(scenes[1]['start'], 2.)

    def test_a_drag_or_another_element_chosen_only_takes_a_new_look(self):
        scenes = [dict(start=None), dict(start=5.)]
        w = stub(scenes, [4., 4.])
        w.follow()
        scenes[1]['start'] = 8.                     # dragged
        w.lengths = [6., 4.]
        w.follow()
        self.assertEqual(scenes[1]['start'], 8.)
        w.scene_index = 1                           # another element chosen
        w.lengths = [7., 4.]
        w.follow()
        self.assertEqual(scenes[1]['start'], 8.)


if __name__ == '__main__':
    unittest.main()
