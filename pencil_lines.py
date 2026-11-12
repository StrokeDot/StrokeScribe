"""Pencil lines: the paint edge drawn as lines that follow the picture's own strokes
(1.0.1-experimental).

The user (after 1.0.0), about the Arthur Morgan drawing: the painting should not feel like
pixels filling up; it should feel like the picture is being drawn.

Every reveal so far moved an edge across the picture: wherever the edge was, it cut through
the drawing's own pencil lines, so a half-done frame looked like a picture being uncovered,
not drawn. Here the edge is made of the picture's own lines:

* the direction of the marks everywhere in the picture is measured (the structure tensor of
  its shading; where the picture has no clear direction, as in flat colour or blank paper,
  the lines lean the way a right hand hatches);
* every pixel belongs to a thin line along that direction (a streak), and every line gets
  its own small difference in timing: some are drawn a little before the brush gets there,
  some a little after;
* a line is drawn from where the hand first touches it and grows along its direction, so it
  is never uncovered by a straight edge; it stays inside its part of the picture.

Behind the hand the area is completed line by line, as with hatching, and everything is
finished by the time the hand leaves the part, so nothing appears after the hand has gone.
The result is again a moment for every pixel (the same clock as the brush), so drawing a
frame is still a single comparison.
"""
from __future__ import annotations

import numpy as np

HATCH_ANGLE = -55.       # degrees (y down): where the picture has no direction, lines lean up-right
LEAD = 2.2               # brush radii: how far ahead of the brush a line may already be drawn
LAG = 1.6                # brush radii (of brush travel): how long a line may wait behind it
GROW = 4.                # a line grows this many times faster than the brush moves
FAINT = .03              # contrast (0..1) from which a mark's direction is followed fully
SEED = 20261112


def directions(gray, scale=1.):
    """(dx, dy) unit vectors: the direction of the picture's marks at every pixel."""
    import cv2
    g = cv2.GaussianBlur(gray, (0, 0), max(.6, 1. * scale))
    gx = cv2.Scharr(g, cv2.CV_32F, 1, 0)
    gy = cv2.Scharr(g, cv2.CV_32F, 0, 1)
    sigma = max(1.5, 3. * scale)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), sigma)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), sigma)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), sigma)
    # the gradient's doubled angle is (jxx - jyy, 2 jxy); the marks run across it
    c2, s2 = -(jxx - jyy), -2. * jxy
    strength = np.sqrt(c2 * c2 + s2 * s2)
    coherence = strength / np.maximum(jxx + jyy, 1e-6)
    # marks of a few percent of contrast count fully (faint shading has its own direction too;
    # Scharr gives 16 x the step of a sharp edge)
    texture = np.sqrt(jxx + jyy) / (16. * FAINT)
    weight = np.clip((coherence - .12) / .3, 0, 1) * np.clip(texture, 0, 1)
    a0 = np.radians(2. * HATCH_ANGLE)
    c = weight * c2 / np.maximum(strength, 1e-9) + (1. - weight) * np.cos(a0)
    s = weight * s2 / np.maximum(strength, 1e-9) + (1. - weight) * np.sin(a0)
    smooth = max(2., 5. * scale)
    c = cv2.GaussianBlur(c.astype(np.float32), (0, 0), smooth)
    s = cv2.GaussianBlur(s.astype(np.float32), (0, 0), smooth)
    angle = .5 * np.arctan2(s, c)
    return np.cos(angle).astype(np.float32), np.sin(angle).astype(np.float32)


