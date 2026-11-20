"""exp.45 (the user: during the circle the hand stops before the end): with "Hand: everything",
a shape without a head uses the whole drawing time for its line; the pen never stands still
while it draws."""
import math
import unittest



def _new(*a, **kw):
    """These tests time the drawing from 'start' (the pen's moment); since exp.70 a new sticker's
    clip starts with its hand's way in, so they use the drawing-at-start timing (test_hand_timing
    covers the new one)."""
    import stickers
    item = stickers.new(*a, **kw); item['clip_v2'] = False
    return item

class Pace(unittest.TestCase):
    def pen_track(self, shape, mode):
        import stickers
        item = dict(_new(shape, start=0.), drawing=mode, draw_seconds=2.)
        w = 300.; h = w * stickers.ASPECT.get(shape, .4)
        return [stickers.pen_point(item, w, h, 540., t / 50.) for t in range(101)]

    def test_circle_and_line_draw_until_the_end(self):
        for shape in ('Circle', 'Hand-drawn circle', 'Line', 'Wavy line'):
            for mode in ('Hand: outline', 'Hand: everything'):
                track = self.pen_track(shape, mode)
                # it still moves in the last tenth of the drawing time
                moved = sum(math.dist(a, b) for a, b in zip(track[90:], track[91:]))
                self.assertGreater(moved, 1., (shape, mode))

    def test_an_arrow_still_draws_its_head(self):
        import stickers
        item = dict(_new('Arrow', start=0.), drawing='Hand: everything', draw_seconds=2.)
        line, head = stickers.phases(item, 1.9)
        self.assertEqual(line, 1.)
        self.assertGreater(head[0], 0.)                  # the head strokes come after the line


if __name__ == '__main__':
    unittest.main()
