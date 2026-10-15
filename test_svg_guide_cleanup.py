"""Regression tests: SVG guide ink must retire with painting, not at the end."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from adaptive_hand import qimage
from color_reveal import artwork_rect, render_color_timeline
from engine import Drawing, Stroke, render
from image_painting import original_frame
from stroke_guided import project
from svg_guide_cleanup import remove_svg_guides, svg_guide_erase_mask

APP = QApplication.instance() or QApplication([])


def pixels(image):
    data = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(bytes(data.constBits()), dtype=np.uint8).reshape(
        data.height(), data.width(), 4)


def svg_fixture():
    png = Image.new('RGBA', (90, 70))
    pen = ImageDraw.Draw(png)
    pen.rectangle((20, 18, 70, 52), fill=(219, 183, 103, 255))
    pen.line((26, 39, 42, 39), fill=(13, 20, 25, 255), width=4)
    drawing = Drawing([
        Stroke('headset top guide', [(10., 30.), (80., 30.)], '#172A3F', 2.),
        Stroke('headset lower guide', [(10., 46.), (80., 46.)], '#172A3F', 2.)
    ], (0., 0., 90., 70.), [])
    drawing.source_kind = 'svg'
    return drawing, qimage(png)


def coverage_mask(drawing, image, full=False):
    width, height = 320, 240
    rect = artwork_rect(drawing, image, width, height)
    mask = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    p = QPainter(mask)
    fraction = 1. if full else .52
    p.fillRect(QRectF(rect.left(), rect.top(), rect.width() * fraction,
                      rect.height()), Qt.GlobalColor.white)
    p.end()
    return mask


class SVGGuideCoverageTests(unittest.TestCase):
    def check_left_guide_removed_right_guide_waits(self, frame, drawing, image):
        original = pixels(original_frame(drawing, image, 320, 240))
        before = pixels(render(drawing, 1., 320, 240))
        result = pixels(frame)
        left = tuple(round(v) for v in project(drawing, 320, 240, (10., 30.)))
        right = tuple(round(v) for v in project(drawing, 320, 240, (80., 30.)))
        for point in (left, right):
            x, y = point
            self.assertEqual(int(original[y, x, 3]), 0,
                             'SVG mismatch intentionally falls outside PNG alpha')
            self.assertGreater(int(before[y, x, 3]), 0)
        self.assertEqual(int(result[left[1], left[0], 3]), 0,
                         'Left-side temporary guide must retire during brush coverage')
        self.assertGreater(int(result[right[1], right[0], 3]), 0,
                           'Unpainted right-side guide must stay visible')
        # Source PNG black detail is real art, not temporary guide ink.
        black = tuple(round(v) for v in project(drawing, 320, 240, (32., 39.)))
        x, y = black
        np.testing.assert_array_equal(result[y, x], original[y, x])
        self.assertLess(int(result[y, x, 0]), 40)

    def test_misaligned_svg_guide_uses_nearest_painted_source_support(self):
        d, image = svg_fixture()
        mask = coverage_mask(d, image)
        outline = render(d, 1., 320, 240)
        cleaned = remove_svg_guides(outline, mask, image,
                                    artwork_rect(d, image, 320, 240))
        before = render(d, 1., 320, 240)
        left = tuple(round(v) for v in project(d, 320, 240, (10., 30.)))
        right = tuple(round(v) for v in project(d, 320, 240, (80., 30.)))
        a, b = pixels(cleaned), pixels(before)
        self.assertEqual(int(a[left[1], left[0], 3]), 0)
        self.assertGreater(int(a[right[1], right[0], 3]), 0)
        self.assertGreater(int(b[left[1], left[0], 3]), 0)

    def test_all_svg_paint_modes_retire_guides_while_painting(self):
        d, image = svg_fixture()
        half = coverage_mask(d, image)
        full = coverage_mask(d, image, full=True)
        cases = {
            'brush': 'color_reveal.paint_mask',
            'continue': 'color_reveal.paint_mask',
            'guided': 'stroke_guided.guided_paint_mask',
            'clean': 'clean_paint.clean_paint_mask',
            'adaptive': 'adaptive_hand.adaptive_paint_mask',
        }
        for mode, mocked in cases.items():
            with self.subTest(mode=mode):
                for mask, is_full in ((half, False), (full, True)):
                    with patch(mocked, return_value=(mask, None)):
                        result = render_color_timeline(
                            d, .75, width=320, height=240,
                            duration=1., fade_duration=1., hold_duration=0.,
                            final_image=image, reveal_mode=mode)
                    if is_full:
                        np.testing.assert_array_equal(
                            pixels(result),
                            pixels(original_frame(d, image, 320, 240)),
                            'Once painting covers the PNG, SVG guides must all be gone')
                    else:
                        self.check_left_guide_removed_right_guide_waits(
                            result, d, image)

    def test_empty_mask_does_not_erase_svg_guides(self):
        d, image = svg_fixture()
        mask = QImage(320, 240, QImage.Format.Format_ARGB32_Premultiplied)
        mask.fill(Qt.GlobalColor.transparent)
        cleared = remove_svg_guides(render(d, 1., 320, 240), mask, image,
                                    artwork_rect(d, image, 320, 240))
        np.testing.assert_array_equal(
            pixels(cleared), pixels(render(d, 1., 320, 240)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
