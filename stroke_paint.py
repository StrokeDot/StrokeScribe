"""Real brush strokes for Adaptive Hand Painting (1.0.1-experimental).

The user (after 1.0.0): the painting looked like pixels filling up; it should look like the
picture is being drawn - strokes, as close as possible to a hand colouring in zigzags.

The painting plan (adaptive_hand.build_plan) is a timed brush route on a coarse grid (about
224 cells across); the old look revealed whole grid cells, enlarged with square pixels, so
the edge was a staircase. Here the same route is drawn as what it is: every painting
segment is a round-capped brush stroke, laid at the picture's full working size. For every
pixel the moment the brush first passes over it is worked out once (a "moment map"); a frame
only compares that map with the clock, so the edge of the paint is the actual zigzag of the
strokes - round ends, overlapping passes - moving with the hand.

Strokes stay inside their colour region, but the region's border is taken from the
picture itself (a pixel near a border belongs to the neighbouring region whose colour it
is closest to), so paint stops at the real colour edges, not at grid squares. The visible
edge of the picture comes from its own alpha. Whatever the strokes do not reach is shown
when the grid plan reaches it, and everything is shown when the painting is done, so no
pixel is ever left unpainted.
"""
from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np

LIMIT = 1280            # the moment map is at most this many pixels across
VISIBLE = 64            # alpha from which a pixel counts as visible (as adaptive_hand)
_FIELDS = OrderedDict()


def _merged(segments):
    """Painting segments joined where the brush keeps going straight on in one region with
    one brush size (the plan steps one grid cell at a time; its time is linear in distance,
    so joining keeps every moment the same)."""
    out = []
    for s in segments:
        if not s.painting:
            continue
        if out:
            a, b, r, rid, t0, t1 = out[-1]
            if rid == s.region and abs(r - s.radius) < 1e-9 and b == s.a and abs(t1 - s.start) < 1e-9:
                d1 = (b[0] - a[0], b[1] - a[1]); d2 = (s.b[0] - s.a[0], s.b[1] - s.a[1])
                l1, l2 = math.hypot(*d1), math.hypot(*d2)
                if l1 > 1e-9 and l2 > 1e-9 and abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-6 * l1 * l2 \
                        and d1[0] * d2[0] + d1[1] * d2[1] > 0:
                    # same direction: one longer stroke, if its speed is the same
                    v1, v2 = (t1 - t0) / l1, (s.end - s.start) / l2
                    if abs(v1 - v2) < 1e-6 * max(v1, v2, 1e-9):
                        out[-1] = (a, s.b, r, rid, t0, s.end)
                        continue
        out.append((s.a, s.b, s.radius, s.region, s.start, s.end))
    return out


