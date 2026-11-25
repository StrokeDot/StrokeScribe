"""Phase 0: characterization checks for the working experimental.58 renderers.

These tests intentionally don't modify product behavior. They pin observable
semantics shared by the headset/TV SVG + matching PNG workflow and both image
animation choices, before project-data safety changes are introduced.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PySide6.QtWidgets import QApplication

from test_svg_guide_cleanup import svg_fixture, pixels
from test_contour_transitions import fixture
from color_reveal import render_color_timeline
from image_painting import original_frame
from engine import render

APP = QApplication.instance() or QApplication([])


class StableRenderingContract(unittest.TestCase):
    def test_svg_guide_and_source_pixels_remain_distinct(self):
        drawing, source = svg_fixture()
        original = pixels(original_frame(drawing, source, 320, 240))
        trace = pixels(render(drawing, 1., 320, 240))
        self.assertGreater(int(trace[:, :, 3].sum()), 0)
        for mode in ("brush", "guided", "clean", "adaptive"):
            with self.subTest(mode=mode):
                finished = pixels(render_color_timeline(
                    drawing, 1., width=320, height=240, duration=1.,
                    fade_duration=1., hold_duration=0., final_image=source,
                    reveal_mode=mode))
                np.testing.assert_array_equal(finished, original)

    def test_image_modes_keep_blank_start_and_exact_source_finish(self):
        drawing, source = fixture()
        original = pixels(original_frame(drawing, source, 320, 240))
        for mode in ("draw_paint", "paint_only"):
            drawing.image_animation = mode
            with self.subTest(mode=mode):
                opts = dict(width=320, height=240, duration=1.,
                            fade_duration=1., hold_duration=0.,
                            final_image=source, reveal_mode="adaptive")
                start = pixels(render_color_timeline(drawing, 0., **opts))
                self.assertEqual(int(start[:, :, 3].max()), 0)
                final = pixels(render_color_timeline(drawing, 1., **opts))
                np.testing.assert_array_equal(final, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
