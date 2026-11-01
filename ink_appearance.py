"""Ink appearance (exp.178, the user: "it looks like paint ink appearing... a different way to
make the image appear, even without the pen"): an element's entrance where the picture soaks
into the paper like ink, no hand.

Every point of the picture gets a moment it appears: the ink starts at a few spots inside the
picture and spreads outwards, slowed and pushed by a fixed paper grain, so the edge is ragged
and organic. A point fades in over a short moment as the edge reaches it. The darkest parts
soak in a little sooner than the pale ones, like ink settling into the paper.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np

LIMIT = 960          # the spread is worked out at most this many pixels across
SEEDS = 5            # how many spots the ink starts from
GRAIN = .10          # how much the paper grain pushes the edge (share of the whole time)
FEATHER = .05        # a point fades in over this share of the time
DARK_FIRST = .12     # the darkest parts appear this share of the time sooner
_CACHE = OrderedDict()


def _grain(height, width, seed):
    import cv2
    rng = np.random.default_rng(seed)
    out = np.zeros((height, width), np.float32)
    for scale, weight in ((2, .4), (7, .35), (30, .25)):
        h, w = max(2, height // scale), max(2, width // scale)
        out += weight * cv2.resize(rng.random((h, w), dtype=np.float32), (width, height),
                                   interpolation=cv2.INTER_CUBIC)
    out -= out.mean()
    return out / max(1e-6, float(np.abs(out).max()))


def _field(image):
    """(moments 0..1, alpha) at the working size for this frame (cached)."""
    import cv2
    key = (image.cacheKey(), image.width(), image.height())
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    from PySide6.QtGui import QImage
    from PySide6.QtCore import Qt
    scale = min(1., LIMIT / max(1, image.width(), image.height()))
    width, height = max(2, round(image.width() * scale)), max(2, round(image.height() * scale))
    small = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGBA8888)
    rgba = np.frombuffer(bytes(small.constBits()), np.uint8).reshape(height, width, 4).astype(np.float32) / 255.
    alpha = rgba[..., 3]
    ink = alpha > .02
    if not ink.any():
        field = (np.zeros((height, width), np.float32), alpha)
    else:
        rng = np.random.default_rng(width * 31 + height)
        ys, xs = np.nonzero(ink)
        # Seeds spread over the picture: the first at its heaviest ink, the rest far apart.
        light = rgba[..., 0] * .299 + rgba[..., 1] * .587 + rgba[..., 2] * .114
        weight = (1. - light) * alpha
        seeds = [int(np.argmax(weight[ys, xs]))]
        sample = rng.choice(len(xs), size=min(len(xs), 4000), replace=False)
        for _ in range(SEEDS - 1):
            d = np.min([(xs[sample] - xs[s]) ** 2 + (ys[sample] - ys[s]) ** 2 for s in seeds], axis=0)
            seeds.append(int(sample[int(np.argmax(d))]))
        start = np.ones((height, width), np.uint8)
        for s in seeds:
            start[ys[s], xs[s]] = 0
        distance = cv2.distanceTransform(start, cv2.DIST_L2, 5).astype(np.float32)
        grain = _grain(height, width, width * 7 + height * 13)
        far = float(distance[ink].max()) or 1.
        moments = distance / far
        moments = moments + GRAIN * grain - DARK_FIRST * (weight - .5)
        lo, hi = float(moments[ink].min()), float(moments[ink].max())
        moments = (moments - lo) / max(1e-6, hi - lo)
        field = (moments.astype(np.float32), alpha)
    _CACHE[key] = field
    while len(_CACHE) > 8:
        _CACHE.popitem(last=False)
    return field


def frame(image, p):
    """`image` (a whole frame) soaking in like ink at progress p (0..1)."""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt, QRectF
    out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    if p <= 0:
        return out
    if p >= 1:
        return image.copy()
    moments, _ = _field(image)
    reach = p * (1. + FEATHER)
    amount = np.clip((reach - moments) / FEATHER, 0., 1.)
    mask = np.ascontiguousarray(np.rint(amount * 255).astype(np.uint8))
    h, w = mask.shape
    m = QImage(mask.data, w, h, w, QImage.Format.Format_Alpha8).copy()
    painter = QPainter(out)
    painter.drawImage(0, 0, image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF(0, 0, image.width(), image.height()), m)
    painter.end()
    return out