def _region_map(plan, rgb, width, height):
    """Region of every pixel: the grid's, but at a border the neighbouring region whose
    mean colour is closest to the pixel's own colour (paint stops at real colour edges)."""
    import cv2
    gw, gh = plan.size
    labels = np.asarray(plan.labels, np.int32).reshape(gh, gw)
    ys = np.minimum(gh - 1, ((np.arange(height) + .5) * gh / height).astype(np.int64))
    xs = np.minimum(gw - 1, ((np.arange(width) + .5) * gw / width).astype(np.int64))
    base = labels[ys[:, None], xs[None, :]]
    # mean colour of every region, from the picture at grid size
    small = cv2.resize(rgb, (gw, gh), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float64)
    flat = labels.reshape(-1)
    count = np.bincount(flat, minlength=flat.max() + 1).astype(np.float64)
    means = np.zeros((count.size, 3))
    for c in range(3):
        means[:, c] = np.bincount(flat, weights=small[:, c], minlength=count.size)
    means /= np.maximum(count, 1)[:, None]
    # only where the 3x3 grid neighbourhood holds more than one region
    lab_pad = np.pad(labels, 1, mode='edge')
    mixed = np.zeros_like(labels, bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            mixed |= lab_pad[1 + dy:1 + dy + gh, 1 + dx:1 + dx + gw] != labels
    border = mixed[ys[:, None], xs[None, :]]
    if not border.any():
        return base
    py, px = np.nonzero(border)
    colour = rgb[py, px].astype(np.float64)
    gy, gx = ys[py], xs[px]
    best = base[py, px].copy()
    best_d = np.full(py.size, np.inf)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cand = labels[np.clip(gy + dy, 0, gh - 1), np.clip(gx + dx, 0, gw - 1)]
            ok = cand > 0
            d = np.where(ok, ((colour - means[cand]) ** 2).sum(1), np.inf)
            take = d < best_d
            best[take] = cand[take]; best_d[take] = d[take]
    out = base.copy()
    out[py, px] = best
    return out


def build_field(plan, image):
    """(moments, alpha) at the working size: when the brush first passes every pixel (in
    the plan's clock; inf: never) and the picture's own alpha there."""
    import cv2
    from adaptive_hand import pil_image
    source = pil_image(image).convert('RGBA')
    iw, ih = source.size
    scale = min(1., LIMIT / max(1, iw, ih))
    width, height = max(2, round(iw * scale)), max(2, round(ih * scale))
    rgba = np.asarray(source, np.uint8)
    if (width, height) != (iw, ih):
        rgba = cv2.resize(rgba, (width, height), interpolation=cv2.INTER_AREA)
    moments, alpha, regions, radius = _moments(plan, rgba, width, height, details=True)
    gw, gh = plan.size
    moments = _fill_from_nearest(moments, alpha)
    if PENCIL_LINES:
        # the edge as lines that follow the picture's own strokes (pencil_lines.py)
        from pencil_lines import pencil_moments
        known = radius > 0
        typical = float(np.median(radius[known])) if known.any() else 4.
        radius = np.where(known, radius, typical).astype(np.float32)
        moments = pencil_moments(moments, rgba[..., :3], regions, radius,
                                 px_per_cell=(width / gw + height / gh) / 2,
                                 scale=max(width, height) / LIMIT)
    return moments, alpha


def _fill_from_nearest(moments, alpha):
    """exp.3 (the user: Arthur's end "glitch": the last stroke revealed the rest): a visible
    pixel the strokes do not reach (the faint soft edges, a few percent opaque, were 11% of
    Arthur) appears with the nearest pixel they do reach, never all together at the end."""
    import cv2
    reached = np.isfinite(moments)
    left = ~reached & (alpha > 0)
    if not left.any() or not reached.any():
        return moments
    _, nearest = cv2.distanceTransformWithLabels((~reached).astype(np.uint8), cv2.DIST_L2, 5,
                                                 labelType=cv2.DIST_LABEL_PIXEL)
    values = moments[reached]            # the labels number the reached pixels in reading order
    out = moments.copy()
    out[left] = values[np.clip(nearest[left] - 1, 0, values.size - 1)]
    return out


PENCIL_LINES = True      # tests: False keeps the plain round strokes
ZIG_SWING = .7           # exp.3: the hand swings this many ring widths to each side of the trace
ZIG_WAVE = .9            # exp.3: and moves on this many ring widths per back-and-forth
ZIG_PEN = .32            # exp.3: the pencil's radius, in ring widths
PENCIL = .6              # exp.2: the stroke is this share of the brush size (a pencil, more strokes)
LEG = 4.5                # exp.2: a stroke is at most this many stroke radii long...
LEG_MIN, LEG_MAX = .03, .08   # ...but between these shares of the picture's width


SAME_COLOUR = 30.        # RGB distance: a stroke may go on into a neighbouring part of this colour


def _means(regions, rgb):
    count = np.bincount(regions.ravel()).astype(np.float64)
    means = np.zeros((count.size, 3))
    for c in range(3):
        means[:, c] = np.bincount(regions.ravel(), weights=rgb[..., c].ravel().astype(np.float64),
                                  minlength=count.size)
    return means / np.maximum(count, 1)[:, None]


def _moments(plan, rgba, width, height, details=False):
    """The first moment the brush strokes pass over every pixel (inf: never), and alpha.
    A stroke stays in its part; it may go on into a neighbouring part only where the picture
    has the stroke's own colour there (one colour area split in parts has no real border, so
    no grid staircase shows between them). details: also the part of every pixel and the
    radius (pixels) of the stroke that reached it first (0: none)."""
    rgb, alpha = rgba[..., :3], rgba[..., 3]
    regions = _region_map(plan, rgb, width, height)
    means = _means(regions, rgb)
    rgbf = rgb.astype(np.float32)
    gw, gh = plan.size
    sx, sy = width / gw, height / gh
    s = (sx + sy) / 2
    moments = np.full((height, width), np.inf, np.float32)
    radius = np.zeros((height, width), np.float32) if details else None
    for a, b, r, rid, t0, t1 in _merged(plan.segments):
        ax, ay, bx, by = a[0] * sx, a[1] * sy, b[0] * sx, b[1] * sy
        rad = max(1., r * s)
        x0, x1 = max(0, int(min(ax, bx) - rad)), min(width, int(math.ceil(max(ax, bx) + rad)) + 1)
        y0, y1 = max(0, int(min(ay, by) - rad)), min(height, int(math.ceil(max(ay, by) + rad)) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        X = np.arange(x0, x1, dtype=np.float32) + .5
        Y = np.arange(y0, y1, dtype=np.float32)[:, None] + .5
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 > 1e-12:
            t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0., 1.)
        else:
            t = np.zeros((y1 - y0, x1 - x0), np.float32)
        qx, qy = ax + t * dx - X, ay + t * dy - Y
        own = regions[y0:y1, x0:x1] == rid
        if 0 < rid < len(means):
            diff = rgbf[y0:y1, x0:x1] - means[rid].astype(np.float32)
            own |= (diff * diff).sum(-1) <= SAME_COLOUR * SAME_COLOUR
        inside = (qx * qx + qy * qy <= rad * rad) & own & (alpha[y0:y1, x0:x1] > 0)
        if not inside.any():
            continue
        when = (t0 + t * (t1 - t0)).astype(np.float32)
        box = moments[y0:y1, x0:x1]
        if radius is not None:
            first = inside & (when < box)
            radius[y0:y1, x0:x1][first] = rad
        np.minimum(box, np.where(inside, when, np.inf), out=box)
    if details:
        return moments, alpha, regions, radius
    return moments, alpha


def field_for(plan, image):
    key = (id(plan), image.cacheKey(), image.width(), image.height())
    hit = _FIELDS.get(key)
    if hit is not None and hit[0] is plan:
        _FIELDS.move_to_end(key)
        return hit[1]
    field = build_field(plan, image)
    _FIELDS[key] = (plan, field)
    while len(_FIELDS) > 6:
        _FIELDS.popitem(last=False)
    return field


def stroke_alpha(plan, image, progress):
    """0..255 at the working size: painted (255) where the brush has passed by `progress`."""
    moments, alpha = field_for(plan, image)
    if progress <= 0:
        return np.zeros(moments.shape, np.uint8)
    clock = max(0., min(1., float(progress))) / .98 * plan.total
    if clock >= plan.total:
        return np.full(moments.shape, 255, np.uint8)
    return np.where(moments <= clock, 255, 0).astype(np.uint8)


# ------------------------------------------------------------------ the hand-colouring route
WORK = 512              # the route is planned on the picture at most this many pixels across
TURN_INSIDE = .85       # a turn is painted (one zigzag) when this share of it is inside the part


def _capsules(canvas, strokes, value=255):
    """Draw round-capped strokes [(ax, ay, bx, by, r)] into a uint8 canvas (coverage)."""
    import cv2
    for ax, ay, bx, by, r in strokes:
        t = max(1, int(round(2 * r)))
        cv2.line(canvas, (int(round(ax)), int(round(ay))), (int(round(bx)), int(round(by))), value, t,
                 lineType=cv2.LINE_8)
        cv2.circle(canvas, (int(round(ax)), int(round(ay))), max(1, int(round(r))), value, -1)
        cv2.circle(canvas, (int(round(bx)), int(round(by))), max(1, int(round(r))), value, -1)
    return canvas


def _hatch(mask, r, spacing, cursor, leg=None):
    """Zigzag strokes over one part (a boolean mask, local coordinates): short back-and-forth
    passes across the part's narrow side, moving along its long side, like hatching.

    leg (exp.2, the user: "the drawing hand requires more zigzag movement"): the longest a
    single stroke may be; a wider part is hatched in bands of that width, one after the other
    (snaking), so the hand keeps making short quick strokes instead of long sweeps.
    Returns [(x0, y0, x1, y1)] in drawing order."""
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return []
    pts = np.stack([xs + .5, ys + .5], 1).astype(np.float64)
    c = pts.mean(0)
    if xs.size > 2:
        cov = np.cov((pts - c).T)
        w, v = np.linalg.eigh(cov)
        u = v[:, 1]                      # the long side: the passes move along it
    else:
        u = np.array([1., 0.])
    u = u / max(1e-9, np.hypot(*u))
    n = np.array([-u[1], u[0]])          # across: each pass goes this way
    pu = (pts - c) @ u
    pn = (pts - c) @ n
    d = max(1., 2 * r * spacing)
    lo, hi = pu.min(), pu.max()
    count = max(1, int(math.ceil((hi - lo) / d)))
    step = (hi - lo) / count if count > 1 else 0.
    lines = [lo + (hi - lo) / 2] if count == 1 else [lo + step * (k + .5) for k in range(count)]
    # start from the end of the part nearer the cursor
    if np.hypot(*(c + u * lo - cursor)) > np.hypot(*(c + u * hi - cursor)):
        lines.reverse()
    nlo, nhi = pn.min() - .5, pn.max() + .5
    width = nhi - nlo
    bands = max(1, int(math.ceil(width / leg))) if leg else 1
    edges = [nlo + width * k / bands for k in range(bands + 1)]
    pairs = list(zip(edges[:-1], edges[1:]))
    if np.hypot(*(c + n * nlo - cursor)) > np.hypot(*(c + n * nhi - cursor)):
        pairs.reverse()                  # the band nearer the cursor first
    out = []
    forward = True
    for index, (b0, b1) in enumerate(pairs):
        order = lines if index % 2 == 0 else lines[::-1]       # snake from band to band
        for uk in order:
            sel = (np.abs(pu - uk) <= .75) & (pn >= b0 - .5) & (pn <= b1 + .5)
            if not sel.any():
                continue
            vs = np.sort(pn[sel])
            cuts = np.nonzero(np.diff(vs) > 2.)[0]
            starts = np.concatenate([[0], cuts + 1]); ends = np.concatenate([cuts, [vs.size - 1]])
            runs = []
            for s0, s1 in zip(starts, ends):
                v0, v1 = max(vs[s0] - .5, b0), min(vs[s1] + .5, b1)
                if v1 <= v0:
                    continue
                inset = min(r * .45, (v1 - v0) / 2)
                runs.append((c + u * uk + n * (v0 + inset), c + u * uk + n * (v1 - inset)))
            if not runs:
                continue
            runs = runs if forward else [(b, a) for a, b in reversed(runs)]
            out.extend((a[0], a[1], b[0], b[1]) for a, b in runs)
            forward = not forward
    return out


def build_stroke_plan(drawing, image, brush_width=.14, stroke_spacing=.55):
    """Painter's parts, order and traces, drawn with big zigzag strokes (see module).

    exp.2 (the user: "only go with the painter... also have this option of colour areas, AI
    parts"): the parts are Painter's (colour areas, or the real parts the AI found) in
    Painter's order (big parts first, or the order set in Line order)."""
    import cv2
    from adaptive_hand import pil_image, PaintPlan, Segment
    from painter_paint import build_painter_plan
    base = build_painter_plan(drawing, image, brush_width, stroke_spacing)
    gw, gh = base.size
    source = pil_image(image).convert('RGBA')
    iw, ih = source.size
    scale = min(1., WORK / max(1, iw, ih))
    W, H = max(2, round(iw * scale)), max(2, round(ih * scale))
    rgba = np.asarray(source, np.uint8)
    if (W, H) != (iw, ih):
        rgba = cv2.resize(rgba, (W, H), interpolation=cv2.INTER_AREA)
    regions = _region_map(base, rgba[..., :3], W, H)
    visible = rgba[..., 3] >= VISIBLE
    to_grid = (gw / W + gh / H) / 2
    # the parts in the Adaptive plan's order (when the brush first reaches them)
    order, seen = [], set()
    for s in base.segments:
        if s.painting and s.region not in seen:
            seen.add(s.region); order.append(s.region)
    for rid in sorted(set(int(v) for v in np.unique(regions)) - seen - {0}):
        order.append(rid)
    flat = regions.ravel()
    idx = np.argsort(flat, kind='stable')
    sorted_ids = flat[idx]
    maximum = max(1.5, W * max(.02, min(.5, float(brush_width))) / 2)
    spacing = max(.2, min(.9, float(stroke_spacing)))
    segments = []
    clock = 0.
    cursor = np.array([base.origin[0] / gw * W, base.origin[1] / gh * H])

    def add(a, b, r, rid, painting):
        nonlocal clock, cursor
        dist = math.dist(a, b) * to_grid
        dur = max(.05, dist) if painting else max(.5, min(12., dist * .2))
        segments.append(Segment((a[0] / W * gw, a[1] / H * gh), (b[0] / W * gw, b[1] / H * gh),
                                max(.5, r * to_grid), int(rid), bool(painting), clock, clock + dur))
        clock += dur
        cursor = np.array(b, float)

    def inside_share(mask, x0, y0, a, b):
        n = max(2, int(math.dist(a, b)))
        xs = np.clip((np.linspace(a[0], b[0], n) - x0).astype(int), 0, mask.shape[1] - 1)
        ys = np.clip((np.linspace(a[1], b[1], n) - y0).astype(int), 0, mask.shape[0] - 1)
        return float(mask[ys, xs].mean())

    # exp.3 (the user: "follow the traces, but with increasing the hand movement... the hand is
    # not visible"): the hand follows Painter's traces (its strokes around every shape, from the
    # edge inwards) and zigzags across them in big, clearly visible back-and-forth strokes, wide
    # enough to cover the trace's whole band, so the movement reads as drawing.
    def zigzag(points, band, r, rid):
        """Back-and-forth strokes along a trace (WORK pixels), each across the band."""
        pts = np.asarray(points, np.float64)
        if len(pts) < 2:
            return
        steps = np.hypot(*np.diff(pts, axis=0).T)
        along = np.concatenate([[0.], np.cumsum(steps)])
        length = float(along[-1])
        if length < 1e-6:
            return
        wave = max(1.5, band * ZIG_WAVE)                # how far the hand moves on per stroke
        count = max(2, int(math.ceil(length / (wave / 2))) + 1)
        at = np.linspace(0., length, count)
        xs = np.interp(at, along, pts[:, 0]); ys = np.interp(at, along, pts[:, 1])
        dx = np.gradient(xs); dy = np.gradient(ys)
        norm = np.maximum(1e-9, np.hypot(dx, dy))
        nx, ny = -dy / norm, dx / norm
        swing = band * ZIG_SWING
        side = np.where(np.arange(count) % 2 == 0, 1., -1.)
        side[0] = side[-1] = 0.                         # start and end on the trace
        zx = np.clip(xs + nx * swing * side, 0, W - 1); zy = np.clip(ys + ny * swing * side, 0, H - 1)
        if math.dist(cursor, (zx[0], zy[0])) > 1e-6:
            add(tuple(cursor), (zx[0], zy[0]), r, rid, math.dist(cursor, (zx[0], zy[0])) <= band * 1.5)
        for k in range(1, count):
            add((zx[k - 1], zy[k - 1]), (zx[k], zy[k]), r, rid, True)

    trace, trace_rid, trace_r = [], None, 1.
    for seg in base.segments + [None]:
        if seg is not None and seg.painting and (not trace or seg.region == trace_rid):
            a = (seg.a[0] / gw * W, seg.a[1] / gh * H); b = (seg.b[0] / gw * W, seg.b[1] / gh * H)
            if not trace:
                trace = [a]; trace_rid = seg.region
                trace_r = seg.radius / .75 / to_grid        # Painter's ring width, in WORK pixels
            trace.append(b)
            continue
        if trace:
            band = max(2., trace_r)
            zigzag(trace, band, max(1.2, band * ZIG_PEN), trace_rid)
            trace = []
        if seg is not None and seg.painting:              # a new part starts right here
            a = (seg.a[0] / gw * W, seg.a[1] / gh * H); b = (seg.b[0] / gw * W, seg.b[1] / gh * H)
            trace = [a, b]; trace_rid = seg.region; trace_r = seg.radius / .75 / to_grid
    plan = PaintPlan(base.size, base.labels, segments, [s.end for s in segments], [], base.origin,
                     clock, list(base.warnings), base.region_count)
    # the grid of moments (for everything that reads the plan's cells): the first moment the
    # strokes reach any pixel of a cell; cells they never reach: the end
    moments, _ = _moments(plan, rgba, W, H)
    ys = np.minimum(gh - 1, ((np.arange(H) + .5) * gh / H).astype(np.int64))
    xs = np.minimum(gw - 1, ((np.arange(W) + .5) * gw / W).astype(np.int64))
    cell = (ys[:, None] * gw + xs[None, :]).ravel()
    arrival = np.full(gw * gh, np.inf)
    np.minimum.at(arrival, cell, moments.ravel().astype(np.float64))
    labels = np.asarray(base.labels)
    arrival[(labels > 0) & ~np.isfinite(arrival)] = clock
    old = np.asarray(base.arrival, np.float64)
    arrival[(labels == 0) & np.isfinite(old) & ~np.isfinite(arrival)] = clock
    plan.arrival = arrival.tolist()
    return plan
