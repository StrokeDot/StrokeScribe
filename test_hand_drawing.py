"""1.0.1-experimental.1: Hand drawing (real strokes, the picture appearing as lines that follow
its own pencil marks) and the built-in pencil-on-paper sound."""
import math
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')     # closing a test window: no question
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


@dataclass(frozen=True)
class Pen:
    point: tuple | None
    kind: str | None


def hatched(size=(200, 140)):
    """A pencil-like picture: diagonal hatching (dark) on the left, sparse vertical lines on the
    right (a second part), on a transparent background around it."""
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    p = ImageDraw.Draw(im)
    p.rectangle((6, 6, size[0] - 7, size[1] - 7), fill=(235, 235, 230, 255))
    for k in range(-size[1], size[0] // 2, 5):                     # left: lines at 45 degrees
        p.line((k, size[1] - 6, k + size[1], 6), fill=(60, 60, 60, 255), width=2)
    p.rectangle((size[0] // 2, 6, size[0] - 7, size[1] - 7), fill=(170, 40, 40, 255))
    for x in range(size[0] // 2 + 4, size[0] - 7, 6):              # right: vertical lines
        p.line((x, 8, x, size[1] - 9), fill=(110, 20, 20, 255), width=2)
    return im


@unittest.skipIf(SKIP, 'needs Qt')
class HandDrawingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def drawing(self, w=200, h=140):
        from engine import Drawing, Stroke
        return Drawing([Stroke('outline', [(6, 6), (w - 6, 6), (w - 6, h - 6), (6, h - 6), (6, 6)], width=2),
                        Stroke('last', [(w - 10, h - 10), (w - 8, h - 10)], width=2)], (0, 0, w, h), [])

    def plan(self):
        from adaptive_hand import qimage
        from stroke_paint import build_stroke_plan
        pil = hatched()
        image = qimage(pil)
        return pil, image, build_stroke_plan(self.drawing(), image, .1, .5)

    def test_every_visible_pixel_is_drawn_and_drawing_only_grows(self):
        import stroke_paint
        pil, image, plan = self.plan()
        moments, alpha = stroke_paint.field_for(plan, image)
        self.assertTrue(np.isfinite(moments[alpha > 0]).all())        # nothing is left out
        before = np.zeros(moments.shape, np.uint8)
        for p in (0., .1, .3, .5, .7, .9, .98, 1.):
            now = stroke_paint.stroke_alpha(plan, image, p)
            self.assertTrue((now >= before).all())                     # once drawn, it stays
            before = now
        self.assertEqual(int(stroke_paint.stroke_alpha(plan, image, 0.).max()), 0)
        self.assertTrue((stroke_paint.stroke_alpha(plan, image, 1.) == 255).all())

    def test_the_picture_appears_along_its_own_marks(self):
        """With pencil lines, the moment pixels appear changes little along the picture's own
        hatching (a line appears as a whole, growing along itself) and much more across it."""
        import stroke_paint
        pil, image, plan = self.plan()
        old = stroke_paint.PENCIL_LINES
        try:
            stroke_paint.PENCIL_LINES = False
            plain = stroke_paint.build_field(plan, image)[0]
        finally:
            stroke_paint.PENCIL_LINES = old
        lines = stroke_paint.build_field(plan, image)[0]

        def along_vs_across(m, d=3):
            left = m[:, :m.shape[1] // 2 - 6]                # the hatching runs up-right there
            with np.errstate(invalid='ignore'):           # never-drawn pixels (inf) are skipped
                along = np.abs(left[d:, :-d] - left[:-d, d:])
                across = np.abs(left[d:, d:] - left[:-d, :-d])
            ok = np.isfinite(along) & np.isfinite(across)
            return float(np.median(along[ok])) / max(1e-9, float(np.median(across[ok])))
        self.assertLess(along_vs_across(lines), .8)
        self.assertLess(along_vs_across(lines), along_vs_across(plain) * .8)

    def test_lines_follow_the_direction_of_the_marks(self):
        from pencil_lines import directions
        h, w = 120, 160
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        angle = math.radians(30.)                     # stripes running at 30 degrees (y down)
        across = -x * math.sin(angle) + y * math.cos(angle)
        gray = (.5 + .5 * np.sin(across * 2 * math.pi / 6.)).astype(np.float32)
        dx, dy = directions(gray, 1.)
        found = np.degrees(np.arctan2(dy[20:-20, 20:-20], dx[20:-20, 20:-20])) % 180.
        self.assertLess(abs(float(np.median(found)) - 30.), 6.)
        faint = (.5 + .03 * np.sin(across * 2 * math.pi / 6.)).astype(np.float32)   # light shading
        dx, dy = directions(faint, 1.)
        found = np.degrees(np.arctan2(dy[20:-20, 20:-20], dx[20:-20, 20:-20])) % 180.
        self.assertLess(abs(float(np.median(found)) - 30.), 8.)
        flat = np.full((h, w), .8, np.float32)        # no marks: lines lean the way a hand hatches
        dx, dy = directions(flat, 1.)
        lean = float(np.degrees(np.arctan2(dy[60, 80], dx[60, 80]))) % 180.
        self.assertLess(abs(lean - (-55. % 180.)), 3.)

    def test_lines_stay_in_their_part_and_finish_with_it(self):
        """A part drawn later never shows lines early, and every line of a part is drawn by
        the time the brush leaves the part."""
        from pencil_lines import pencil_moments
        h, w = 80, 120
        regions = np.ones((h, w), np.int32); regions[:, 60:] = 2
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        moments = np.where(regions == 1, x / 10. + y / 100., 100. + (x - 60) / 10. + y / 100.).astype(np.float32)
        rgb = np.full((h, w, 3), 200, np.uint8)
        rgb[:, ::4] = 40                               # vertical marks everywhere
        out = pencil_moments(moments, rgb, regions, 6., px_per_cell=1.)
        first, second = regions == 1, regions == 2
        self.assertGreaterEqual(float(out[second].min()), float(moments[second].min()) - 1e-4)
        self.assertLessEqual(float(out[first].max()), float(moments[first].max()) + 1e-4)
        self.assertLessEqual(float(out[second].max()), float(moments[second].max()) + 1e-4)

    def test_hand_drawing_is_a_paint_mode(self):
        from app import REVEAL_MODES
        from export_job import REVEAL_BY_TEXT
        from paint_mode_dialog import DESCRIPTIONS, SHORT
        name = 'Hand drawing — real strokes and lines'
        self.assertEqual(REVEAL_BY_TEXT[name], 'strokes')
        self.assertEqual(REVEAL_MODES[-1], 'strokes')
        self.assertIn(name, DESCRIPTIONS)
        self.assertEqual(SHORT[name], 'Hand drawing')
        from app import Window
        w = Window(); self.addCleanup(w.close)
        self.assertEqual(w.reveal_mode.itemText(REVEAL_MODES.index('strokes')), name)

    def test_renders_with_the_hand(self):
        from color_reveal import render_color_timeline
        pil, image, plan = self.plan()
        frames = [render_color_timeline(self.drawing(), f, 400, 280, duration=1, fade_duration=2,
                                        hold_duration=.2, final_image=image, reveal_mode='strokes',
                                        brush_width=.1, stroke_spacing=.5) for f in (.4, .7, 1.)]
        self.assertTrue(all(not f.isNull() for f in frames))


def track(seconds=6.):
    """Draw a circle, lift, draw a fast line, paint, then nothing."""
    samples = []
    for i in range(int(seconds * 120) + 1):
        t = i / 120
        if t < 2:
            s = Pen((960 + 300 * math.cos(t * 3), 540 + 300 * math.sin(t * 3)), 'draw')
        elif t < 2.5:
            s = Pen((1200, 300), 'lift')
        elif t < 4:
            s = Pen((600 + 400 * (t - 2.5), 700), 'draw')
        elif t < 5.5:
            s = Pen((800 + 200 * math.sin(t * 8), 500), 'paint')
        else:
            s = Pen(None, None)
        samples.append((t, s))
    return samples


class BuiltinSoundTests(unittest.TestCase):
    def test_pencil_on_paper_follows_the_pen(self):
        import sound
        audio = sound.synthesize(track(), 6, 1920, 1080, builtin={'draw': 'pencil', 'paint': 'pencil'})
        self.assertEqual(audio.shape, (6 * sound.RATE, 2))
        mono = audio.astype(float).mean(1)
        rms = lambda a, b: float(np.sqrt((mono[int(a * sound.RATE):int(b * sound.RATE)] ** 2).mean()))
        self.assertGreater(rms(.2, 1.8), 800)               # drawing
        self.assertLess(rms(2.1, 2.4), 5)                   # pen lifted: silent
        self.assertGreater(rms(4.2, 5.3), 300)              # colouring in
        self.assertLess(rms(5.7, 5.95), 5)                  # done: silent
        again = sound.synthesize(track(), 6, 1920, 1080, builtin={'draw': 'pencil', 'paint': 'pencil'})
        self.assertTrue(np.array_equal(audio, again))       # the preview and the export sound the same

    def test_sounds_like_graphite_on_paper(self):
        """Mostly a scratchy 1-6 kHz noise (not a tone, no rumble), brighter when faster."""
        import sound_synth
        rng = np.random.default_rng(3)
        n = 3 * sound_synth.RATE

        def centroid(speed):
            s = np.full(n, float(speed))
            x = sound_synth.tool_sound('pencil', np.cumsum(s) / sound_synth.RATE, s, np.ones(n), rng)
            spec = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2
            f = np.fft.rfftfreq(n, 1 / sound_synth.RATE)
            return float((spec * f).sum() / spec.sum()), spec, f, x
        c, spec, f, x = centroid(50.)
        self.assertGreater(c, 1800.); self.assertLess(c, 6000.)
        low = spec[f < 200].sum() / spec.sum()
        self.assertLess(low, .01)                           # no rumble
        self.assertGreater(centroid(90.)[0], centroid(20.)[0])
        self.assertGreater(float(np.sqrt((centroid(90.)[3] ** 2).mean())),
                           float(np.sqrt((centroid(15.)[3] ** 2).mean())))   # louder when faster

    def test_builtin_sounds_are_chosen_like_files(self):
        import sound
        self.assertTrue(sound.is_builtin('builtin:pencil'))
        self.assertFalse(sound.is_builtin('C:/sounds/pencil.wav'))
        self.assertEqual(sound.sound_name('builtin:pencil'), 'Pencil on paper (built-in)')
        self.assertEqual(sound.sound_name('C:/sounds/my pencil.wav'), 'my pencil')
        # a recording of a tool wins over a built-in sound for it
        rec = (np.sin(np.arange(2 * sound.RATE) * 2 * np.pi * 700 / sound.RATE) * .5).astype(np.float32)
        both = sound.synthesize(track(), 6, 1920, 1080, recordings={'draw': rec}, builtin={'draw': 'pencil'})
        only = sound.synthesize(track(), 6, 1920, 1080, recordings={'draw': rec})
        self.assertTrue(np.array_equal(both, only))


@unittest.skipIf(SKIP, 'needs Qt')
class BuiltinSoundWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_use_the_builtin_pencil_sounds_and_keep_them_in_the_project(self):
        from app import Window
        import projects
        w = Window(); self.addCleanup(w.close)
        self.assertFalse(w.sound_on.isChecked())            # still no sound until you choose one
        w.use_builtin_sounds()
        self.assertTrue(w.sound_on.isChecked())
        self.assertEqual(w.options()['sound_files'], ('builtin:pencil', 'builtin:pencil', 'builtin:eraser'))
        self.assertEqual(w.sound_file_buttons['sound_pencil_file'][0].text(), 'Pencil on paper (built-in)')
        w.set_sound_file('sound_brush_file', 'builtin:brush')
        self.assertEqual(w.sound_file_buttons['sound_brush_file'][0].text(), 'Soft brush (built-in)')
        menu = w.sound_file_buttons['sound_eraser_file'][0].menu()
        self.assertIn('Choose a recording…', [a.text() for a in menu.actions()])
        with tempfile.TemporaryDirectory() as tmp:
            saved = projects.save(Path(tmp) / 'snd', w.project_state())
            other = Window(); self.addCleanup(other.close)
            self.assertTrue(other.open_project(str(saved)))
            self.assertEqual(other.sound_files['sound_brush_file'], 'builtin:brush')
            self.assertEqual(other.sound_files['sound_pencil_file'], 'builtin:pencil')


if __name__ == '__main__':
    unittest.main()


@unittest.skipIf(SKIP, 'needs Qt')
class Exp2Tests(unittest.TestCase):
    """1.0.1-experimental.2: more zigzag, Painter's parts, pencil first then colour."""
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_the_hand_zigzags_along_painters_traces(self):
        """exp.3: big back-and-forth strokes across Painter's traces (visible hand movement)."""
        from adaptive_hand import qimage
        from painter_paint import build_painter_plan
        from stroke_paint import build_stroke_plan
        d = HandDrawingTests.drawing(self)
        image = qimage(hatched())
        painter = build_painter_plan(d, image, .1, .5)
        plan = build_stroke_plan(d, image, .1, .5)
        moves = [s for s in plan.segments if s.painting]
        turns = sum(1 for a, b in zip(moves, moves[1:])
                    if (a.b[0] - a.a[0]) * (b.b[0] - b.a[0]) + (a.b[1] - a.a[1]) * (b.b[1] - b.a[1]) < 0)
        self.assertGreater(turns, len(moves) * .3)             # it keeps turning back: a zigzag
        ring = max(s.radius for s in painter.segments if s.painting) / .75
        legs = sorted(math.dist(s.a, s.b) for s in moves)
        self.assertGreater(legs[len(legs) // 2], ring * .8)    # each stroke spans the trace's band

    def test_nothing_waits_for_the_end(self):
        """exp.3 (Arthur's end "glitch"): faint soft edges the strokes do not reach appear with
        the nearest stroke, not all at once after the last stroke."""
        from PIL import Image
        import stroke_paint
        from adaptive_hand import qimage
        pil = hatched()
        a = np.asarray(pil).copy()
        a[:, :, 3] = np.where(a[:, :, 3] > 0, a[:, :, 3], 6)   # a faint veil all around (like a vignette)
        image = qimage(Image.fromarray(a, 'RGBA'))
        plan = stroke_paint.build_stroke_plan(HandDrawingTests.drawing(self), image, .1, .5)
        moments, alpha = stroke_paint.field_for(plan, image)
        last = max(s.end for s in plan.segments if s.painting)
        visible = alpha > 0
        self.assertTrue(np.isfinite(moments[visible]).all())
        self.assertLessEqual(float(moments[visible].max()), last + 1e-3)
        self.assertLess(float((moments[visible] >= last * .995).mean()), .03)

    def test_hand_drawing_draws_painters_parts_with_the_parts_choice(self):
        import paint_mode_dialog
        self.assertIn('Hand drawing — real strokes and lines', paint_mode_dialog.WITH_PARTS)
        from adaptive_hand import qimage
        from painter_paint import build_painter_plan
        from stroke_paint import build_stroke_plan
        d = HandDrawingTests.drawing(self)
        image = qimage(hatched())
        painter = build_painter_plan(d, image, .1, .5)
        strokes = build_stroke_plan(d, image, .1, .5)
        self.assertEqual(strokes.labels, painter.labels)         # Painter's parts
        first = lambda plan: [s.region for s in plan.segments if s.painting][:1]
        self.assertEqual(first(strokes), first(painter))         # in Painter's order

    def test_pencil_first_then_colour(self):
        import adaptive_hand
        from adaptive_hand import apply_pencil, plan_for, pencil_passes, qimage
        d = HandDrawingTests.drawing(self)
        image = qimage(hatched())
        d.paint_method = 'painter'
        apply_pencil(d, 'strokes')
        plan = plan_for(d, image, .1, .5)
        self.assertIsNotNone(plan.pencil)
        self.assertAlmostEqual(plan.split / plan.total, .5, places=3)
        self.assertEqual(pencil_passes(plan, .49 * .98)[1], 0.)        # colour waits for the pencil
        self.assertAlmostEqual(pencil_passes(plan, .5 * .98)[0], .98, places=3)
        ends = [s.end for s in plan.segments]
        self.assertEqual(ends, sorted(ends))                           # one continuous route
        for a, b in zip(plan.segments, plan.segments[1:]):
            self.assertLess(math.dist(a.b, b.a), 1e-6)                 # the hand never jumps
        from image_painting import paint_frame
        from adaptive_hand import pil_image
        mid = pil_image(paint_frame(d, image, 200, 140, .3, 1, .1, .5, None, .2, (.1, .1), False))
        px = np.asarray(mid.convert('RGBA')).reshape(-1, 4)
        drawn = px[px[:, 3] > 200]
        self.assertGreater(len(drawn), 50)
        self.assertLess(float(np.abs(drawn[:, 0].astype(int) - drawn[:, 2].astype(int)).mean()), 6)   # gray
        apply_pencil(d, '')
        self.assertIsNone(getattr(plan_for(d, image, .1, .5), 'pencil', None))

    def test_pencil_first_is_an_element_setting(self):
        from app import Window
        w = Window(); self.addCleanup(w.close)
        self.assertEqual(w.pencil_first.currentText(), 'Off')
        self.assertEqual(w.options()['pencil_first'], '')
        w.pencil_first.setCurrentText('Hand drawing — real strokes and lines')
        self.assertEqual(w.options()['pencil_first'], 'strokes')
        self.assertEqual(w.settings_state()['pencil_first'], 'Hand drawing — real strokes and lines')