def _walk(dx, dy, steps, step):
    """Follow the lines from every pixel, both ways: yields (j, x, y) positions (float32
    maps) for j = 1..steps on one side, then the other."""
    import cv2
    h, w = dx.shape
    X, Y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    for sign in (1., -1.):
        px, py = X.copy(), Y.copy()
        vx, vy = dx * sign, dy * sign
        for j in range(1, steps + 1):
            px += vx * step
            py += vy * step
            nx = cv2.remap(dx, px, py, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
            ny = cv2.remap(dy, px, py, cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
            back = nx * vx + ny * vy < 0          # an orientation has no sign: keep going on
            vx = np.where(back, -nx, nx)
            vy = np.where(back, -ny, ny)
            yield j, px, py


def streaks(dx, dy, width_px, length_px, seed=SEED):
    """0..1 for every pixel, the same along a line and different from line to line
    (thin random lines along the directions), evenly spread."""
    import cv2
    h, w = dx.shape
    rng = np.random.default_rng(seed)
    cell = max(1., float(width_px))
    small = rng.random((max(2, int(h / cell) + 2), max(2, int(w / cell) + 2)), dtype=np.float32)
    noise = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    step = 1.
    steps = max(2, int(length_px / 2 / step))
    total = noise.copy()
    weights = np.ones_like(noise)
    for j, px, py in _walk(dx, dy, steps, step):
        wj = 1. - j / (steps + 1.)
        total += wj * cv2.remap(noise, px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        weights += wj
    value = (total / weights).ravel()
    rank = np.empty(value.size, np.float32)
    rank[np.argsort(value, kind='stable')] = np.linspace(0., 1., value.size, dtype=np.float32)
    return rank.reshape(h, w)


def pencil_moments(moments, rgb, regions, radius, px_per_cell, scale=1., seed=SEED):
    """The moments (brush clock, inf: never) turned into pencil lines (see the module).

    moments: float32 (h, w) when the brush first passes every pixel; rgb: uint8 (h, w, 3);
    regions: int (h, w), the part of every pixel (lines stay in their part); radius: the brush
    radius in pixels (a number or an (h, w) map); px_per_cell: pixels per unit of brush travel
    (the brush moves one grid cell per unit of the clock)."""
    import cv2
    h, w = moments.shape
    gray = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.
    dx, dy = directions(gray, scale)
    rad = np.broadcast_to(np.asarray(radius, np.float32), (h, w))
    rad = np.clip(rad, 1.5 * scale, 60. * scale)
    line_w = max(1.2, 1.6 * scale)
    u = streaks(dx, dy, line_w, max(8., 18. * scale), seed)
    speed = max(1e-6, float(px_per_cell))            # brush: pixels per unit of the clock
    reach = np.minimum(LEAD * rad, 28. * scale) * u   # this line may be drawn this far ahead
    step = max(1., 1.2 * scale)
    steps = int(np.ceil(float(reach.max()) / step)) if reach.size else 0
    out = moments.copy()
    reg = regions.astype(np.int32)
    finite = np.isfinite(moments)
    safe = np.where(finite, moments, np.float32(3e38)).astype(np.float32)
    regf = reg.astype(np.float32)
    if steps > 0:
        alive = np.ones((h, w), bool)
        side = 0
        for j, px, py in _walk(dx, dy, steps, step):
            if j == 1:
                side += 1
                alive = np.ones((h, w), bool)
            same = cv2.remap(regf, px, py, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
                             borderValue=-1.) == regf
            alive &= same
            dist = j * step
            take = alive & (dist <= reach)
            if not take.any():
                continue
            there = cv2.remap(safe, px, py, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
                              borderValue=3e38)
            when = there + dist / (GROW * speed)
            np.minimum(out, np.where(take & (there < 1e38), when, np.inf).astype(np.float32), out=out)
    # some lines wait a little behind the brush, but every line of a part is drawn before the
    # brush leaves that part
    lag = (LAG * rad / speed) * (1. - u)
    late = out + lag.astype(np.float32)
    ids = reg.ravel()
    fin = np.isfinite(moments).ravel()
    top = int(ids.max()) + 1 if ids.size else 1
    last = np.full(top, -np.inf)
    np.maximum.at(last, ids[fin], moments.ravel()[fin].astype(np.float64))
    end = last[reg].astype(np.float32)
    capped = np.where(np.isfinite(end), np.minimum(late, np.maximum(end, out)), late)
    return np.where(np.isfinite(out), capped, out).astype(np.float32)
