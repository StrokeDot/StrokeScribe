"""exp.18: Opacity / Blend don't render the element again; switched-off sections are greyed out."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QSlider

APP = QApplication.instance() or QApplication([])


class Switches(unittest.TestCase):
    def test_a_switched_off_section_is_greyed_out(self):
        from ui_sections import Section
        box = QCheckBox(); box.setChecked(False)
        sec = Section('Shadow', switch=box)
        slider = QSlider(); sec.body.addWidget(slider)
        self.assertFalse(sec.content.isEnabled())
        self.assertFalse(slider.isEnabled())
        box.setChecked(True)
        self.assertTrue(slider.isEnabled())
        later = QCheckBox(); later.setChecked(True)
        other = Section('Hand'); other.attach_switch(later)
        self.assertTrue(other.content.isEnabled())
        later.setChecked(False)
        self.assertFalse(other.content.isEnabled())

    def test_the_window_sections_follow_their_switch(self):
        from app import Window
        w = Window()
        try:
            for sec in (w.section_text_shadow, w.section_draw_hand, w.section_ink):
                src = sec._switch_source
                src.setChecked(False); self.assertFalse(sec.content.isEnabled(), sec.text())
                src.setChecked(True); self.assertTrue(sec.content.isEnabled(), sec.text())
        finally:
            w.close()


class OpacityIsCheap(unittest.TestCase):
    def test_opacity_changes_mix_the_kept_layers(self):
        from app import Window
        from engine import import_svg
        import frame_render
        w = Window(); w.resize(1400, 900); w.show(); APP.processEvents()
        try:
            w.set_drawing(import_svg('samples/drawing.svg')); APP.processEvents()
            w.slider.setValue(600); APP.processEvents()
            w.artwork_opacity.setValue(80); w.refresh(); APP.processEvents()
            calls = []
            real = frame_render._compose_raw_frame_now
            frame_render._compose_raw_frame_now = lambda *a, **k: calls.append(1) or real(*a, **k)
            try:
                for v in (70, 60, 50):
                    w.artwork_opacity.setValue(v); w.refresh(); APP.processEvents()
                self.assertEqual(calls, [])                         # nothing rendered again
                w.thickness.setValue(w.thickness.value() + .5); w.refresh(); APP.processEvents()
                self.assertGreater(len(calls), 0)                   # a real change renders
            finally:
                frame_render._compose_raw_frame_now = real
        finally:
            w.close()

    def test_icons_are_made_once(self):
        import ui_icons
        self.assertIs(ui_icons.pixmap('hand', '#ffffff', 18), ui_icons.pixmap('hand', '#ffffff', 18))


if __name__ == '__main__':
    unittest.main()
