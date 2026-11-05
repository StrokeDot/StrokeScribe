"""exp.207: the Background row (pieces of the video with their own background)."""
import json
import tempfile
import unittest
from pathlib import Path

import background_track as b


class BackgroundTrackTests(unittest.TestCase):
    def test_split_choose_hide_join(self):
        p = b.split([], 3.)
        self.assertEqual([x['start'] for x in p], [0., 3.])        # the cut stays (like Filmora)
        p = b.set_choice(p, 1, 'Paper')
        p = b.set_hidden(b.split(p, 6.), 2, True)
        self.assertEqual(b.spec_at(p, 1, 'whiteboard'), 'whiteboard')   # the video's Background
        self.assertEqual(b.spec_at(p, 4, 'whiteboard'), 'paper')
        self.assertEqual(b.spec_at(p, 7, 'whiteboard'), 'transparent')
        self.assertEqual(b.ranges(p, 10), [(0, 0., 3.), (1, 3., 6.), (2, 6., 10.)])
        self.assertEqual([x['start'] for x in b.move_cut(p, 2, 4.)], [0., 3., 4.])
        self.assertEqual(b.move_cut(p, 2, 1.)[2]['start'], 3.1)       # not past its neighbour
        self.assertEqual(len(b.remove_cut(p, 1)), 2)
        self.assertEqual(b.tidy(b.remove_cut(b.split([], 3.), 1)), [])   # nothing of its own: no pieces

    def test_custom_colour(self):
        p = b.set_choice(b.split([], 2.), 0, 'Custom colour…', '#ff8800')
        self.assertEqual(b.spec_at(p, 1, 'white'), '#ff8800')

    def test_bake_puts_each_frame_on_its_background(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'sequence.json').write_text(json.dumps({'width': 8, 'height': 6}))
            for i in range(4):
                Image.new('RGBA', (8, 6), (0, 0, 0, 0)).save(folder / f'frame_{i:06d}.png')
            pieces = b.set_hidden(b.set_choice(b.split([], 2 / 10.), 0, 'Black'), 1, True)
            out = b.bake(folder, 10, pieces, 'white')
            first = Image.open(out / 'frame_000000.png').convert('RGBA').getpixel((1, 1))
            last = Image.open(out / 'frame_000003.png').convert('RGBA').getpixel((1, 1))
            self.assertEqual(first, (0, 0, 0, 255))      # black piece
            self.assertEqual(last[3], 0)                  # hidden: transparent
            self.assertTrue((out / 'sequence.json').is_file())


if __name__ == '__main__':
    unittest.main()
