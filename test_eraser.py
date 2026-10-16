"""Erase stage: zigzag over the picture, along the lines, timeline, export, sound."""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'


def alpha_sum(image):
    from adaptive_hand import pil_image
    return int(np.asarray(pil_image(image).getchannel('A'), np.int64).sum())


@unittest.skipIf(SKIP, 'needs Qt')
class EraserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from engine import import_svg
        cls.drawing = import_svg(Path(__file__).parent / 'samples' / 'drawing.svg')

    def options(self, mode, **extra):
        from export_job import builtin_eraser
        from eraser import ERASER_TIP
        o = dict(width=480, height=270, duration=2., fade_duration=.4, hold_duration=.5,
                 final_image=None, thickness=1., hand=None, hand_scale=.2, anchor=(.1, .1),
                 reveal_mode='adaptive', brush_width=.14, painting_hand=None, stroke_spacing=.55,
                 artwork_scale=1.,
                 erase=dict(mode=mode, seconds=2., size=.08, image=builtin_eraser(), anchor=ERASER_TIP,
                            width=.18) if mode else None)
        o.update(extra)
        return o

    def test_timeline_gets_an_erase_stage(self):
        from frame_render import timeline_seconds
        self.assertAlmostEqual(timeline_seconds(self.drawing, self.options(None)), 2.)
        self.assertAlmostEqual(timeline_seconds(self.drawing, self.options('zigzag')), 4.)

    def test_both_styles_erase_everything_gradually(self):
        from frame_render import compose_frame
        for mode in ('zigzag', 'lines'):
            o = self.options(mode)
            full = alpha_sum(compose_frame(self.drawing, .5 - 1e-9, o))     # end of drawing (t=2 s)
            done_drawing = alpha_sum(compose_frame(self.drawing, .499, o))
            middle = alpha_sum(compose_frame(self.drawing, .75, o))           # half way erasing
            late = alpha_sum(compose_frame(self.drawing, .93, o))
            end = alpha_sum(compose_frame(self.drawing, 1., o))
            self.assertGreater(full, 0, mode)
            self.assertGreater(done_drawing, 0, mode)
            self.assertLess(late, full, mode)
            self.assertLessEqual(late, middle + 1, mode)
            self.assertEqual(end, 0, f'{mode}: picture fully erased at the end')

    def test_eraser_is_shown_and_followed_by_the_pen_track(self):
        import motion
        from frame_render import compose_frame
        o = self.options('zigzag')
        samples = motion.track(self.drawing, o, 4., 20)
        kinds = [s.kind for t, s in samples if t > 2.05 and t < 3.8]
        self.assertGreater(kinds.count('erase'), len(kinds) * .5)
        drawing_kinds = [s.kind for t, s in samples if .1 < t < 1.9]
        self.assertTrue(all(k == 'draw' for k in drawing_kinds))
        # The eraser image appears where the eraser is.
        t = next(t for t, s in samples if s.kind == 'erase' and t > 2.6)
        with_eraser = compose_frame(self.drawing, t / 4., o)
        o2 = self.options('zigzag'); o2['erase'] = dict(o2['erase'], image=None)
        without = compose_frame(self.drawing, t / 4., o2)
        self.assertGreater(alpha_sum(with_eraser), alpha_sum(without))

    def test_lettering_background_survives_erasing(self):
        from frame_render import compose_frame
        import copy
        d = copy.deepcopy(self.drawing)
        d.source_kind = 'lettering'; d.lettering_background = '#ffffff'
        frame = compose_frame(d, 1., self.options('zigzag'))
        self.assertEqual(frame.pixelColor(5, 5).name(), '#ffffff')

    def test_export_ends_blank_and_has_rubbing_sound(self):
        from engine import export_frames
        from PySide6.QtGui import QImage
        from sound import soundtrack
        import wave
        o = self.options('lines')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'out'
            count = export_frames(self.drawing, folder, fps=8, **o)
            self.assertEqual(count, 32)
            last = QImage(str(folder / f'frame_{count - 1:06d}.png'))
            self.assertEqual(alpha_sum(last), 0)
            path = soundtrack(self.drawing, dict(o, fps=8), folder / 's.wav', .8)
            with wave.open(str(path)) as f:
                data = np.frombuffer(f.readframes(f.getnframes()), np.int16).reshape(-1, 2)
            rate = 44100
            erase_part = data[int(2.3 * rate):int(3.5 * rate)].astype(float)
            self.assertGreater(np.sqrt((erase_part ** 2).mean()), 300)

    def test_settings_and_window(self):
        from export_job import erase_from_settings
        from PySide6.QtGui import QImage
        self.assertIsNone(erase_from_settings({'erase_mode': 'Off'}))
        e = erase_from_settings({'erase_mode': 'Along the lines', 'erase_time': 4, 'erase_size': 10})
        self.assertEqual((e['mode'], e['seconds'], e['size']), ('lines', 4., .1))
        self.assertFalse(e['image'].isNull())
        hand = QImage(10, 10, QImage.Format.Format_ARGB32)
        e = erase_from_settings({'erase_mode': 'Zigzag (follows the shapes)', 'eraser': 'Pen hand',
                                 'ax': .2, 'ay': .3, 'handsize': .5}, hand)
        self.assertIs(e['image'], hand)
        self.assertEqual(e['anchor'], (.2, .3))
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        w.erase_mode.setCurrentIndex(1)
        w.erase_time.setValue(2.5)
        self.assertAlmostEqual(w.stage_timeline.erase_seconds, 2.5)
        self.assertAlmostEqual(w.timeline_length(), w.effective_duration() + 2.5)
        w.slider.setValue(1000)
        self.assertEqual(alpha_sum(w.canvas.frame), 0)
        w.slider.setValue(round(1000 * (w.effective_duration() + .2) / w.timeline_length()))
        self.assertGreater(alpha_sum(w.canvas.frame), 0)
        self.assertIn('erase_mode', w.settings_state())


if __name__ == '__main__':
    unittest.main(verbosity=2)
