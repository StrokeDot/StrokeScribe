"""Backgrounds for MP4 and the preview: plain colours and drawn textures.

Textures are generated (no image files): whiteboard, paper, chalkboard and
cork. They are made once per size and cached. Transparent exports (PNG, WebM,
MOV) never get a background.
"""
from __future__ import annotations

import numpy as np

COLORS = {'White': (255, 255, 255), 'Dark': (36, 45, 59), 'Black': (0, 0, 0)}
TEXTURES = ('Whiteboard', 'Paper', 'Chalkboard', 'Cork')
CHOICES = tuple(COLORS) + TEXTURES
_CACHE = {}


def _noise(h, w, scale, rng):
    """Smooth value noise in 0..1 at a given feature size (pixels)."""
    import cv2
    small = rng.random((max(2, int(h / scale) + 2), max(2, int(w / scale) + 2))).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def texture_rgb(name, width, height, seed=3):
    """(h, w, 3) uint8 background picture."""
    key = (name, width, height)
    if key in _CACHE:
        return _CACHE[key]
    if name in COLORS:
        out = np.empty((height, width, 3), np.uint8)
        out[:] = COLORS[name]
    else:
        rng = np.random.default_rng(seed)
        h, w = height, width
        grain = rng.standard_normal((h, w)).astype(np.float32)
        if name == 'Whiteboard':
            base = np.array([247, 248, 250], np.float32)
            light = _noise(h, w, max(w, h) / 3, rng) * 6 - 3          # soft sheen
            out = base + light[..., None] + grain[..., None] * 1.2
            # faint, wiped ghost streaks
            streak = _noise(h, w, 90, rng)
            out -= (np.clip(streak - .6, 0, None) * 5)[..., None]
        elif name == 'Paper':
            base = np.array([246, 240, 226], np.float32)
            fibre = _noise(h, w, 3, rng) * 10 - 5
            blotch = _noise(h, w, max(w, h) / 5, rng) * 12 - 6
            out = base + (fibre + blotch)[..., None] + grain[..., None] * 2.5
            # slightly darker edges (vignette)
            yy, xx = np.mgrid[0:h, 0:w]
            d = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2))
            out -= (np.clip(d - .75, 0, None) * 30)[..., None]
        elif name == 'Chalkboard':
            base = np.array([40, 62, 52], np.float32)
            smudge = _noise(h, w, max(w, h) / 6, rng) * 14 - 7
            dust = np.clip(_noise(h, w, 30, rng) - .55, 0, None) * 14
            out = base + (smudge + dust)[..., None] + grain[..., None] * 4
        else:  # Cork
            base = np.array([196, 150, 98], np.float32)
            granules = _noise(h, w, 2.5, rng)
            dark = (granules < .25) * -45 + (granules > .82) * 22
            tone = _noise(h, w, 40, rng) * 18 - 9
            out = base + (dark + tone)[..., None] + grain[..., None] * 6
        out = np.clip(out, 0, 255).astype(np.uint8)
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[key] = out
    return out


def texture_qimage(name, width, height):
    from PySide6.QtGui import QImage
    rgb = np.ascontiguousarray(texture_rgb(name, width, height))
    return QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()


def save_png(name, width, height, path):
    from PIL import Image
    Image.fromarray(texture_rgb(name, width, height)).save(path)
    return path
