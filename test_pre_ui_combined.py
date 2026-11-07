"""Combined pre-overhaul line/painting and per-element blend mode regression."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from app import Window

APP = QApplication.instance() or QApplication([])

class CombinedPreUIRegression(unittest.TestCase):
    def test_short_stroke_and_multiply_save_together(self):
        w = Window()
        try:
            self.assertFalse(w.lines_toggle.isChecked())
            self.assertEqual(w.blend_mode.currentText(), "Normal")
            mode = "Adaptive — Short up/down strokes"
            w.reveal_mode.setCurrentText(mode)
            w.blend_mode.setCurrentText("Multiply")
            self.assertEqual(w.options()["reveal_mode"], "short_zigzag")
            self.assertEqual(w.options()["blend_mode"], "Multiply")
            saved = w.project_state()
            w.reveal_mode.setCurrentText("Adaptive Hand Painting")
            w.blend_mode.setCurrentText("Normal")
            w.apply_project(saved)
            self.assertEqual(w.reveal_mode.currentText(), mode)
            self.assertEqual(w.blend_mode.currentText(), "Multiply")
        finally:
            w.close()

if __name__ == "__main__":
    unittest.main(verbosity=2)
