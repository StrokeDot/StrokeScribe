"""Faster export on several CPU cores: same frames, less time."""
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'

import parallel_export


class WorkerCountTests(unittest.TestCase):
    def test_choice(self):
        old = os.environ.pop('STROKESCRIBE_EXPORT_WORKERS', None)
        try:
            self.assertEqual(parallel_export.worker_count(30), 1)            # short: one core
            self.assertEqual(parallel_export.worker_count(5000, 1), 1)       # switched off
            self.assertEqual(parallel_export.worker_count(10, 3), 3)         # explicit
            cores = os.cpu_count() or 1
            expected = 1 if cores < 3 else min(cores - 1, parallel_export.MAX_WORKERS)
            self.assertEqual(parallel_export.worker_count(5000), expected)
            os.environ['STROKESCRIBE_EXPORT_WORKERS'] = '1'
            self.assertEqual(parallel_export.worker_count(5000), 1)
        finally:
            os.environ.pop('STROKESCRIBE_EXPORT_WORKERS', None)
            if old is not None:
                os.environ['STROKESCRIBE_EXPORT_WORKERS'] = old


@unittest.skipIf(SKIP, 'needs Qt')
class ParallelExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def scene(self):
        from PIL import Image, ImageDraw
        from PySide6.QtGui import QImage
        from engine import import_svg
        import tools_kit
        from export_job import builtin_eraser
        from eraser import ERASER_TIP
        drawing = import_svg(Path(__file__).parent / 'samples' / 'drawing.svg')
        x0, y0, x1, y1 = drawing.bounds
        w, h = round(x1 - x0), round(y1 - y0)
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((w * .25, h * .35, w * .55, h * .8), fill=(220, 120, 60, 255))
        d.ellipse((w * .65, h * .1, w * .85, h * .4), fill=(250, 200, 40, 255))
        colour = QImage(img.tobytes(), w, h, QImage.Format.Format_RGBA8888).copy()
        hand = tools_kit.builtin_image('hand')
        brush = tools_kit.painting_hand(dict(paint_hand=tools_kit.PAINT_BRUSH, paint_hand_size=30,
                                             handsize=.75, ax=.08, ay=.13), hand)
        options = dict(duration=1.2, fps=12, width=480, height=270, final_image=colour, hand=hand,
                       hand_scale=.75, anchor=(.08, .13), reveal_mode='adaptive', painting_hand=brush,
                       fade_duration=.6, hold_duration=.3, artwork_scale=.9,
                       erase=dict(mode='zigzag', seconds=.8, size=.1, image=builtin_eraser(),
                                  anchor=ERASER_TIP, width=.18))
        return drawing, options

    def frames(self, folder):
        from PIL import Image
        return [np.asarray(Image.open(p).convert('RGBA')) for p in sorted(Path(folder).glob('frame_*.png'))]

    def test_same_frames_on_one_or_several_cores(self):
        from engine import export_frames
        import json
        drawing, options = self.scene()
        progress = []
        one = export_frames(drawing, self.dir / 'one', workers=1, **options)
        many = export_frames(drawing, self.dir / 'many', workers=3,
                             callback=lambda i, n: progress.append(i), **options)
        self.assertEqual(one, many)
        info = json.loads((self.dir / 'many' / 'sequence.json').read_text())
        self.assertEqual(info['cpu_workers'], 3)                 # really ran on 3 workers
        self.assertEqual(max(progress), many)
        a, b = self.frames(self.dir / 'one'), self.frames(self.dir / 'many')
        self.assertEqual(len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            self.assertTrue(np.array_equal(x, y), f'frame {i} differs')
        # Something was drawn, painted and erased.
        self.assertGreater(a[len(a) // 2][..., 3].max(), 0)
        self.assertEqual(a[-1][..., 3].max(), 0)

    def test_cancel(self):
        from engine import export_frames
        drawing, options = self.scene()
        with self.assertRaises(InterruptedError):
            export_frames(drawing, self.dir / 'stop', workers=2, callback=lambda i, n: i < 12, **options)

    def test_speed(self):
        """Not a strict test (shared CI machines vary): prints the speed-up."""
        from engine import export_frames
        drawing, options = self.scene()
        options.update(duration=5., fps=24, width=960, height=540, erase=None)
        start = time.perf_counter()
        export_frames(drawing, self.dir / 'seq', workers=1, **options)
        single = time.perf_counter() - start
        start = time.perf_counter()
        export_frames(drawing, self.dir / 'par', workers=0, **options)
        multi = time.perf_counter() - start
        cores = os.cpu_count() or 1
        print(f'\nEXPORT SPEED: {cores} cores, one core {single:.1f} s, all cores {multi:.1f} s, '
              f'x{single / max(multi, 1e-6):.2f}')
        if cores >= 4:
            self.assertLess(multi, single)


if __name__ == '__main__':
    unittest.main(verbosity=2)
