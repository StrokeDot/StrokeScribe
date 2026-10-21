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
        self.assertTrue(widget.isEnabled(), "Control was disabled: " + name)
        self.assertGreaterEqual(widget.width(), 84, "Control had no usable width: " + name)
        self.assertGreaterEqual(widget.height(), 20, "Control collapsed vertically: " + name)
        self.assertTrue(widget.currentText(), "Current value is invisible: " + name)

    def test_source_and_inspector_controls_have_real_geometry(self):
        w = self.w
        w.source_type.setCurrentIndex(1)
        APP.processEvents()
        for name in ("source_type", "image_animation_style", "image_style",
                     "image_detail", "font_select"):
            self._assert_control(name)
        for name in ("blend_mode", "reveal_mode", "pen_ease",
                     "entrance", "erase_mode", "camera"):
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
                         "blend_mode", "reveal_mode", "pen_ease"):
                self._assert_control(name)

    def test_all_mounted_source_and_inspector_dropdowns_have_usable_geometry(self):
        w = self.w
        w.source_type.setCurrentIndex(1)
        APP.processEvents()
        source = w.workspace_splitter.widget(0).findChildren(QComboBox)
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

    def test_values_persist_with_existing_project_settings(self):
        w = self.w
        w.blend_mode.setCurrentText("Multiply")
        w.reveal_mode.setCurrentText("Adaptive Hand Painting")
        w.pen_ease.setCurrentText("Natural (ease in and out)")
        w.image_style.setCurrentText("Detailed (all lines)")
        w.image_detail.setCurrentText("Max")
        state = w.settings_state()
        self.assertEqual(state["blend_mode"], "Multiply")
        self.assertEqual(state["reveal_mode"], w.reveal_mode.currentIndex())
        self.assertEqual(state["pen_ease"], "Natural (ease in and out)")
        self.assertEqual(state["image_style"], "Detailed (all lines)")
        self.assertEqual(state["image_detail"], "Max")

    def test_popup_items_are_clickable_and_change_value(self):
        w = self.w
        w.source_type.setCurrentIndex(1)
        for name in ("image_animation_style", "image_style", "image_detail",
                     "blend_mode", "reveal_mode", "pen_ease"):
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
