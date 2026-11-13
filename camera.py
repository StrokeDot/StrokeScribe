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


class ShiftedPath:
    """A camera path for a picture moved on the page (offset: fractions of the frame)."""

    def __init__(self, path, dx, dy):
        self.path, self.dx, self.dy = path, float(dx), float(dy)

    def at(self, fraction):
        z, x, y = self.path.at(fraction)
        return z, x + self.dx, y + self.dy


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


# ------------------------------------------------------------ element camera (exp.115)

ZOOM_MODE = 'Zoom (start → end)'


class ZoomPath:
    """The element's own camera: from a start framing to an end framing.

    start / end: (zoom, centre x, centre y) - zoom 1 = the whole element, centres are
    fractions of the element's frame. The camera holds the start framing until
    `begin` seconds, moves for `length` seconds (eased; zoom on a natural, logarithmic
    scale), then holds the end framing. `total` is the element's own time.

    The move can be longer than the element: what is left runs on into the camera
    move after the element, where the move gradually takes over (board.join_view).
    """

    def __init__(self, start, end, begin, length, total):
        self.start, self.end = tuple(map(float, start)), tuple(map(float, end))
        self.begin, self.length = max(0., float(begin)), max(.05, float(length))
        self.total = max(1e-6, float(total))

    def at_seconds(self, seconds):
        p = (float(seconds) - self.begin) / self.length
        e = float(_smoothstep(np.float64(p)))
        (z0, x0, y0), (z1, x1, y1) = self.start, self.end
        z = math.exp(math.log(max(1., z0)) + (math.log(max(1., z1)) - math.log(max(1., z0))) * e)
        return z, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e

    def at(self, fraction):
        return self.at_seconds(max(0., min(1., float(fraction))) * self.total)

    def runs_past_end(self):
        return self.begin + self.length > self.total + 1e-6


def zoom_path(plan, total):
    """ZoomPath from options['cam_plan'] = (start zoom %, x %, y %, end zoom %, x %, y %,
    begin s, length s), or None when it does nothing (both framings the whole element)."""
    if not plan:
        return None
    sz, sx, sy, ez, ex, ey, begin, length = (float(v) for v in plan)
    if sz <= 100.01 and ez <= 100.01:
        return None
    return ZoomPath((sz / 100., sx / 100., sy / 100.), (ez / 100., ex / 100., ey / 100.), begin, length, total)


def after_end(path, seconds_after):
    """Where an element's camera is `seconds_after` its end (it may still be zooming)."""
    if path is None:
        return None
    if hasattr(path, 'at_seconds'):
        return path.at_seconds(path.total + max(0., float(seconds_after)))
    return path.at(1.)
