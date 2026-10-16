"""Erase stage: an eraser rubs the finished picture away at the end.

Two styles, both planned on the finished frame itself (so they work for SVG
drawings, coloured images and lettering alike):

  zigzag  The eraser finds where the picture is (its visible pixels) and
          scrubs back and forth over it along one logical route, the same
          planner as Zigzag sweep painting.
  lines   The eraser follows the drawn lines backwards (last line first), with
          a wide rubber; whatever is left fades out at the very end.

The plan works on a small grid; the erased area is scaled up smoothly, so the
edge of the rubbed area is soft like a real eraser.
"""
from __future__ import annotations

import bisect
import math
from pathlib import Path

import numpy as np

MODES = {'Off': None, 'Zigzag (follows the shapes)': 'zigzag', 'Along the lines': 'lines'}
DEFAULT_ERASER = Path(__file__).resolve().parent / 'assets' / 'default_eraser.png'
ERASER_TIP = (.19, .81)            # rubbing edge of the built-in eraser image
GRID = 256
FINISH = .96                       # route done at 96% of the erase time


class ErasePlan:
    def __init__(self, size, grid, segments, arrival, total, fade_from=None):
        self.size = size                 # output (w, h)
        self.grid = grid                 # (gw, gh)
        self.segments = segments         # (a, b, radius, painting, start, end) in grid cells
        self.ends = [s[5] for s in segments]
        self.arrival = arrival           # clock time each cell is erased (inf: never)
        self.total = max(1e-6, total)
        self.fade_from = fade_from       # progress where leftovers start fading (lines)

    def clock(self, progress):
        return max(0., min(1., progress)) / FINISH * self.total

    def state(self, progress):
        """(point in output pixels or None, rubbing: bool)."""
        if not self.segments or progress <= 0 or progress >= FINISH:
            return None, False
        t = self.clock(progress)
        i = min(len(self.segments) - 1, bisect.bisect_left(self.ends, t))
        a, b, _, painting, start, end = self.segments[i]
        f = 0. if end <= start else max(0., min(1., (t - start) / (end - start)))
        x = a[0] + (b[0] - a[0]) * f
        y = a[1] + (b[1] - a[1]) * f
        gw, gh = self.grid
        w, h = self.size
        return (x * w / gw, y * h / gh), painting

    def erased(self, progress):
        """Erased amount per grid cell, 0..1."""
        if progress <= 0:
            return np.zeros(self.arrival.shape, np.float32)
        if progress >= 1:
            return np.ones(self.arrival.shape, np.float32)
        amount = (self.arrival <= self.clock(progress)).astype(np.float32)
        if self.fade_from is not None and progress > self.fade_from:
            amount = np.maximum(amount, min(1., (progress - self.fade_from) / (FINISH - self.fade_from)))
        elif self.fade_from is None and progress >= FINISH:
            amount[:] = 1.
        return amount


def _grid_for(width, height):
    scale = GRID / max(width, height)
    return max(8, round(width * scale)), max(8, round(height * scale))


