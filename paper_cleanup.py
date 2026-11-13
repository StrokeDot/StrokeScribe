"""Non-destructive, opt-in removal of paper touching an image's OUTER border.

A near-white hole enclosed by drawn lines stays intact. The source image is
never mutated: its alpha-adjusted copy is only used for display/export.
This cannot always distinguish faint intentional border details from paper;
tolerance/softness are deliberately adjustable and default to OFF.
"""
from __future__ import annotations
from collections import OrderedDict

import cv2
import numpy as np

_CACHE = OrderedDict()
_CACHE_LIMIT = 4


def clean_paper(image, tolerance=22, softness=8):
    """Return a new QImage with connected near-white paper faded to alpha."""
    from PIL import Image
    from adaptive_hand import pil_image, qimage

    if image is None or image.isNull():
        return image
    tolerance = max(0, min(80, int(tolerance)))
    softness = max(0, min(50, int(softness)))
    key = (image.cacheKey(), image.width(), image.height(), tolerance, softness)
    result = _CACHE.get(key)
    if result is not None:
        _CACHE.move_to_end(key)
        return result
    pixels = np.array(pil_image(image), dtype=np.uint8)
    rgb = pixels[:, :, :3].astype(np.int16)
    # The worst RGB-channel departure rejects tinted details and colored lines.
    departure = np.max(255 - rgb, axis=2)
    neutral = np.max(rgb, axis=2) - np.min(rgb, axis=2) <= 30
    candidate = (departure <= tolerance) & neutral & (pixels[:, :, 3] > 0)
    count, labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=8)
    border_labels = np.unique(np.concatenate((
        labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    outside = np.zeros(count, dtype=bool)
    outside[border_labels] = True
    outside[0] = False
    paper = candidate & outside[labels]
    if paper.any():
        if softness == 0:
            pixels[:, :, 3][paper] = 0
        else:
            # Pixels nearest white are removed; darker antialiased transitions
            # fade gradually back to fully opaque along the ink boundary.
            start = max(0, tolerance - softness)
            coverage = np.clip((departure.astype(np.float32) - start) /
                               max(1, softness), 0., 1.)
            pixels[:, :, 3][paper] = np.rint(
                pixels[:, :, 3][paper] * coverage[paper]).astype(np.uint8)
    cleaned = qimage(Image.fromarray(pixels, mode='RGBA'))
    _CACHE[key] = cleaned
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return cleaned
