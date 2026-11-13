"""Erase temporary SVG guide ink using the same spatial brush coverage as color.

SVG traces and colored PNG edges rarely align perfectly. Erasing guides only
where nontransparent color pixels have appeared leaves stray SVG outlines
behind until the final frame. Nearest opaque-source support extends the real
brush coverage to these temporary guides, without painting extra color pixels.
The PNG is always composited afterward, preserving its genuine dark outlines.
"""
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image
from PySide6.QtGui import QImage, QPainter

from adaptive_hand import pil_image, qimage


_SUPPORT_CACHE = OrderedDict()

# How far painted coverage reaches to retire nearby SVG guide ink, as a
# fraction of the artwork's longest side. About 2.5 adaptive grid cells.
GUIDE_REACH = .012

# exp.172/173 (the user: the painting looked finished but lines stayed until the very end): ink
# where the picture is empty (nothing will ever be painted there) goes as the picture AROUND it
# gets painted: when this share of the picture within EMPTY_REACH (share of the artwork's
# width) is painted, it starts to fade, and it is gone at the second share. It does not wait
# for the last small touches nearby.
EMPTY_REACH = .2
EMPTY_DONE = (.45, .75)
# Whatever is still left then fades out over this stretch of the painting (share of the
# route), so no line is left near the end.
EMPTY_FADE = (.7, .88)


def grown_coverage(alpha, rect):
    """Dilate a canvas-sized coverage alpha by GUIDE_REACH of the artwork."""
    reach = max(2, int(round(max(rect.width(), rect.height()) * GUIDE_REACH)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (2 * reach + 1, 2 * reach + 1))
    return cv2.dilate(np.ascontiguousarray(alpha), kernel)


def _nearest_source_support(image):
    """Map each source-grid cell to its nearest visible PNG pixel (cached)."""
    key = (image.cacheKey(), image.width(), image.height())
    if key in _SUPPORT_CACHE:
        _SUPPORT_CACHE.move_to_end(key)
        return _SUPPORT_CACHE[key]

    source = pil_image(image)
    scale = min(1., 360. / max(source.width, source.height))
    gw = max(1, round(source.width * scale))
    gh = max(1, round(source.height * scale))
    alpha = np.asarray(source.getchannel('A').resize(
        (gw, gh), Image.Resampling.BOX), dtype=np.uint8)
    support = alpha >= 8
    if not support.any():
        support = alpha > 0
    if not support.any():
        raise ValueError('The matching PNG contains no visible pixels.')

    missing = (~support).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(
        missing, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    nearest = (gw, gh, support, labels)
    _SUPPORT_CACHE[key] = nearest
    if len(_SUPPORT_CACHE) > 3:
        _SUPPORT_CACHE.popitem(last=False)
    return nearest


def empty_fade(progress):
    """0..255: how much of the guide ink in empty areas has faded out at this progress."""
    if progress is None:
        return 0
    a, b = EMPTY_FADE
    return int(round(255 * max(0., min(1., (float(progress) - a) / (b - a)))))


def svg_guide_erase_mask(coverage, image, rect, progress=None):
    """An erase mask driven by brush coverage, including misaligned SVG ink.

    For pixels over real source art, erasure follows the precise reveal mask.
    For transparent gaps and outside the PNG bounds, the nearest visible
    source pixel supplies its brush-coverage amount. No fade clock, cleanup
    pass, or SVG stroke deletion is involved.
    """
    width, height = coverage.width(), coverage.height()
    gw, gh, support, labels = _nearest_source_support(image)
    canvas = coverage.convertToFormat(QImage.Format.Format_RGBA8888)
    alpha = np.frombuffer(bytes(canvas.constBits()), dtype=np.uint8).reshape(
        height, width, 4)[:, :, 3]

    # Grow the *actual current paint mask* by a small reach before using it.
    # The adaptive planner reveals on a coarse grid, so the outermost source
    # cells often read as unpainted even when the paint beside them is done.
    # Ink that the SVG trace places a few pixels outside the PNG edge then
    # survives as dark specks until the final frame. Growing the coverage
    # retires that ink together with its painted neighbourhood.
    alpha = grown_coverage(alpha, rect)
    xs = np.clip(np.floor(rect.left() + (np.arange(gw) + .5) *
                          rect.width() / gw).astype(np.int32), 0, width - 1)
    ys = np.clip(np.floor(rect.top() + (np.arange(gh) + .5) *
                          rect.height() / gh).astype(np.int32), 0, height - 1)
    brush = alpha[np.ix_(ys, xs)]
    lookup = np.zeros(int(labels.max()) + 1, dtype=np.uint8)
    lookup[labels[support]] = brush[support]
    source_coverage = lookup[labels]
    reach = max(1, int(round(gw * EMPTY_REACH)))
    box = (2 * reach + 1, 2 * reach + 1)
    painted = cv2.boxFilter(np.where(support, brush, 0).astype(np.float32) / 255., -1, box,
                            normalize=False, borderType=cv2.BORDER_CONSTANT)
    around = cv2.boxFilter(support.astype(np.float32), -1, box, normalize=False,
                           borderType=cv2.BORDER_CONSTANT)
    done = np.where(around > 0, painted / np.maximum(around, 1e-6), 0.)
    a, b = EMPTY_DONE
    local = np.clip((done - a) / (b - a), 0., 1.) * 255
    empty = np.maximum(np.maximum(source_coverage, local), empty_fade(progress)).astype(np.uint8)
    source_coverage = np.where(support, source_coverage, empty)

    out_x = np.clip(np.floor((np.arange(width) + .5 - rect.left()) *
                             gw / max(.001, rect.width())).astype(np.int32),
                    0, gw - 1)
    out_y = np.clip(np.floor((np.arange(height) + .5 - rect.top()) *
                             gh / max(.001, rect.height())).astype(np.int32),
                    0, gh - 1)
    amount = np.maximum(source_coverage[np.ix_(out_y, out_x)], alpha)
    mask = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    mask.putalpha(Image.fromarray(amount, 'L'))
    return qimage(mask)


def remove_svg_guides(outline, coverage, original, rect, progress=None):
    """Change only the temporary stroke layer, never the original PNG layer."""
    erase = svg_guide_erase_mask(coverage, original, rect, progress)
    painter = QPainter(outline)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawImage(0, 0, erase)
    painter.end()
    return outline
