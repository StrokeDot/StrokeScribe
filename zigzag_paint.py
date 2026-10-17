"""Zigzag sweep painting: colour scribbled in along one logical route.

The hand starts where the drawing ended and travels along the object's
"spine" (its centre line) from one end to the other, zigzagging across the
shape as it goes, wider on broad parts, narrower on thin parts, so the
colour appears like a quick marker scribble. Branches and any spots the main
sweep missed follow, each with its own short zigzag, until every visible
pixel is painted. The result uses the same plan format as Adaptive Hand
Painting (timed brush segments + per-cell arrival times), so preview, export,
hand and guide-line removal all work unchanged.
"""
from __future__ import annotations

import math
from collections import deque

import cv2
import numpy as np

from lineart import thin

NEIGHBOURS8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _tree_chains(pixels, distance, cursor):
    """Chains for the skeleton piece nearest the cursor (see _routes)."""
    degree = {p: sum((p[0] + dy, p[1] + dx) in pixels for dy, dx in NEIGHBOURS8) for p in pixels}
    gap = lambda p: math.hypot(p[1] + .5 - cursor[0], p[0] + .5 - cursor[1])
    nearest = min(pixels, key=lambda p: (gap(p), p))
    ends = [p for p in pixels if degree[p] <= 1]
    # Start at a free end (a natural place to begin) unless one is much
    # farther than the nearest part of the route (e.g. a closed loop).
    end = min(ends, key=lambda p: (gap(p), p)) if ends else nearest
    slack = .15 * max(distance.shape)
    root = end if gap(end) <= gap(nearest) + slack else nearest
    # Depth-first, so a closed loop (a handle, a headband with both ear
    # cups) is followed all the way round instead of split in two halves.
    children = {root: []}
    order = [root]
    stack = [(root, iter(NEIGHBOURS8))]
    while stack:
        p, moves = stack[-1]
        for dy, dx in moves:
            q = (p[0] + dy, p[1] + dx)
            if q in pixels and q not in children:
                children[q] = []
                children[p].append(q)
                order.append(q)
                stack.append((q, iter(NEIGHBOURS8)))
                break
        else:
            stack.pop()
    height = {}
    for p in reversed(order):
        height[p] = 1 + max((height[c] for c in children[p]), default=0)

    def kept(p):
        kids = sorted(children[p], key=lambda c: (-height[c], c))
        if len(kids) < 2:
            return kids
        limit = max(4., 2.5 * float(distance[p]))
        return kids[:1] + [c for c in kids[1:] if height[c] >= limit]

    chains = []
    stack = [(root, None)]
    while stack:
        node, junction = stack.pop()
        chain = [junction] if junction is not None else []
        while True:
            chain.append(node)
            kids = kept(node)
            if not kids:
                break
            if len(kids) == 1:
                node = kids[0]
                continue
            stack.append((kids[0], node))                 # the main branch last
            for side in sorted(kids[1:], key=lambda c: (-height[c], c)):
                stack.append((side, node))                # shortest side first
            break
        if len(chain) >= 2:
            chains.append([(float(x) + .5, float(y) + .5) for y, x in chain])
    return {'chains': chains, 'used': set(children)}


def _routes(skeleton, distance, cursor):
    """Ordered centre-line chains covering a skeleton.

    Starts at the skeleton end nearest the cursor and walks the whole tree;
    at a fork, short side branches (a microphone, a handle) are painted as
    the hand passes them and the longest branch is continued last, so the
    route ends at the far end of the object. Tiny spurs (bumps on the
    outline) are skipped; the zigzag around them covers those anyway.
    """
    remaining = set(zip(*np.nonzero(skeleton)))
    chains = []
    while remaining:
        tree = _tree_chains(remaining, distance, cursor)
        chains += tree['chains']
        remaining -= tree['used']
        if chains:
            cursor = chains[-1][-1]
    return chains


def _resample(path, step):
    """Points every `step` cells along a polyline."""
    if len(path) < 2:
        return list(path)
    out = [path[0]]
    carry = 0.
    for a, b in zip(path, path[1:]):
        seg = math.dist(a, b)
        t = step - carry
        while t <= seg:
            f = t / seg
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            t += step
        carry = seg - (t - step)
    if math.dist(out[-1], path[-1]) > step * .3:
        out.append(path[-1])
    return out


