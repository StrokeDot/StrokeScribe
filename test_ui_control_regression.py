"""Qt regression for invisible (zero-width) controls reported after experimental.70.

These assertions test ACTUAL rendered widget geometry and popup interaction,
not merely whether QComboBoxes exist and retain values in the project model.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QPushButton
from PySide6.QtTest import QTest

from app import Window

APP = QApplication.instance() or QApplication([])


class VisibleControlRegression(unittest.TestCase):
    def setUp(self):
        self.w = Window()
        self.w.resize(1490, 890)
        self.w.show()
        APP.processEvents()
        APP.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close()
        APP.processEvents()

    def _ensure_visible(self, combo):
        # Source, Animation, Hand, Sound and Export share the right panel and
        # show one page at a time (experimental.76): open the control's page.
        # Both side panels show one page at a time (Text/Sound/Music/Camera on
        # the left since experimental.78): open whichever holds the control.
        for tabs in (self.w.inspector_tabs, self.w.left_tabs):
            for i in range(tabs.count()):
                if tabs.widget(i).isAncestorOf(combo):
                    if tabs.currentIndex() != i:
                        tabs.setCurrentIndex(i)
                        APP.processEvents()
                    break
        from ui_sections import reveal
        reveal(combo)                      # open the panel section that holds it (exp.96)
        APP.processEvents()
        parent = combo.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent:
            parent.ensureWidgetVisible(combo)
            APP.processEvents()

    def _assert_control(self, name):
        widget = getattr(self.w, name)
        self._ensure_visible(widget)
        APP.processEvents()
        data = (name, widget.width(), widget.height(), widget.isVisible(),
                widget.isEnabled(), widget.currentText())
        print("VISIBLE_CONTROL_GEOMETRY %s width=%s height=%s visible=%s enabled=%s value=%r"
              % data, flush=True)
        self.assertTrue(widget.isVisible(), "Control was hidden: " + name)
        if not widget.toolTip().startswith('Not used now'):     # greyed out on purpose, with a reason
            self.assertTrue(widget.isEnabled(), "Control was disabled: " + name)
        self.assertGreaterEqual(widget.width(), 84, "Control had no usable width: " + name)
        self.assertGreaterEqual(widget.height(), 20, "Control collapsed vertically: " + name)
        self.assertTrue(widget.currentText(), "Current value is invisible: " + name)

    def test_source_and_inspector_controls_have_real_geometry(self):
        w = self.w
        w.source_type.setCurrentIndex(1)
        APP.processEvents()
        for name in ("image_animation_style", "image_style",
                     "image_detail", "font_select"):
            self._assert_control(name)
        for name in ("reveal_mode", "pen_ease",
                     "entrance", "camera"):
            self._assert_control(name)

    def test_combos_remain_measurable_at_multiple_desktop_sizes(self):
        w = self.w
        w.source_type.setCurrentIndex(1)
        for width, height in ((1040, 768), (1490, 890),
                              (1920, 1080), (2560, 1440)):
            w.resize(width, height)
            APP.processEvents()
            APP.processEvents()
            for name in ("image_animation_style", "image_style", "image_detail",
                         "reveal_mode", "pen_ease"):
                self._assert_control(name)

    def test_all_mounted_source_and_inspector_dropdowns_have_usable_geometry(self):
        w = self.w
        w.source_type.setCurrentIndex(1)
        APP.processEvents()
        from studio_workspace import TABS
        source = (w.workspace_splitter.widget(0).findChildren(QComboBox) +
                  w.inspector_tabs.widget(TABS['source']).findChildren(QComboBox))
        self.assertGreaterEqual(len(source), 5)
        for combo in source:
            if not combo.isVisible():
                continue  # hidden source mode and optional legacy fields
            self._ensure_visible(combo)
            self.assertGreaterEqual(combo.width(), 84, "Source dropdown collapsed")
            self.assertGreaterEqual(combo.height(), 20, "Source dropdown lost height")
        for tab in range(w.inspector_tabs.count()):
            w.inspector_tabs.setCurrentIndex(tab)
            APP.processEvents()
            area = w.inspector_tabs.widget(tab)
            boxes = area.widget().findChildren(QComboBox)
            for combo in boxes:
                if not combo.isVisible():
                    continue  # conditionally hidden field intentionally
                area.ensureWidgetVisible(combo)
                APP.processEvents()
                self.assertGreaterEqual(combo.width(), 84,
                                        "Inspector tab %s dropdown collapsed" % tab)
                self.assertGreaterEqual(combo.height(), 20,
                                        "Inspector tab %s dropdown lost height" % tab)


    def test_hand_sliders_keep_editable_values_and_commit_drags_once(self):
        w = self.w
        pairs = (
            ("hand_size_pct", "draw_hand_size_slider", 40, 40),
            ("paint_hand_size", "paint_hand_size_slider", 55, 55),
            ("move_hand_size", "move_hand_size_slider", 45, 45),
            ("eraser_hand_size", "eraser_hand_size_slider", 60, 60),
            ("ax", "pen_tip_x_slider", .385, 77),
            ("ay", "pen_tip_y_slider", .615, 123),
            ("move_hand_gx", "move_hand_gx_slider", .385, 77),
            ("move_hand_gy", "move_hand_gy_slider", .615, 123),
        )
        for spin_name, slider_name, value, ticks in pairs:
            spin = getattr(w, spin_name)
            slider = getattr(w, slider_name)
            self.assertFalse(slider.hasTracking(), slider_name)
            spin.setValue(value)
            self.assertEqual(slider.value(), ticks, slider_name)
            self.assertGreaterEqual(spin.width(), 98, spin_name)
            self.assertEqual(spin.property('compact'), True, spin_name)
        w.hand_size_pct.setValue(42)
        self.assertAlmostEqual(w.handsize.value(), .42, places=2)
        w.pen_tip_x_slider.setValue(100)
        self.assertAlmostEqual(w.ax.value(), .5, places=3)

    def test_compact_numeric_fields_fit_full_text_and_arrow_reserve(self):
        from studio_workspace import compact_width
        w = self.w
        for name in ('ink_edge_size','ink_removal','ink_strength',
                     'hand_size_pct','ax','ay','move_hand_size','move_hand_gx',
                     'move_hand_gy','eraser_hand_size'):
            spin = getattr(w, name)
            self.assertGreaterEqual(spin.width(), compact_width(spin),
                                    'Clipped numeric field: ' + name)

    def test_values_persist_with_existing_project_settings(self):
        w = self.w
        w.blend_mode.setCurrentText("Multiply")
        w.reveal_mode.setCurrentText("Adaptive Hand Painting")
        w.pen_ease.setCurrentText("Natural (ease in and out)")
        w.image_style.setCurrentText("Detailed (all lines)")
        w.image_detail.setCurrentText("Max")
        state = w.settings_state()
        # The sample is an imported SVG: blend mode shows in Source → Appearance
        # (the Element Editor edits the same field).
        self.assertFalse(w.blend_mode.isHidden())
        self.assertEqual(state["blend_mode"], "Multiply")
        self.assertEqual(state["reveal_mode"], "Adaptive Hand Painting")
        self.assertEqual(state["pen_ease"], "Natural (ease in and out)")
        self.assertEqual(state["image_style"], "Detailed (all lines)")
        self.assertEqual(state["image_detail"], "Max")

    def test_popup_items_are_clickable_and_change_value(self):
        w = self.w
        w.source_type.setCurrentIndex(1)
        # Paint mode opens its own picker window instead (test_paint_mode_picker).
        for name in ("image_animation_style", "image_style", "image_detail",
                     "pen_ease"):
            combo = getattr(w, name)
            self._assert_control(name)
            old = combo.currentIndex()
            candidate = next((i for i in range(combo.count())
                              if i != old and combo.model().flags(combo.model().index(i, 0))
                              & Qt.ItemFlag.ItemIsEnabled), None)
            self.assertIsNotNone(candidate, "No selectable menu options: "+name)
            combo.showPopup()
            APP.processEvents()
            view = combo.view()
            self.assertTrue(view.isVisible(), "Dropdown popup failed to appear: "+name)
            # A real mouse action selects from the visible popup instead of a
            # direct setCurrentIndex that bypasses hit testing and signals.
            view.scrollTo(view.model().index(candidate, 0))
            APP.processEvents()
            rect = view.visualRect(view.model().index(candidate, 0))
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, rect.center())
            APP.processEvents()
            self.assertEqual(combo.currentIndex(), candidate,
                             "Popup selection did not change current value: "+name)
            combo.hidePopup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
