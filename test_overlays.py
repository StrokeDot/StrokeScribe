"""exp.51: overlays — pictures and titles on their own timeline tracks, at the
same time as the drawing, with entrance and exit effects."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

import overlays

HERE = Path(__file__).parent


class TimingTests(unittest.TestCase):
    def test_effects(self):
        it = overlays.new_text('Hello')
        it.update(start=1., duration=3., effect_in='Pop', in_seconds=.5, effect_out='Fade', out_seconds=.4)
        self.assertIsNone(overlays.state_at(it, .9))
        self.assertIsNone(overlays.state_at(it, 4.1))
        self.assertEqual(overlays.state_at(it, 2.), (1., 0., 0., 1., 0.))
        sizes = [overlays.state_at(it, 1 + k * .05)[3] for k in range(11)]
        self.assertAlmostEqual(sizes[0], 0., places=3)
        self.assertGreater(max(sizes), 1.05)                     # the bounce
        self.assertAlmostEqual(sizes[-1], 1., places=3)
        self.assertLess(overlays.state_at(it, 3.9)[0], .5)       # fading out
        it['effect_in'] = 'Slide from left'
        self.assertLess(overlays.state_at(it, 1.)[1], -1.)       # starts outside, on the left
        it['effect_in'] = 'Spin'
        self.assertLess(overlays.state_at(it, 1.1)[4], -50)      # turning
        it['effect_in'] = 'None'
        self.assertEqual(overlays.state_at(it, 1.)[0], 1.)
        self.assertEqual(overlays.end_of(it), 4.)


def picture_file(folder):
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (300, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((20, 20, 280, 180), fill=(230, 80, 40, 255))
    path = Path(folder) / 'sun.png'; im.save(path)
    return path


def alpha_in(image, box):
    import numpy as np
    from PySide6.QtGui import QImage
    im = image.convertToFormat(QImage.Format.Format_RGBA8888)
    a = np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.bytesPerLine())[:, 3::4][:, :im.width()]
    x, y, w, h = [int(round(v)) for v in box]
    return (a[max(0, y):y + h, max(0, x):x + w] > 30).mean()


@unittest.skipIf(SKIP, 'needs Qt')
class PaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_text_and_picture_drawn_at_their_time(self):
        from PySide6.QtGui import QImage
        with tempfile.TemporaryDirectory() as tmp:
            pic = overlays.image_item_from_file(picture_file(tmp), start=0., duration=2.)
            pic.update(x=.3, y=.5, size=.3, effect_in='None')
            title = overlays.new_text('Hello', start=1., duration=2.)
            title['effect_in'] = 'None'
            frame = QImage(640, 360, QImage.Format.Format_ARGB32_Premultiplied); frame.fill(0)
            overlays.paint(frame, [pic, title], .5)
            self.assertGreater(alpha_in(frame, overlays.box(pic, 640, 360)), .5)
            self.assertLess(alpha_in(frame, overlays.box(title, 640, 360)), .01)    # not yet
            frame.fill(0); overlays.paint(frame, [pic, title], 1.5)
            self.assertGreater(alpha_in(frame, overlays.box(title, 640, 360)), .05)
            # SVG overlays are drawn at the size they appear (sharp).
            svg = overlays.new_image('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                                     '<circle cx="5" cy="5" r="4" fill="blue"/></svg>', 'svg', 'dot')
            big = overlays.picture(svg, 600)
            self.assertGreaterEqual(big.width(), 600)

    def test_in_the_animation_frame(self):
        from engine import import_svg
        from frame_render import compose_frame
        d = import_svg(HERE / 'samples' / 'drawing.svg')
        title = overlays.new_text('Hello', start=0., duration=10.)
        title.update(effect_in='None', x=.5, y=.12)
        o = dict(width=640, height=360, duration=2., fade_duration=.4, hold_duration=.5, final_image=None,
                 thickness=1., hand=None, hand_scale=.2, anchor=(.1, .1), reveal_mode='adaptive',
                 brush_width=.14, painting_hand=None, stroke_spacing=.55, artwork_scale=1., overlays=[title])
        frame = compose_frame(d, .5, o)
        self.assertGreater(alpha_in(frame, overlays.box(title, 640, 360)), .05)
        hand_only = compose_frame(d, .5, dict(o, layers='hand'))
        self.assertLess(alpha_in(hand_only, overlays.box(title, 640, 360)), .01)   # hand-only export: no overlays


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        from app import Window
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); self.app.processEvents()
        self.w.duration.setValue(4.)

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()
        self.tmp.cleanup()

    def test_add_move_resize_undo_save(self):
        w = self.w
        w.slider.setValue(250)                                    # at 1 s
        item = w.add_overlay_picture(str(picture_file(self.dir)))
        self.assertIsNotNone(item)
        self.assertAlmostEqual(item['start'], 1., places=1)
        self.assertEqual(len(w.stage_timeline.overlays), 1)
        self.assertTrue(w.add_picture_overlay.isVisible())
        # On the preview after its entrance: drag it, then the mouse wheel.
        w.slider.setValue(500); self.app.processEvents()
        W, H = w.canvas.frame.width(), w.canvas.frame.height()
        x, y, bw, bh = overlays.box(item, W, H)
        self.assertIs(w.overlay_at(x + bw / 2, y + bh / 2), item)
        self.assertIsNotNone(w.compute_overlay_box())
        self.assertTrue(w.drag_picture('start', x + bw / 2, y + bh / 2))
        w.drag_picture('move', .1, -.05); w.drag_picture('done', 0, 0)
        self.assertAlmostEqual(item['x'], .6, places=2)
        self.assertEqual(w.picture_x.value(), 0.)                 # the drawing did not move
        size = item['size']
        x, y, bw, bh = overlays.box(item, W, H)
        self.assertTrue(w.preview_wheel(2, x + bw / 2, y + bh / 2))
        self.assertGreater(item['size'], size)
        # Clip on the timeline: move it and make it longer.
        w.move_overlay_clip(item['id'], 2., 1.5, 1)
        self.assertEqual((item['start'], item['duration'], item['track']), (2., 1.5, 1))
        tl = w.stage_timeline
        self.assertEqual(tl.tracks(), 2)
        self.assertGreater(tl._overlay_rect(tl.overlays[0]).top(), tl._lane(0).top())
        self.assertGreater(tl._rows()[2].top(), tl._lane(1).bottom())          # audio lane below the tracks
        # A title, duplicate, delete and undo.
        w.overlay_action(item['id'], 'duplicate')
        self.assertEqual(len(w.overlays), 2)
        w.overlay_action(item['id'], 'delete')
        self.assertEqual(len(w.overlays), 1)
        w.undo()
        self.assertEqual(len(w.overlays), 2)
        # Saved in the project and in other scenes' previews.
        import projects
        saved = projects.save(self.dir / 'overlay', w.project_state())
        from app import Window
        other = Window(); self.addCleanup(other.close)
        self.assertTrue(other.open_project(str(saved)))
        self.assertEqual(len(other.overlays), 2)
        from scenes import job_from_state
        _, options, _ = job_from_state(projects.load(saved), w.hand)
        self.assertEqual(len(options['overlays']), 2)

    def test_title_shows_in_the_preview(self):
        w = self.w
        from PySide6.QtWidgets import QDialog
        from overlay_dialog import OverlayDialog
        original = OverlayDialog.exec
        OverlayDialog.exec = lambda self: QDialog.DialogCode.Accepted       # no window in the test
        try:
            w.slider.setValue(0)
            item = w.add_overlay_text()
        finally:
            OverlayDialog.exec = original
        self.assertEqual(item['kind'], 'text')
        item['effect_in'] = 'None'
        w.refresh()
        w.slider.setValue(400); self.app.processEvents()
        W, H = w.canvas.frame.width(), w.canvas.frame.height()
        self.assertGreater(alpha_in(w.canvas.frame, overlays.box(item, W, H)), .03)
        # The settings window changes it live.
        d = OverlayDialog(w, item, w.scene_seconds(), changed=lambda it: w.refresh())
        d.text.setPlainText('New title'); d.effect_in.setCurrentText('Zoom')
        self.assertEqual(item['text'], 'New title'); self.assertEqual(item['effect_in'], 'Zoom')
        d.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