def _smooth_path(path, window=4):
    if len(path) < 3:
        return path
    xs = np.array([p[0] for p in path]); ys = np.array([p[1] for p in path])
    k = np.ones(2 * window + 1) / (2 * window + 1)
    pad = lambda v: np.concatenate([np.full(window, v[0]), v, np.full(window, v[-1])])
    return list(zip(np.convolve(pad(xs), k, 'valid'), np.convolve(pad(ys), k, 'valid')))


class _Planner:
    def __init__(self, support, faint, origin, brush_width, spacing, seed=7):
        self.support = support                       # visible cells (bool, h x w)
        self.faint = faint
        self.h, self.w = support.shape
        self.max_radius = max(.9, self.w * max(.02, min(.5, float(brush_width))) / 2)
        self.spacing = max(.2, min(.9, float(spacing)))
        count, self.components = cv2.connectedComponents(support.astype(np.uint8), connectivity=8)
        self.component_count = count - 1
        self.arrival = np.full(support.shape, np.inf)
        self.segments = []          # (a, b, radius, region, painting, start, end)
        self.clock = 0.
        self.cursor = origin
        self.rng = np.random.default_rng(seed)

    # -- primitive moves (same timing rules as Adaptive Hand Painting)
    def _stamp(self, point, radius, region, when):
        x, y = point
        x0, x1 = max(0, math.floor(x - radius)), min(self.w, math.ceil(x + radius))
        y0, y1 = max(0, math.floor(y - radius)), min(self.h, math.ceil(y + radius))
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        disk = ((xx + .5 - x) ** 2 + (yy + .5 - y) ** 2 <= radius * radius)
        mask = disk & (self.components[y0:y1, x0:x1] == region)
        block = self.arrival[y0:y1, x0:x1]
        block[mask] = np.minimum(block[mask], when)

    def move(self, point, region, painting, radius=.9):
        distance = math.dist(self.cursor, point)
        duration = max(.05, distance) if painting else max(.5, min(12., distance * .2))
        self.segments.append((self.cursor, point, radius, region, painting,
                              self.clock, self.clock + duration))
        if painting:
            steps = max(1, math.ceil(distance / .35))
            for j in range(steps + 1):
                f = j / steps
                self._stamp((self.cursor[0] + (point[0] - self.cursor[0]) * f,
                             self.cursor[1] + (point[1] - self.cursor[1]) * f),
                            radius, region, self.clock + duration * f)
        self.clock += duration
        self.cursor = point

    def hop(self, point, region, radius):
        """Go to `point`: keep painting over a short gap, lift for a long one."""
        x, y = int(self.cursor[0]), int(self.cursor[1])
        inside = (0 <= x < self.w and 0 <= y < self.h and self.components[y, x] == region
                  and np.isfinite(self.arrival[y, x]))
        if inside and math.dist(self.cursor, point) <= 2.5 * radius:
            self.move(point, region, True, radius)
        else:
            self.move(point, region, False)

    def _painted(self, p):
        x, y = min(self.w - 1, max(0, int(p[0]))), min(self.h - 1, max(0, int(p[1])))
        return bool(np.isfinite(self.arrival[y, x]))

    # -- zigzag sweeps along the centre lines of a region
    def sweep(self, mask, region):
        """Zigzag along every main centre line of `mask`, in route order."""
        distance = cv2.distanceTransform(np.pad(mask.astype(np.uint8), 1), cv2.DIST_L2, 3)[1:-1, 1:-1]
        # Centre lines of a softened outline: bumps and notches in the edge
        # would otherwise sprout side branches the hand has to visit.
        sigma = max(1., min(4., float(distance.max()) * .25))
        soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma) > .5
        soft &= mask
        if soft.sum() < mask.sum() * .6:
            soft = mask
        chains = _routes(thin(soft), distance, self.cursor) if mask.sum() > 3 else []
        if not chains:
            ys, xs = np.nonzero(mask)
            centre = (float(xs.mean()) + .5, float(ys.mean()) + .5)
            chains = [[centre, (centre[0] + .01, centre[1])]]

        def half_width(p):
            x, y = min(self.w - 1, max(0, int(p[0]))), min(self.h - 1, max(0, int(p[1])))
            return float(distance[y, x])

        def extent(p, dx, dy, limit):
            t = 0.
            while t < limit:
                x, y = int(p[0] + dx * (t + .7)), int(p[1] + dy * (t + .7))
                if not (0 <= x < self.w and 0 <= y < self.h and mask[y, x]):
                    break
                t += .7
            return t

        for chain in chains:
            if len(chain) > 2 and np.mean([self._painted(p) for p in chain]) > .97:
                continue                                    # already covered
            chain = _smooth_path(chain, 3)
            typical = max(1., float(np.median([half_width(p) for p in chain])))
            radius = min(self.max_radius, max(.9, typical * .6))
            pitch = max(.7, 1.6 * radius * self.spacing)
            # Centre lines stop short of the shape's ends; carry the route on
            # to the edge so ends and corners are painted in the same pass.
            chain = list(chain)
            for at_start in (True, False):
                if len(chain) < 2:
                    break
                tip, inner = (chain[0], chain[min(len(chain) - 1, 3)]) if at_start \
                    else (chain[-1], chain[max(0, len(chain) - 4)])
                if at_start and self._painted(tip):
                    continue                                # starts at a fork
                dx, dy = tip[0] - inner[0], tip[1] - inner[1]
                n = math.hypot(dx, dy)
                if n < 1e-6:
                    continue
                dx, dy = dx / n, dy / n
                run = extent(tip, dx, dy, half_width(tip) * 1.5 + 2) - radius * .5
                if run > .5:
                    point = (tip[0] + dx * run, tip[1] + dy * run)
                    if at_start:
                        chain.insert(0, point)
                    else:
                        chain.append(point)
            # Dense candidates; strokes are picked from them so the far ends
            # of neighbouring strokes stay close enough to leave no gaps,
            # even where the route curves and the shape is wide.
            dense = _resample(chain, pitch / 4)
            if len(dense) < 2:
                dense = chain[:2]
            k = max(2, round(8 * radius / pitch))           # gentle turning
            jitter = 1. + self.rng.uniform(-.06, .12, (len(dense), 2))

            def tip_at(i, side):
                p = dense[i]
                a = dense[max(0, i - k)]; b = dense[min(len(dense) - 1, i + k)]
                tx, ty = b[0] - a[0], b[1] - a[1]
                n = math.hypot(tx, ty) or 1.
                nx, ny = -ty / n * side, tx / n * side     # across the shape
                hw = half_width(p)
                r = min(radius, max(.9, hw * .9))
                # Reach the edge on this side (shapes bulge unevenly around
                # their centre line); the brush is clipped to the shape, and
                # slightly uneven tips give a hand-made, scribbled look.
                edge = extent(p, nx, ny, max(hw, min(hw * 2.5, hw + 2 * radius)))
                reach = max(0., edge - r * .2) * float(jitter[i, int(side > 0)])
                return (p[0] + nx * reach, p[1] + ny * reach), r

            self.hop(dense[0], region, radius)
            side, i = 1, 0
            last = {}
            while True:
                tip, r = tip_at(i, side)
                self.move(tip, region, True, r)
                last[side] = tip
                if i >= len(dense) - 1:
                    break
                side = -side
                j = i + 1
                for c in range(i + 2, min(len(dense), i + 5)):
                    t, rc = tip_at(c, side)
                    if side in last and math.dist(t, last[side]) > 1.7 * rc:
                        break
                    j = c
                i = j

    def run(self):
        order = list(range(1, self.component_count + 1))
        while order:
            def near(c):
                ys, xs = np.nonzero(self.components == c)
                return float(np.min((xs + .5 - self.cursor[0]) ** 2 + (ys + .5 - self.cursor[1]) ** 2))
            region = min(order, key=near)
            order.remove(region)
            part = self.components == region
            self.sweep(part, region)
            # Missed spots, nearest first, until all is painted.
            for _ in range(400):
                missing = part & ~np.isfinite(self.arrival)
                if not missing.any():
                    break
                n, pieces, stats, _ = cv2.connectedComponentsWithStats(missing.astype(np.uint8), 8)
                def gap(k):
                    ys, xs = np.nonzero(pieces[stats[k, cv2.CC_STAT_TOP]:stats[k, cv2.CC_STAT_TOP] + stats[k, cv2.CC_STAT_HEIGHT],
                                               stats[k, cv2.CC_STAT_LEFT]:stats[k, cv2.CC_STAT_LEFT] + stats[k, cv2.CC_STAT_WIDTH]] == k)
                    xs = xs + stats[k, cv2.CC_STAT_LEFT] + .5; ys = ys + stats[k, cv2.CC_STAT_TOP] + .5
                    return float(np.min((xs - self.cursor[0]) ** 2 + (ys - self.cursor[1]) ** 2))
                best = min(range(1, n), key=gap)
                piece = pieces == best
                if stats[best, cv2.CC_STAT_AREA] >= 12:
                    self.sweep(piece, region)
                else:                                      # a small spot: a quick dab
                    ys, xs = np.nonzero(piece)
                    target = (float(xs.mean()) + .5, float(ys.mean()) + .5)
                    r = max(1.2, math.sqrt(len(xs) / math.pi) + .6)
                    self.hop(target, region, r)
                    self.move((target[0] + .01, target[1]), region, True, r)
            # Guarantee: anything still unreached gets a direct dab.
            for y, x in zip(*np.nonzero(part & ~np.isfinite(self.arrival))):
                if np.isfinite(self.arrival[y, x]):
                    continue
                self.hop((x + .5, y + .5), region, 1.2)
                self.move((x + .51, y + .5), region, True, 1.2)
        return self


