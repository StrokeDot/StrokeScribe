"""Camera follow: a gentle zoom that follows the hand, then shows the whole picture.

The camera path is planned once for the whole animation from the pen track
(motion.py): positions are smoothed over about half a second in both
directions, so the camera glides ahead of quick jumps instead of jerking. It
zooms in as the pen starts and zooms back out to the full frame once the
drawing and painting are done. The frame is rendered larger and cropped, so
zoomed frames stay sharp.
"""
from __future__ import annotations

import math

import numpy as np

ZOOMS = {'off': 1.0, 'gentle': 1.3, 'close': 1.65}
RATE = 30.
SMOOTH_SECONDS = .55
ZOOM_IN_SECONDS = .9
ZOOM_OUT_SECONDS = 1.1


def _smoothstep(x):
    x = np.clip(x, 0., 1.)
    return x * x * (3 - 2 * x)


class CameraPath:
    """Camera (zoom, centre x, centre y) for a timeline fraction 0..1.

    Centres are fractions of the frame (0..1), so one path serves the preview
    and every export resolution.
    """

    def __init__(self, times, zoom, cx, cy, total):
        self.times, self.zoom, self.cx, self.cy, self.total = times, zoom, cx, cy, total

    def at(self, fraction):
        t = max(0., min(1., float(fraction))) * self.total
        z = float(np.interp(t, self.times, self.zoom))
        x = float(np.interp(t, self.times, self.cx))
        y = float(np.interp(t, self.times, self.cy))
        return z, x, y


def plan(samples, total, width, height, zoom):
    """CameraPath from motion.track() samples [(time, PenSample)], or None if off."""
    if zoom <= 1.0001 or not samples or total <= 0:
        return None
    times = np.array([t for t, _ in samples], np.float64)
    points = [s.point for _, s in samples]
    active = np.array([p is not None for p in points])
    if not active.any():
        return None
    xs = np.full(len(points), np.nan); ys = np.full(len(points), np.nan)
    for i, p in enumerate(points):
        if p is not None:
            xs[i], ys[i] = p[0] / width, p[1] / height
    # Hold the last known position through gaps (and the first one before it).
    idx = np.where(active, np.arange(len(points)), -1)
    np.maximum.accumulate(idx, out=idx)
    first = int(np.argmax(active))
    idx[idx < 0] = first
    xs, ys = xs[idx], ys[idx]
    # Smooth in both directions (Gaussian over ~0.55 s).
    dt = times[1] - times[0] if len(times) > 1 else 1 / RATE
    sigma = max(1., SMOOTH_SECONDS / dt)
    radius = int(3 * sigma)
    kernel = np.exp(-.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    pad = lambda v: np.concatenate([np.full(radius, v[0]), v, np.full(radius, v[-1])])
    xs = np.convolve(pad(xs), kernel, 'valid')
    ys = np.convolve(pad(ys), kernel, 'valid')
    # Zoom in as the pen starts; out to the full picture after it stops.
    start, end = times[first], times[len(active) - 1 - int(np.argmax(active[::-1]))]
    # Always finish on the whole picture, even when the pen works to the very end.
    end = max(start, min(end, total - ZOOM_OUT_SECONDS * .66))
    rise = _smoothstep((times - start + ZOOM_IN_SECONDS * .25) / ZOOM_IN_SECONDS)
    fall = 1 - _smoothstep((times - end + ZOOM_OUT_SECONDS * .35) / ZOOM_OUT_SECONDS)
    amount = np.minimum(rise, fall)
    z = 1 + (zoom - 1) * amount
    # Ease the centre to the middle as the zoom relaxes, and keep the view
    # inside the frame.
    xs = .5 + (xs - .5) * amount
    ys = .5 + (ys - .5) * amount
    half_w, half_h = .5 / z, .5 / z
    xs = np.clip(xs, half_w, 1 - half_w)
    ys = np.clip(ys, half_h, 1 - half_h)
    return CameraPath(times, z, xs, ys, total)


def crop(frame, width, height, zoom, cx, cy):
    """Cut the camera view (output size) out of a frame rendered at zoom x size."""
    if zoom <= 1.0001:
        return frame
    from PySide6.QtCore import QRect
    left = int(round(cx * frame.width() - width / 2))
    top = int(round(cy * frame.height() - height / 2))
    left = max(0, min(frame.width() - width, left))
    top = max(0, min(frame.height() - height, top))
    return frame.copy(QRect(left, top, width, height))


def render_size(width, height, zoom):
    return max(width, int(math.ceil(width * zoom))), max(height, int(math.ceil(height * zoom)))
