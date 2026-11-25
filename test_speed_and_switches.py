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


class SwitchesFollowQuietChanges(unittest.TestCase):
    def test_a_quiet_switch_change_is_followed(self):
        # exp.20: projects, undo and element switches set switches with their signals blocked
        from ui_sections import Section, sync_all
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        root = QWidget(); lay = QVBoxLayout(root)
        box = QCheckBox(); box.setChecked(False)
        sec = Section('Ink', switch=box); lay.addWidget(sec)
        box.blockSignals(True); box.setChecked(True); box.blockSignals(False)
        sync_all(root)
        self.assertTrue(sec.content.isEnabled())

    def test_greyed_out_controls_look_grey(self):
        import theme
        css = theme.stylesheet('dark', __import__('pathlib').Path('assets'))
        for rule in ('QLabel:disabled', 'QSlider::handle:horizontal:disabled', 'QSpinBox:disabled'):
            self.assertIn(rule, css)


class ExportDefaults(unittest.TestCase):
    def test_a_new_project_exports_2k_60fps_webm_18(self):
        from app import Window
        w = Window()
        try:
            self.assertEqual(w.res.currentText(), '2560 × 1440')
            self.assertEqual(w.fps.value(), 60)
            self.assertTrue(w.webm.isChecked())
            self.assertEqual(w.webm_quality.value(), 18)
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
            real = frame_render._compose_raw_frame
            frame_render._compose_raw_frame = lambda *a, **k: calls.append(1) or real(*a, **k)
            try:
                for v in (70, 60, 50):
                    w.artwork_opacity.setValue(v); w.refresh(); APP.processEvents()
                self.assertEqual(calls, [])                         # nothing rendered again
                w.thickness.setValue(w.thickness.value() + .5); w.refresh(); APP.processEvents()
                self.assertGreater(len(calls), 0)                   # a real change renders
            finally:
                frame_render._compose_raw_frame = real
        finally:
            w.close()

    def test_the_hand_still_goes_back_to_its_corner(self):
        # exp.19 (the user: the hand froze on its way back): the kept layers must not reuse one
        # frame for the whole way back
        from app import Window
        from engine import import_svg
        import frame_render
        w = Window(); w.resize(1400, 900); w.show(); APP.processEvents()
        try:
            w.set_drawing(import_svg('samples/drawing.svg')); APP.processEvents()
            w.hand_rest.setChecked(True); w.refresh(); APP.processEvents()
            d, opts, _, cam = w.preview_scene(0, 640, 360)

            def walk(token):
                frame_render.set_layer_token(token)
                seen = []
                for f in (.70, .75, .80, .85, .90, .95):
                    frame_render._set_spec(None)
                    frame_render.compose_frame(d, f, dict(opts, layers='hand'), cam)
                    s = frame_render.last_hand_spec()
                    seen.append(None if not s else (s.get('phase'), round(s.get('p') or 0, 3),
                                                    tuple(round(v) for v in s.get('tip', (0, 0)))))
                return seen
            plain = walk(None)
            kept = walk(('token', 1))
            frame_render.set_layer_token(None)
            self.assertEqual(kept, plain)
            self.assertEqual(len({x for x in plain if x}), len([x for x in plain if x]))   # it moves
        finally:
            w.close()

    def test_icons_are_made_once(self):
        import ui_icons
        self.assertIs(ui_icons.pixmap('hand', '#ffffff', 18), ui_icons.pixmap('hand', '#ffffff', 18))


if __name__ == '__main__':
    unittest.main()
