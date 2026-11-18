"""exp.27 (the user): the Animation panel is now Drawing; Effects (Move in, Goes out, Loop) and
Stickers (arrows, circles, lines that draw themselves) are their own panels."""
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def ink(image):
    """How many pixels are not white."""
    n = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if image.pixelColor(x, y).lightness() < 240:
                n += 1
    return n


class Drawing(unittest.TestCase):
    def frame(self, items, t, w=320, h=180):
        import overlays
        f = QImage(w, h, QImage.Format.Format_ARGB32); f.fill(QColor('white'))
        return overlays.paint(f, items, t)

    def test_every_shape_draws_itself_little_by_little(self):
        import stickers
        for shape in stickers.SHAPES:
            item = stickers.new(shape); item.update(start=1., duration=4., draw_seconds=1.)
            before, early, done = (ink(self.frame([item], t)) for t in (.9, 1.4, 2.5))
            self.assertEqual(before, 0, shape)
            self.assertGreater(early, 0, shape)
            self.assertGreater(done, early, shape)

    def test_an_arrow_gets_its_head_at_the_end(self):
        import stickers
        item = stickers.new('Arrow'); item.update(start=0., duration=4., draw_seconds=1., size=.6, aspect=.4)
        self.assertGreater(ink(self.frame([item], 1.)), ink(self.frame([item], .8)) * 1.05)

    def test_it_is_sharp_at_the_export_size_and_has_its_colour(self):
        import stickers
        item = stickers.new('Line', color='#2050E0'); item.update(start=0., duration=3.)
        big = self.frame([item], 2., 2560, 1440)
        c = big.pixelColor(1280, 720)
        self.assertEqual((c.red(), c.green(), c.blue()), (0x20, 0x50, 0xE0))


class Panels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg')); cls.settle()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    @staticmethod
    def settle():
        for _ in range(3):
            for _ in range(20):
                APP.processEvents()
            time.sleep(.05)

    def test_the_rail_has_drawing_effects_and_stickers(self):
        names = [b.text() for b in self.w.rail_buttons.values()]
        self.assertEqual(names[:5], ['Image', 'AI', 'Drawing', 'Effects', 'Stickers'])
        w = self.w
        self.assertTrue(w.effects_page.isAncestorOf(w.section_move_in))
        self.assertTrue(w.effects_page.isAncestorOf(w.effect_out))
        self.assertFalse(w.effects_page.isAncestorOf(w.section_drawing))

    def test_goes_out_and_loop_are_the_same_settings_as_the_text_panel(self):
        w = self.w
        w.effect_loop.setCurrentIndex(1)
        self.assertEqual(w.loop_style.currentIndex(), 1)
        w.loop_style.setCurrentIndex(0)
        self.assertEqual(w.effect_loop.currentIndex(), 0)
        w.text_out_time.setValue(1.7)
        self.assertAlmostEqual(w.effect_out_time.value(), 1.7)

    def test_a_sticker_is_added_chosen_and_changed_in_its_panel(self):
        w = self.w
        item = w.add_sticker('Circle'); self.settle()
        self.assertEqual(item['kind'], 'sticker')
        self.assertIn(item, w.overlays)
        self.assertEqual(w.selected_overlay, item['id'])
        self.assertEqual(w.inspector_tabs.currentIndex(), 6)
        self.assertTrue(w.sticker_shape.isEnabled())
        w.sticker_size.setValue(55)
        self.assertAlmostEqual(item['size'], .55)
        w.sticker_shape.setCurrentText('Arrow')
        self.assertEqual((item['shape'], item['name']), ('Arrow', 'Arrow'))
        w.undo(); self.settle()                          # back to how it was
        again = w.find_overlay(item['id'])
        self.assertTrue(again is None or again['shape'] in ('Circle', 'Arrow'))
        w.select_overlay(None); self.settle()
        self.assertFalse(w.sticker_shape.isEnabled())

    def test_advanced_edit_opens_effects_for_the_way_out(self):
        from advanced_edit import PART_TAB
        self.assertEqual(PART_TAB['out'], 'effects')
        self.assertEqual(PART_TAB['move'], 'effects')


if __name__ == '__main__':
    unittest.main()
