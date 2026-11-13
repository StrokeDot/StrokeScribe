"""Follow the page fold (1.0.1-experimental.4).

The user (a game screenshot of a sketch in an open journal): "you can see how the drawing is
perfectly embedded in the page... improve the technology for the embedded image".

A picture drawn across an open book used to lie flat over the fold, and the fold's line cut
straight through it, so it looked pasted on. Real pages curve down into the binding: what is
drawn near the fold bends away into it, and a pencil cannot reach into the gutter. Here the
fold is found in the picture underneath (the page: a narrow dark valley running down the middle
part of the element), and the element's picture bends into it and fades out in the gutter.
Nothing changes when no fold is found.
"""
from __future__ import annotations

import numpy as np

BEND = .007        # of the screen's width: how far the drawing next to the fold slides into it
REACH = .02        # of the width: how far from the fold the bending is felt
GUTTER = .008     # of the width: the gutter, where the pencil does not reach
MIN_DIP = .05      # the fold must be at least this much darker than the page around it


def _array(image):
    from PySide6.QtGui import QImage
    q = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    w, h = q.width(), q.height()
    a = np.frombuffer(q.constBits(), np.uint8, q.bytesPerLine() * h).reshape(h, q.bytesPerLine())
    return a[:, :w * 4].reshape(h, w, 4).copy()


def find_fold(under, x, y, w, h):
    """The fold's x (in `under`'s pixels) inside the rectangle, or None."""
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(under.width(), int(x + w)), min(under.height(), int(y + h))
    if x1 - x0 < 40 or y1 - y0 < 40:
        return None
    # exp.5 (lag): on a small copy of the page (the fold's place to within a pixel or two)
    from PySide6.QtCore import Qt
    part = under.copy(x0, y0, x1 - x0, y1 - y0)
    if y1 - y0 > 160:                      # fewer rows only: the fold is a narrow valley across
        part = part.scaled(x1 - x0, 160, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    a = _array(part).astype(np.float32)
    rows = slice(int(a.shape[0] * .15), int(a.shape[0] * .85))
    lum = (a[rows, :, 2] * .299 + a[rows, :, 1] * .587 + a[rows, :, 0] * .114)
    alpha = a[rows, :, 3]
    if float(alpha.mean()) < 128:                       # no page under it
        return None
    profile = np.median(lum, axis=0)
    kernel = np.ones(3) / 3
    profile = np.convolve(profile, kernel, mode='same')
    n = profile.size
    lo, hi = int(n * .3), int(n * .7)
    i = lo + int(np.argmin(profile[lo:hi]))
    side = max(6, n // 25)
    around = np.concatenate([profile[max(0, i - 3 * side):max(0, i - side)], profile[i + side:i + 3 * side]])
    if around.size < 4:
        return None
    level = float(np.median(around))
    if level <= 1 or (level - profile[i]) / level < MIN_DIP:
        return None
    return x0 + (i + .5) * (x1 - x0) / n


def follow_fold(image, fold_x, x, w, screen_width):
    """The element's picture (QImage, drawn at x..x+w) bent into the fold at fold_x and faded in
    its gutter (a new QImage). Sizes are shares of the screen's width (an element's own frame
    can be much bigger than the screen).

    exp.5 (the user: "now it's lagging a lot"): only the strip around the fold changes (further
    away the drawing moves by less than a third of a pixel), so only that strip is worked on, in
    8-bit (it was the whole frame, 4245 pixels wide, in floating point: a third of a second a
    frame)."""
    strip = fold_strip(image, fold_x, x, w, screen_width)
    from PySide6.QtGui import QImage, QPainter
    out = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if strip is not None:
        picture, c0 = strip
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(c0, 0, picture)
        p.end()
    return out


def fold_strip(image, fold_x, x, w, screen_width):
    """(the bent strip around the fold as a QImage, its first column in `image`), or None: the
    only part of the picture that changes, so the rest is drawn as it is (no copy of a big
    frame on every frame)."""
    import cv2
    from PySide6.QtGui import QImage
    ih, iw = image.height(), image.width()
    fx = (fold_x - x) / max(1e-6, w) * iw
    unit = float(screen_width) * iw / max(1e-6, w)       # the screen's width, in the picture's pixels
    bend, reach, gutter = BEND * unit, REACH * unit, GUTTER * unit
    span = reach * np.log(max(1.5, bend / .3)) + 2 + bend
    c0, c1 = max(0, int(fx - span)), min(iw, int(np.ceil(fx + span)))
    if c1 - c0 < 2:
        return None
    a = _array(image.copy(c0, 0, c1 - c0, ih))
    xx = np.arange(c0, c1, dtype=np.float32)
    dist = np.abs(xx - fx)
    shift = -np.sign(xx - fx) * bend * np.exp(-dist / reach)       # slides toward the fold
    mapx = np.tile((xx - shift - c0)[None, :], (ih, 1)).astype(np.float32)
    mapy = np.tile(np.arange(ih, dtype=np.float32)[:, None], (1, c1 - c0))
    bent = cv2.remap(a, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    t = np.clip((dist - gutter * .2) / max(1e-6, gutter), 0, 1)
    fade = (t * t * (3 - 2 * t)).astype(np.float32)
    bent = (bent.astype(np.float32) * fade[None, :, None] + .5).astype(np.uint8)   # premultiplied
    picture = QImage(np.ascontiguousarray(bent).data, c1 - c0, ih, (c1 - c0) * 4,
                     QImage.Format.Format_ARGB32_Premultiplied).copy()
    return picture, c0
