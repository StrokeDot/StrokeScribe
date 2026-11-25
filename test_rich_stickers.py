"""exp.52 (the user: stickers like Filmora's, with an ending that undoes them the way they
appeared, which I can turn off; their animation at 60 fps in the Stickers panel): the five new
stickers build in stages, the Ending plays the build backwards, and the panel's tiles animate."""
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def ink(item, amount=1., t=None, size=240):
    """How many pixels the sticker paints."""
    import stickers
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied); img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(QPointF(size / 2, size / 2))
    w = size * .8
    stickers.draw(p, item, w, w * float(item.get('aspect', .4)), 540, amount=amount, t=t)
    p.end()
    bits = img.constBits().tobytes()
    return sum(1 for i in range(3, len(bits), 4) if bits[i] > 40)


def shot(item, amount, size=240):
    import stickers
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied); img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(QPointF(size / 2, size / 2)); w = size * .8
    stickers.draw(p, item, w, w * float(item.get('aspect', .4)), 540, amount=amount)
    p.end()
    return img


class RichStickers(unittest.TestCase):
    def test_a_each_builds_in_stages(self):
        import stickers, sticker_art
        for shape in sticker_art.RICH:
            item = stickers.new(shape)
            self.assertIn(shape, stickers.SHAPES)
            counts = [ink(item, a) for a in (0., .3, .6, 1.)]
            self.assertEqual(counts[0], 0, shape)
            self.assertGreater(counts[1], 0, shape)
            if shape == 'Clock':                  # its disc is whole early; then rings, numerals, hands
                self.assertNotEqual(shot(item, .3), shot(item, 1.), shape)
            else:
                self.assertGreater(counts[3], counts[1], shape)           # more of it as it builds

    def test_b_the_ending_plays_the_build_backwards(self):
        import stickers
        item = stickers.new('Marker ellipse', start=0., duration=4.)
        self.assertEqual(item['ending'], 'Reverse of how it appeared')
        self.assertEqual(item['effect_out'], 'None')
        d = item['draw_seconds']
        full = ink(item, t=2.)
        half_way_out = ink(item, t=4. - d / 2)
        self.assertGreater(full, half_way_out)
        self.assertGreater(half_way_out, 0)
        self.assertEqual(ink(item, t=3.999), 0)                            # gone at the end
        # the same amount going out as coming in at the mirrored moment
        self.assertAlmostEqual(ink(item, t=.3), ink(item, t=4. - .3), delta=max(30, ink(item, t=.3) * .1))
        item['ending'] = 'None'
        self.assertEqual(ink(item, t=3.95), full)                          # no ending: it stays

    def test_c_old_shapes_can_have_the_ending_too(self):
        import stickers
        item = stickers.new('Arrow', start=0., duration=3.)
        self.assertEqual(item['ending'], 'None')                           # unchanged unless chosen
        item['ending'] = 'Reverse of how it appeared'
        self.assertLess(ink(item, t=3. - item['draw_seconds'] / 2), ink(item, t=1.5))

    def test_d_a_clocks_hands_turn(self):
        import stickers
        item = stickers.new('Clock', start=0., duration=10.)
        a = QImage(200, 200, QImage.Format.Format_ARGB32_Premultiplied)

        def shot(t):
            a.fill(QColor(0, 0, 0, 0))
            p = QPainter(a); p.translate(QPointF(100, 100)); stickers.draw(p, item, 180, 180, 540, t=t); p.end()
            return a.copy()
        self.assertNotEqual(shot(3.), shot(5.))

    def test_e_the_panel_tiles_play_at_60_fps(self):
        from app import Window
        w = Window(); w.show()
        try:
            for _ in range(10): APP.processEvents()
            w.inspector_tabs.setCurrentIndex(6)
            for _ in range(10): APP.processEvents()
            f0 = w.sticker_tile_frames; t0 = time.perf_counter()
            while time.perf_counter() - t0 < 1.:
                APP.processEvents()
            self.assertGreater(w.sticker_tile_frames - f0, 40)            # about 60 a second
            w.add_sticker('Magnifier')
            st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
            w.selected_overlay = st['id']; w.sync_sticker_panel()
            w.sticker_ending.setCurrentText('None')
            self.assertEqual(st['ending'], 'None')
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
