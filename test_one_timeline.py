"""exp.55: one timeline for the whole video, new elements with their own artwork,
camera moves never land on an earlier element, steady handwriting at any Letter
detail, the Hand tab pictures."""
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

import board

HERE = Path(__file__).parent


def sample_font():
    for p in ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/segoeui.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'):
        if Path(p).is_file():
            return Path(p)
    return None


class BoardTests(unittest.TestCase):
    def test_pan_back_does_not_land_on_an_earlier_element(self):
        A = 9 / 16
        f = board.frames([dict(transition='Pan right'), dict(transition='Pan left'),
                          dict(transition='Pan left'), dict(transition='Cut')], A)
        for k in range(1, len(f)):
            for j in range(k):
                self.assertEqual(board.overlap(f[j], f[k], A), 0., (j, k, f))
        self.assertLess(f[2][0], 0)                        # carried on to the left of element 1
        # Same page still means the same place.
        f = board.frames([dict(transition='Same page'), dict(transition='Cut')], A)
        self.assertEqual(f[0], f[1])


@unittest.skipIf(SKIP, 'needs Qt')
class FontTests(unittest.TestCase):
    def test_letter_detail_keeps_the_writing_steady_and_sharp(self):
        font = sample_font()
        if font is None:
            self.skipTest('no TTF here')
        from font_stroke_reveal import create_font_drawing, _stroke_schedule
        low, high = (create_font_drawing('Hello world!', font, d) for d in (40, 128))
        # The ink is drawn big at both details (sharp letters), the paths follow it.
        self.assertGreater(low.font_ink.size[1], 120)
        self.assertLess(abs(low.font_ink.size[0] - high.font_ink.size[0]), high.font_ink.size[0] * .1)
        W, H = low.font_ink.size
        self.assertTrue(all(0 <= x <= W and 0 <= y <= H for s in low.strokes for x, y in s.points))

        def lifts(d):
            events, total = _stroke_schedule(d)
            real = [e for e in events if e[0] == 'lift' and e[3] - e[2] > ((e[5][0] - e[4][0]) ** 2 + (e[5][1] - e[4][1]) ** 2) ** .5 * .99 + 1e-6]
            return events, real, total
        for d in (low, high):
            events, real, total = lifts(d)
            self.assertLess(len(real), 40)                 # not a stop at every little piece
        a, b = len(lifts(low)[1]), len(lifts(high)[1])
        self.assertLess(abs(a - b), max(6, a))             # about the same rhythm


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); self.app.processEvents()
        self.w.duration.setValue(2.)

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()

    def test_new_element_and_one_timeline(self):
        w = self.w
        first = w.drawing
        self.assertTrue(w.new_element('file', path=str(HERE / 'samples' / 'arthur-headset-traced.svg')))
        self.app.processEvents()
        self.assertEqual(len(w.scenes), 2)
        self.assertIsNot(w.drawing, first)                 # its own artwork, not a copy
        self.assertEqual(w.scenes[1]['name'], 'arthur-headset-traced')
        self.assertEqual(w.preview_scope.currentIndex(), 1)   # the whole video
        tl = w.stage_timeline
        segs = tl.scene_segments
        self.assertEqual([s[2] for s in segs], ['scene', 'join', 'scene'])
        self.assertTrue(all(s[3] for s in segs if s[2] == 'scene'))   # each element shows its parts
        self.assertGreater(tl.offset, 0)                   # element 2 starts after element 1 and the move
        lengths, joins = w.scene_timeline()
        self.assertAlmostEqual(tl.total(), sum(lengths) + sum(joins), places=3)
        self.assertAlmostEqual(tl.element_length(), lengths[1], places=2)
        # The edited element's edges can be dragged on the whole-video timeline.
        keys = [k for k, _, _ in tl._edges()]
        self.assertIn('draw', keys)
        w.set_stage_seconds('draw', 3.)
        self.assertAlmostEqual(w.duration.value() / w.speed.value(), 3., places=1)
        # A click on element 1's block works on element 1.
        tl.element_clicked.emit(0); self.app.processEvents()
        self.assertEqual(w.scene_index, 0)
        self.assertEqual(w.preview_scope.currentIndex(), 1)
        # Text element.
        self.assertTrue(w.new_element('text', text='Hi there'))
        self.assertEqual(len(w.scenes), 3)
        self.assertEqual(w.scene_label(w.scene_index), 'Hi there')
        # Playing the whole video works everywhere.
        for v in (100, 450, 800, 990):
            w.slider.setValue(v)
            self.assertFalse(w.canvas.frame.isNull())

    def test_hand_tab_pictures(self):
        w = self.w
        w.refresh(); self.app.processEvents()
        self.assertIsNotNone(w.hand_pictures['draw'].pixmap())
        self.assertFalse(w.hand_pictures['draw'].pixmap().isNull())
        w.showhand.setChecked(False); self.app.processEvents()
        self.assertEqual(w.hand_pictures['draw'].text(), 'hidden')


if __name__ == '__main__':
    unittest.main(verbosity=2)
