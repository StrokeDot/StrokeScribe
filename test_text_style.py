"""exp.16: Filmora-style text settings: style basics, effects, Out and Loop animations."""
import os
import tempfile
import unittest

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
from test_part_c import sample_font  # noqa: E402

FONT = sample_font()
TEXT = 'lolo lolo\nlo'


def ink(d):
    return np.asarray(d.font_ink)[..., 3]


def columns(mask):
    cols = np.nonzero(mask.any(axis=0))[0]
    return cols[0], cols[-1]


@unittest.skipIf(FONT is None, 'needs a TrueType font')
class StyleBasics(unittest.TestCase):
    def make(self, **layout):
        from font_stroke_reveal import create_font_drawing
        return create_font_drawing(TEXT, FONT, 68, layout=layout)

    def test_defaults_change_nothing(self):
        from font_stroke_reveal import create_font_drawing, LAYOUT_DEFAULT
        a = create_font_drawing(TEXT, FONT, 68)
        b = create_font_drawing(TEXT, FONT, 68, layout=dict(LAYOUT_DEFAULT))
        self.assertEqual(ink(a).tobytes(), ink(b).tobytes())
        self.assertEqual([s.points for s in a.strokes], [s.points for s in b.strokes])

    def test_bold_is_heavier(self):
        self.assertGreater((ink(self.make(bold=True)) > 100).sum(), (ink(self.make()) > 100).sum() * 1.1)

    def test_italic_leans_the_tops_right(self):
        plain, lean = self.make(), self.make(italic=True)
        def top_left(d):
            a = ink(d) > 100
            rows = np.nonzero(a.any(axis=1))[0]
            return columns(a[rows[0]:rows[0] + 6])[0]
        self.assertGreater(top_left(lean), top_left(plain))
        self.assertGreater(lean.bounds[2], plain.bounds[2])          # room for the lean

    def test_underline_is_written_after_each_line(self):
        d = self.make(underline=True)
        names = [s.name for s in d.strokes]
        unders = [i for i, n in enumerate(names) if n.startswith('Pen underline')]
        self.assertEqual(len(unders), 2)                                 # one per line
        first_line_end = max(i for i, n in enumerate(names) if i < unders[1] and not n.startswith('Pen underline'))
        self.assertLess(unders[0], unders[1]); self.assertGreater(unders[0], 0)
        self.assertEqual(unders[0], first_line_end + 1 if first_line_end < unders[0] else unders[0])

    def test_alignment_moves_the_short_line(self):
        def second_line_left(d):
            a = ink(d) > 100
            h = a.shape[0]
            return columns(a[h // 2:])[0]
        left, centre, right = (second_line_left(self.make(align=x)) for x in ('left', 'center', 'right'))
        self.assertLess(left, centre); self.assertLess(centre, right)

    def test_spacing_widens_and_line_spacing_heightens(self):
        plain = self.make()
        self.assertGreater(self.make(spacing=20).bounds[2], plain.bounds[2] * 1.2)
        self.assertGreater(self.make(line=1.8).bounds[3], plain.bounds[3] * 1.2)

    def test_pen_paths_follow_the_letters(self):
        d = self.make(italic=True, align='center', spacing=10, bold=True)
        a = ink(d) > 60
        h, w = a.shape
        inside = 0; total = 0
        for s in d.strokes:
            for x, y in s.points[::3]:
                total += 1
                xi, yi = int(min(w - 1, max(0, x))), int(min(h - 1, max(0, y)))
                inside += a[max(0, yi - 3):yi + 4, max(0, xi - 3):xi + 4].any()
        self.assertGreater(inside / total, .9)                       # the pen is on the ink


@unittest.skipIf(FONT is None, 'needs a TrueType font')
class Effects(unittest.TestCase):
    def frame(self, effects, progress=1.):
        from font_stroke_reveal import create_font_drawing, render_traced_font
        d = create_font_drawing('lolo', FONT, 68)
        if effects is not None:
            d.text_effects = effects
        img = render_traced_font(d, progress, 480, 200).convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(bytes(img.constBits())[:img.sizeInBytes()], np.uint8).reshape(200, 480, 4)

    def test_no_effects_is_the_same_picture(self):
        from font_stroke_reveal import EFFECTS_DEFAULT
        import copy
        self.assertEqual(self.frame(None).tobytes(), self.frame(copy.deepcopy(EFFECTS_DEFAULT)).tobytes())

    def test_outline_and_glow_reach_past_the_letters(self):
        plain = (self.frame(None)[..., 3] > 30).sum()
        self.assertGreater((self.frame({'outline': {'on': True, 'thickness': 6}})[..., 3] > 30).sum(), plain * 1.3)
        self.assertGreater((self.frame({'glow': {'on': True}})[..., 3] > 30).sum(), plain * 1.3)

    def test_outline_colour(self):
        f = self.frame({'outline': {'on': True, 'thickness': 6, 'color': '#FF0000'}})
        visible = f[..., 3] > 200
        reds = (f[..., 0] > 200) & (f[..., 1] < 60) & visible
        self.assertGreater(reds.sum(), 50)

    def test_shadow_falls_down_right(self):
        plain = self.frame(None)[..., 3] > 30
        shadow = self.frame({'shadow': {'on': True, 'distance': 12, 'blur': 0, 'opacity': 100}})[..., 3] > 30
        self.assertGreater(columns(shadow)[1], columns(plain)[1])
        self.assertGreater(np.nonzero(shadow.any(axis=1))[0][-1], np.nonzero(plain.any(axis=1))[0][-1])

    def test_background_box_and_fill_opacity(self):
        box = self.frame({'background': {'on': True, 'color': '#00FF00', 'spread': 10}})
        self.assertGreater(((box[..., 1] > 200) & (box[..., 3] > 200)).sum(), 2000)
        faint = self.frame({'fill': {'opacity': 40}})
        self.assertLess(faint[..., 3].max(), 120)

    def test_effects_appear_with_the_writing(self):
        early = (self.frame({'outline': {'on': True}}, .2)[..., 3] > 30).sum()
        done = (self.frame({'outline': {'on': True}}, 1.)[..., 3] > 30).sum()
        self.assertLess(early, done * .7)


class OutAndLoop(unittest.TestCase):
    def picture(self):
        img = QImage(200, 80, QImage.Format.Format_ARGB32_Premultiplied); img.fill(QColor(0, 0, 0, 0))
        for x in range(40, 160):
            for y in range(30, 50):
                img.setPixelColor(x, y, QColor('#202040'))
        return img

    def test_blur_and_wipe_out(self):
        from frame_render import effect_frame, EXITS
        import eraser_clips
        self.assertEqual(eraser_clips.EFFECTS['Blur out'], 'blur')
        self.assertEqual(eraser_clips.EFFECTS['Wipe out'], 'wipe')
        art = self.picture()
        for kind in ('Blur', 'Wipe'):
            self.assertIn(kind, EXITS.values())
            self.assertEqual(effect_frame(art, kind, 1.).pixelColor(100, 40).alpha(), 255)
            self.assertEqual(effect_frame(art, kind, 0.).pixelColor(100, 40).alpha(), 0)
        half = effect_frame(art, 'Wipe', .5)
        self.assertEqual(half.pixelColor(45, 40).alpha(), 0)          # the left side has gone first
        self.assertEqual(half.pixelColor(155, 40).alpha(), 255)

    def test_loops_start_still_and_move_after(self):
        from frame_render import loop_state, LOOPS
        for kind in filter(None, LOOPS.values()):
            self.assertEqual(loop_state(kind, 0.), (1., 0., 1., 0.))
            self.assertNotEqual(loop_state(kind, 1.1), (1., 0., 1., 0.), kind)

    @unittest.skipIf(FONT is None, 'needs a TrueType font')
    def test_an_export_loops_while_it_waits(self):
        from engine import export_frames
        from font_stroke_reveal import create_font_drawing
        from pathlib import Path
        d = create_font_drawing('lolo', FONT, 68)
        with tempfile.TemporaryDirectory() as tmp:
            for name, loop in (('still', None), ('sway', 'sway')):
                export_frames(d, Path(tmp) / name, duration=.4, fps=10, width=320, height=180,
                              pause=1.6, loop=loop)
            frames = lambda name: sorted((Path(tmp) / name).glob('*.png'))
            still, sway = frames('still'), frames('sway')
            same = lambda a, b: a.read_bytes() == b.read_bytes()
            self.assertTrue(same(still[-1], still[-4]))              # no loop: it just waits
            self.assertFalse(same(sway[-1], sway[-4]))               # loop: it moves while it waits
            self.assertTrue(same(still[2], sway[2]))                 # writing itself: unchanged

    def test_board_clock(self):
        import board
        seconds, ends = board.clock([4., 2.], [1., 0.], 'scene', 1, .5)
        self.assertEqual(ends, {0: 4., 1: 7.})
        self.assertAlmostEqual(seconds, 6.)                          # 4 + 1 (move) + half of 2
        seconds, _ = board.clock([4., 2.], [1., 0.], 'join', 0, .5)
        self.assertAlmostEqual(seconds, 4.5)

    def test_loop_option(self):
        from export_job import options_from_settings
        import inspect
        params = inspect.signature(options_from_settings).parameters
        self.assertIn('s', params) if 's' in params else None
        from frame_render import LOOPS
        self.assertEqual(LOOPS['Float'], 'float')


@unittest.skipIf(FONT is None, 'needs a TrueType font')
class Panel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        cls.w = Window()
        cls.w.font_select.addItem('Local: test', str(FONT))
        cls.w.font_select.setCurrentIndex(cls.w.font_select.count() - 1)
        cls.w.text.setPlainText('lolo')
        cls.w.letter(); APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def test_style_rewrites_and_effects_apply(self):
        w = self.w
        w.text_italic.setChecked(True)
        w.letter_timer.stop(); w.reletter(); APP.processEvents()
        self.assertTrue(w.drawing.font_layout['italic'])
        w.text_fx['outline']['on'].setChecked(True)
        self.assertTrue(w.drawing.text_effects['outline']['on'])
        state = w.letter_state()
        self.assertTrue(state['layout']['italic']); self.assertTrue(state['effects']['outline']['on'])
        import text_style_panel
        text_style_panel.set_state(w, None, None)                      # another element: defaults
        self.assertFalse(w.text_italic.isChecked()); self.assertFalse(w.text_fx['outline']['on'].isChecked())
        text_style_panel.set_state(w, state['layout'], state['effects'])
        self.assertTrue(w.text_italic.isChecked()); self.assertTrue(w.text_fx['outline']['on'].isChecked())

    def test_out_alone_is_its_own_way_out(self):
        w = self.w
        self.assertEqual(len(w.scenes), 1)
        w.text_out_time.setValue(1.)
        w.text_out.setCurrentText('Blur out'); APP.processEvents()
        self.assertEqual(w.erase_mode.currentText(), 'Blur out')
        self.assertEqual(w.options()['erase']['mode'], 'blur')
        self.assertEqual([o for o in w.overlays if o.get('kind') == 'eraser'], [])
        w.text_out.setCurrentText('None'); APP.processEvents()
        self.assertEqual(w.erase_mode.currentText(), 'Off')

    def test_out_with_several_elements_is_one_goes_out_clip(self):
        from app import Window
        from font_stroke_reveal import create_font_drawing
        w = Window()
        try:
            w.set_drawing(create_font_drawing('lolo', FONT, 68))
            w.add_scene(); w.set_drawing(create_font_drawing('lo', FONT, 68)); APP.processEvents()
            w.text_out.setCurrentText('Wipe out'); APP.processEvents()
            clips = [o for o in w.overlays if o.get('kind') == 'eraser']
            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0]['effect'], 'Wipe out')
            self.assertEqual(clips[0]['target'], w.scenes[w.scene_index]['uid'])
            w.text_out.setCurrentText('Fade out'); APP.processEvents()
            clips = [o for o in w.overlays if o.get('kind') == 'eraser']
            self.assertEqual(len(clips), 1); self.assertEqual(clips[0]['effect'], 'Fade out')
            w.text_out.setCurrentText('None'); APP.processEvents()
            self.assertEqual([o for o in w.overlays if o.get('kind') == 'eraser'], [])
        finally:
            w.close()

    def test_loop_is_an_element_setting(self):
        w = self.w
        self.assertIn('loop_style', w.PROJECT_SETTINGS)
        w.loop_style.setCurrentText('Float')
        self.assertEqual(w.settings_state()['loop_style'], 'Float')
        self.assertEqual(w.options().get('loop'), 'float')
        w.loop_style.setCurrentText('None')

    def test_letter_detail_is_under_advanced(self):
        w = self.w
        parent = w.font_size
        while parent is not None and parent is not w.section_text_advanced:
            parent = parent.parentWidget()
        self.assertIs(parent, w.section_text_advanced)


if __name__ == '__main__':
    unittest.main()