def plan_cells(support, faint, origin, brush_width=.14, spacing=.55):
    """Plan on a grid of cells. Returns labels, segments, arrival, total."""
    if not support.any():
        raise ValueError('The color image has no visible pixels.')
    planner = _Planner(support, faint, origin, brush_width, spacing).run()
    labels = planner.components.astype(np.int64)
    arrival = planner.arrival
    return labels, planner.segments, arrival, planner.clock, planner.component_count


def build_zigzag_plan(drawing, image, brush_width=.14, stroke_spacing=.55):
    """Zigzag plan for a drawing + colour image, in Adaptive's PaintPlan form."""
    from adaptive_hand import (GRID_LIMIT, VISIBLE_ALPHA, PaintPlan, Segment,
                               _reveal_faint_with_neighbours, pil_image)
    from color_reveal import artwork_rect, last_stroke_canvas_endpoint
    source = pil_image(image)
    iw, ih = source.size
    ratio = min(1., GRID_LIMIT / max(iw, ih))
    gw, gh = max(1, math.ceil(iw * ratio)), max(1, math.ceil(ih * ratio))
    alpha = np.asarray(source.getchannel('A'))
    rows = np.minimum(gh - 1, ((2 * np.arange(ih) + 1) * gh) // (2 * ih))
    cols = np.minimum(gw - 1, ((2 * np.arange(iw) + 1) * gw) // (2 * iw))
    visible = np.zeros((gh, gw), bool); faint = np.zeros((gh, gw), bool)
    vy, vx = np.nonzero(alpha >= VISIBLE_ALPHA)
    visible[rows[vy], cols[vx]] = True
    fy, fx = np.nonzero((alpha > 0) & (alpha < VISIBLE_ALPHA))
    faint[rows[fy], cols[fx]] = True
    faint &= ~visible
    if not visible.any():
        visible, faint = faint, np.zeros_like(faint)
    rect = artwork_rect(drawing, image, 1920, 1080)
    end = last_stroke_canvas_endpoint(drawing, 1920, 1080)
    origin = ((end[0] - rect.x()) * gw / rect.width(), (end[1] - rect.y()) * gh / rect.height())
    labels, raw, arrival, total, regions = plan_cells(visible, faint, origin,
                                                      brush_width, stroke_spacing)
    segments = [Segment(a, b, r, int(rid), painting, s, e)
                for a, b, r, rid, painting, s, e in raw]
    labels_list = [int(v) for v in labels.ravel()]
    arrival_list = [float(v) for v in arrival.ravel()]
    _reveal_faint_with_neighbours(arrival_list, labels_list,
                                  bytearray(faint.ravel().astype(np.uint8)), gw, gh)
    return PaintPlan((gw, gh), labels_list, segments, [s.end for s in segments],
                     arrival_list, origin, total, [], regions)


# ---------------------------------------------------------------- band painting
# Like a painter filling a sketch from the top down: the picture is cut into bands
# (rows for "Top to bottom", columns for "Left to right"); each band is swept with a
# wide brush, back and forth across everything in it, one band after the other.
# The brush is clipped to the picture, so the background is never painted.

def _band_strokes(support, radius, across):
    """[(points, ...)] brush passes in (x, y) cells. across=False: horizontal bands
    from the top down; True: vertical bands from the left to the right."""
    grid = support.T if across else support               # rows of `grid` are the bands
    h, w = grid.shape
    pitch = max(1., 1.45 * radius)                         # neighbouring bands overlap a little
    passes = []
    forward = True
    v = radius * .8
    while v - radius < h:
        lo, hi = max(0, int(v - pitch / 2)), min(h, int(math.ceil(v + pitch / 2)))
        if hi > lo:
            cover = grid[lo:hi].any(0)
            # Runs along the band; small gaps are crossed with the brush down.
            runs, start, gap = [], None, 0
            for u in range(w):
                if cover[u]:
                    if start is None:
                        start = u
                    gap, end = 0, u
                elif start is not None:
                    gap += 1
                    if gap > 2.2 * radius:
                        runs.append((start, end)); start = None
            if start is not None:
                runs.append((start, end))
            if not forward:
                runs = [(b, a) for a, b in reversed(runs)]
            for a, b in runs:
                step = 1 if b >= a else -1
                a2, b2 = a - step * radius * .3, b + step * (radius * .3 + 1)
                # A gentle wave inside the band, like a hand sweeping a brush.
                length = abs(b2 - a2)
                count = max(2, int(length / max(1., radius * .9)) + 1)
                points = []
                for i in range(count):
                    f = i / (count - 1)
                    u = a2 + (b2 - a2) * f
                    wave = math.sin(f * math.pi * max(1., length / (radius * 3.))) * pitch * .1
                    points.append((u + .5, v + wave + .5))
                passes.append([(q, p) for p, q in points] if across else points)
            if runs:
                forward = not forward
        v += pitch
    return passes


def build_band_plan(drawing, image, brush_width=.14, stroke_spacing=.55, across=False):
    """Top to bottom (across=False) or Left to right (across=True) band painting,
    in Adaptive's PaintPlan form (same preview, export, hand and guide removal)."""
    from adaptive_hand import (GRID_LIMIT, VISIBLE_ALPHA, PaintPlan, Segment,
                               _reveal_faint_with_neighbours, pil_image)
    from color_reveal import artwork_rect, last_stroke_canvas_endpoint
    source = pil_image(image)
    iw, ih = source.size
    ratio = min(1., GRID_LIMIT / max(iw, ih))
    gw, gh = max(1, math.ceil(iw * ratio)), max(1, math.ceil(ih * ratio))
    alpha = np.asarray(source.getchannel('A'))
    rows = np.minimum(gh - 1, ((2 * np.arange(ih) + 1) * gh) // (2 * ih))
    cols = np.minimum(gw - 1, ((2 * np.arange(iw) + 1) * gw) // (2 * iw))
    visible = np.zeros((gh, gw), bool); faint = np.zeros((gh, gw), bool)
    vy, vx = np.nonzero(alpha >= VISIBLE_ALPHA)
    visible[rows[vy], cols[vx]] = True
    fy, fx = np.nonzero((alpha > 0) & (alpha < VISIBLE_ALPHA))
    faint[rows[fy], cols[fx]] = True
    faint &= ~visible
    if not visible.any():
        visible, faint = faint, np.zeros_like(faint)
    if not visible.any():
        raise ValueError('The color image has no visible pixels.')
    rect = artwork_rect(drawing, image, 1920, 1080)
    end = last_stroke_canvas_endpoint(drawing, 1920, 1080)
    origin = ((end[0] - rect.x()) * gw / rect.width(), (end[1] - rect.y()) * gh / rect.height())
    planner = _Planner(visible, faint, origin, brush_width, stroke_spacing)
    # One region: the brush may pass from one part to the next inside a band.
    planner.components = visible.astype(np.int32)
    planner.component_count = 1
    # Band height from the brush size; Stroke spacing makes the bands a little denser or looser.
    radius = max(1.2, planner.max_radius * (.55 + .5 * planner.spacing))
    for points in _band_strokes(visible, radius, across):
        planner.hop(points[0], 1, radius)
        if planner.cursor != points[0]:
            planner.move(points[0], 1, False)
        for p in points[1:]:
            planner.move(p, 1, True, radius)
    # Anything the bands missed: a quick dab, in band order.
    order = (lambda y, x: (x, y)) if across else (lambda y, x: (y, x))
    for y, x in sorted(zip(*np.nonzero(visible & ~np.isfinite(planner.arrival))), key=lambda c: order(*c)):
        if np.isfinite(planner.arrival[y, x]):
            continue
        r = max(1.2, radius * .5)
        planner.hop((x + .5, y + .5), 1, r)
        planner.move((x + .51, y + .5), 1, True, r)
    segments = [Segment(a, b, r, int(rid), painting, s, e)
                for a, b, r, rid, painting, s, e in planner.segments]
    labels_list = [int(v) for v in planner.components.astype(np.int64).ravel()]
    arrival_list = [float(v) for v in planner.arrival.ravel()]
    _reveal_faint_with_neighbours(arrival_list, labels_list,
                                  bytearray(faint.ravel().astype(np.uint8)), gw, gh)
    return PaintPlan((gw, gh), labels_list, segments, [s.end for s in segments],
                     arrival_list, origin, planner.clock, [], 1)