def _support(frame, grid):
    """Grid cells where the finished frame has visible pixels."""
    import cv2
    from adaptive_hand import pil_image
    alpha = np.asarray(pil_image(frame).getchannel('A'), np.uint8)
    # Max-pool so thin lines are not lost when shrinking.
    gw, gh = grid
    ky = max(1, alpha.shape[0] // gh); kx = max(1, alpha.shape[1] // gw)
    pooled = cv2.dilate(alpha, np.ones((ky, kx), np.uint8))
    small = cv2.resize(pooled, (gw, gh), interpolation=cv2.INTER_AREA)
    return small > 12


def plan_zigzag(frame, size_fraction=.08):
    from zigzag_paint import plan_cells
    grid = _grid_for(frame.width(), frame.height())
    support = _support(frame, grid)
    if not support.any():
        return ErasePlan((frame.width(), frame.height()), grid, [], np.full(support.shape, np.inf), 1.)
    _, raw, arrival, total, _ = plan_cells(support, np.zeros_like(support), (0., 0.),
                                            brush_width=size_fraction, spacing=.5)
    segments = [(a, b, r, painting, s, e) for a, b, r, _rid, painting, s, e in raw]
    return ErasePlan((frame.width(), frame.height()), grid, segments, arrival, total)


def plan_lines(frame, strokes_px, size_fraction=.08):
    """strokes_px: drawn strokes in output pixels, in drawing order."""
    grid = _grid_for(frame.width(), frame.height())
    gw, gh = grid
    w, h = frame.width(), frame.height()
    sx, sy = gw / w, gh / h
    support = _support(frame, grid)
    radius = max(1., gw * size_fraction / 2)
    arrival = np.full((gh, gw), np.inf)
    segments = []
    clock = 0.
    cursor = None
    yy, xx = np.mgrid[0:gh, 0:gw]

    def stamp(p, when):
        x0, x1 = int(max(0, p[0] - radius)), int(min(gw, p[0] + radius + 1))
        y0, y1 = int(max(0, p[1] - radius)), int(min(gh, p[1] + radius + 1))
        if x0 >= x1 or y0 >= y1:
            return
        disk = (xx[y0:y1, x0:x1] + .5 - p[0]) ** 2 + (yy[y0:y1, x0:x1] + .5 - p[1]) ** 2 <= radius * radius
        block = arrival[y0:y1, x0:x1]
        block[disk] = np.minimum(block[disk], when)

    def move(p, rubbing):
        nonlocal clock, cursor
        if cursor is None:
            cursor = p
        d = math.dist(cursor, p)
        duration = max(.05, d) if rubbing else max(.3, min(8., d * .15))
        if rubbing:
            steps = max(1, math.ceil(d / .5))
            for j in range(steps + 1):
                f = j / steps
                stamp((cursor[0] + (p[0] - cursor[0]) * f, cursor[1] + (p[1] - cursor[1]) * f),
                      clock + duration * f)
        segments.append((cursor, p, radius, rubbing, clock, clock + duration))
        clock += duration
        cursor = p

    for stroke in reversed(strokes_px):
        pts = [(x * sx, y * sy) for x, y in reversed(stroke)]
        if len(pts) < 2:
            continue
        # Fewer, evenly spaced points (the eraser does not need every pixel).
        kept = [pts[0]]
        for p in pts[1:]:
            if math.dist(kept[-1], p) >= .8:
                kept.append(p)
        move(kept[0], False)
        for p in kept[1:]:
            move(p, True)
    if not segments:
        return ErasePlan((w, h), grid, [], np.full((gh, gw), np.inf), 1., fade_from=0.)
    covered = np.isfinite(arrival[support]).mean() if support.any() else 1.
    # Leftovers (areas far from any line) fade during the last part.
    fade_from = .82 if covered < .999 else None
    return ErasePlan((w, h), grid, segments, arrival, clock, fade_from)


def erase_frame(frame, plan, progress):
    """The finished frame with the erased part removed (soft edge)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    amount = plan.erased(progress)
    if not amount.any():
        return frame
    gw, gh = plan.grid
    alpha = np.ascontiguousarray((amount * 255).astype(np.uint8))
    mask = QImage(alpha.data, gw, gh, gw, QImage.Format.Format_Alpha8).copy()
    mask = mask.scaled(frame.width(), frame.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    out = frame.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawImage(0, 0, mask)
    painter.end()
    return out


def draw_eraser(frame, point, eraser, anchor, width_fraction):
    """The eraser (or eraser hand) with its rubbing point at `point`."""
    if point is None or eraser is None or eraser.isNull():
        return frame
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    w = frame.width() * width_fraction
    h = w * eraser.height() / eraser.width()
    painter = QPainter(frame)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF(point[0] - anchor[0] * w, point[1] - anchor[1] * h, w, h), eraser)
    painter.end()
    return frame
