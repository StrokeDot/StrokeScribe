"""Line art reconstruction: any image -> ordered single-line pen strokes.

Pipeline (numpy, OpenCV and ONNX Runtime; no Qt):
1. Object support from alpha, ignoring faint leftover background pixels.
2. Line evidence from two sources merged together:
   - TEED, a small MIT-licensed edge model (models/teed.onnx, ONNX Runtime),
     which draws artist-like contours and inner detail lines;
   - dark "ink" lines found directly (black-hat), so thick outlines become a
     single line and pencil strokes in sketches survive.
3. Thinning to 1-pixel centre lines, tracing them into strokes, and joining
   pieces through junctions where the line continues most smoothly.
4. Smoothing, removing specks, and a natural drawing order: outer outline,
   then long lines, then details, each starting near the previous end.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODEL_PATH = Path(__file__).resolve().parent / 'models' / 'teed.onnx'
TEED_MEAN = np.array([104.007, 116.669, 122.679], np.float32)  # BGR
TEED_BASELINE = 0.44  # model output where there is no line

DETAIL = {
    #        working size, strong/weak edge, min stroke (fraction of size), max strokes
    'low':    dict(size=768,  strong=.62, weak=.38, min_len=.012, max_strokes=260, loop_factor=3),
    'medium': dict(size=1024, strong=.55, weak=.32, min_len=.008, max_strokes=520, loop_factor=2.5),
    'high':   dict(size=1400, strong=.48, weak=.28, min_len=.005, max_strokes=1000, loop_factor=1.5),
    'max':    dict(size=1800, strong=.45, weak=.26, min_len=.004, max_strokes=1500, loop_factor=1.2),
}

# Clean drawing: fewer, longer, smoother strokes that read like an artist's
# drawing. Shading and texture are left to the colour painting.
CLEAN = {
    #        analysis size, edge threshold raise, min stroke (fraction), max strokes
    'low':    dict(size=640,  raise_=.12, min_len=.045, max_strokes=35),
    'medium': dict(size=768,  raise_=.10, min_len=.035, max_strokes=70),
    'high':   dict(size=896,  raise_=.08, min_len=.026, max_strokes=120),
    'max':    dict(size=1024, raise_=.06, min_len=.020, max_strokes=180),
}
STYLES = ('clean', 'detailed')

_RUNNER = None


def _runner():
    """Run the model with ONNX Runtime; OpenCV's DNN module as a fallback.

    OpenCV 4.x cannot load this model's flexible image size, so ONNX Runtime
    (MIT, installed by Setup.cmd) is the primary engine.
    """
    global _RUNNER
    if _RUNNER is None:
        if not MODEL_PATH.is_file():
            raise FileNotFoundError(f'Line art model missing: {MODEL_PATH}')
        try:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.log_severity_level = 3
            session = ort.InferenceSession(str(MODEL_PATH), options,
                                           providers=['CPUExecutionProvider'])
            _RUNNER = lambda x: session.run(None, {'image': x})[0]
        except ImportError:
            net = cv2.dnn.readNetFromONNX(str(MODEL_PATH))

            def run(x):
                net.setInput(x)
                return net.forward()
            _RUNNER = run
    return _RUNNER


# ---------------------------------------------------------------- inputs

def prepare(image, size):
    """RGB on white at working size, object support mask, and scale factor."""
    rgba = np.asarray(image.convert('RGBA'))
    alpha = rgba[:, :, 3]
    # Work on the object, not the empty canvas around it: a small object on a
    # large transparent canvas would otherwise get very few working pixels.
    offset = (0, 0)
    visible = np.argwhere(alpha >= 128)
    if len(visible) and (alpha < 128).any():
        (y0, x0), (y1, x1) = visible.min(0), visible.max(0) + 1
        pad = int(max(y1 - y0, x1 - x0) * .03) + 4
        y0, x0 = max(0, y0 - pad), max(0, x0 - pad)
        y1, x1 = min(alpha.shape[0], y1 + pad), min(alpha.shape[1], x1 + pad)
        rgba = rgba[y0:y1, x0:x1]
        alpha = rgba[:, :, 3]
        offset = (x0, y0)
    h, w = rgba.shape[:2]
    scale = min(1., size / max(w, h))
    W, H = max(8, round(w * scale)), max(8, round(h * scale))
    support = alpha >= 128
    if support.mean() > .995:          # no transparency: whole image is subject
        support = np.ones_like(support)
    else:                              # drop faint leftover background specks
        count, labels, stats, _ = cv2.connectedComponentsWithStats(support.astype(np.uint8), 8)
        if count > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            keep = np.zeros(count, bool)
            keep[1:] = areas >= max(areas.max() * .004, 50)
            support = keep[labels]
    rgb = rgba[:, :, :3].copy()
    rgb[~support] = 255
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    rgb = cv2.resize(rgb, (W, H), interpolation=interp)
    support = cv2.resize(support.astype(np.uint8) * 255, (W, H), interpolation=cv2.INTER_AREA) >= 128
    return rgb, support, scale, offset


def teed_edges(rgb):
    """Normalised edge strength 0..1 from the TEED model."""
    h, w = rgb.shape[:2]
    H, W = (h + 7) // 8 * 8, (w + 7) // 8 * 8
    bgr = cv2.resize(np.ascontiguousarray(rgb[:, :, ::-1]), (W, H),
                     interpolation=cv2.INTER_CUBIC).astype(np.float32) - TEED_MEAN
    out = _runner()(np.ascontiguousarray(bgr.transpose(2, 0, 1)[None]))[0, 0]
    out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip((out - TEED_BASELINE) / (1 - TEED_BASELINE), 0, 1)


def calm_textures(rgb):
    """Edge-preserving smoothing: removes wood grain, paper and pencil texture
    while keeping real edges sharp."""
    calm = cv2.bilateralFilter(rgb, 9, 40, 7)
    return cv2.bilateralFilter(calm, 9, 40, 7)


def is_sketch(rgb, support):
    """Pencil/charcoal drawings: almost no colour inside the object."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1][support]
    return sat.size > 0 and float(np.median(sat)) < 28


def ink_lines(rgb, support, sketch=False):
    """Dark lines thinner than ~2.5% of the image (outlines, pencil strokes).

    Areas densely packed with dark marks are shading (hatching), not lines;
    they are skipped here and revealed later by the colour painting.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Window must exceed the thickest outline so its inside fills solid;
    # large dark areas (screens, cones) are still far bigger and stay out.
    k = max(7, int(round(max(gray.shape) * .025)) | 1)
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    values = blackhat[support & (blackhat > 8)]
    if values.size < 50:
        return np.zeros_like(support)
    otsu, _ = cv2.threshold(values.astype(np.uint8).reshape(-1, 1), 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Sketch lines are lighter, so read them more sensitively; shading in a
    # sketch is denser, so allow more ink before calling an area "shading".
    floor, dense = (16, .30) if sketch else (28, .22)
    ink = (blackhat > max(otsu * (.8 if sketch else 1.), floor)) & support
    # Measured over a window much wider than any single line, so one thick
    # outline stays below the limit while hatched areas exceed it.
    window = max(15, (4 * k) | 1)
    density = cv2.boxFilter(ink.astype(np.float32), -1, (window, window))
    return ink & (density < dense)


def structural_detail(confident, base, size):
    """Keep extra confident lines only if they are rings or long lines.

    Real fine detail (speaker rings, screws, seams) forms closed loops or
    long lines; texture (wood grain, paper) forms short open dashes.
    """
    extra = confident & ~cv2.dilate(base.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(confident.astype(np.uint8), 8)
    keep = np.zeros(count, bool)
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if math.hypot(w, h) >= size * .08:
            keep[label] = True
            continue
        # A 1-pixel empty border lets the flood from outside reach every
        # non-enclosed pixel, even when a diagonal dash splits its box.
        piece = np.pad((labels[y:y + h, x:x + w] == label).astype(np.uint8), 1)
        filled = piece.copy()
        cv2.floodFill(filled, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 1)
        # Pixels the flood from outside could not reach are enclosed: a ring.
        enclosed = int((filled == 0).sum())
        keep[label] = enclosed >= 6
    return extra & keep[labels]


def long_marks(mask, min_span):
    """Keep only connected marks that span at least min_span pixels."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    keep = np.zeros(count, bool)
    spans = np.hypot(stats[1:, cv2.CC_STAT_WIDTH], stats[1:, cv2.CC_STAT_HEIGHT])
    keep[1:] = spans >= min_span
    return keep[labels]


def hysteresis(strength, strong, weak):
    weak_mask = (strength >= weak).astype(np.uint8)
    count, labels = cv2.connectedComponents(weak_mask, connectivity=8)
    seeds = np.unique(labels[(strength >= strong) & (weak_mask > 0)])
    keep = np.zeros(count, bool)
    keep[seeds] = True
    keep[0] = False
    return keep[labels]


# ---------------------------------------------------------------- thinning

def thin(mask):
    """Zhang-Suen thinning to 1-pixel centre lines (vectorised)."""
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p2 = img[:-2, 1:-1]; p3 = img[:-2, 2:]; p4 = img[1:-1, 2:]; p5 = img[2:, 2:]
            p6 = img[2:, 1:-1]; p7 = img[2:, :-2]; p8 = img[1:-1, :-2]; p9 = img[:-2, :-2]
            center = img[1:-1, 1:-1]
            neighbours = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            ring = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
            transitions = sum(((ring[i] == 0) & (ring[i + 1] == 1)).astype(np.uint8) for i in range(8))
            if step == 0:
                cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            remove = (center == 1) & (neighbours >= 2) & (neighbours <= 6) & (transitions == 1) & cond
            if remove.any():
                center[remove] = 0
                changed = True
        if not changed:
            return img[1:-1, 1:-1].astype(bool)


# ---------------------------------------------------------------- tracing

OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _neighbour_count(skel):
    s = np.pad(skel.astype(np.uint8), 1)
    total = np.zeros(skel.shape, np.uint8)
    for dy, dx in OFFSETS:
        total += s[1 + dy:1 + dy + skel.shape[0], 1 + dx:1 + dx + skel.shape[1]]
    return total


def _walk(start, pixels, visited):
    """Follow a simple chain of pixels (no junctions) from start."""
    path = [start]
    visited.add(start)
    current = start
    while True:
        y, x = current
        nxt = None
        # Prefer 4-connected steps so diagonal staircases are followed cleanly.
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            q = (y + dy, x + dx)
            if q in pixels and q not in visited:
                nxt = q
                break
        if nxt is None:
            return path
        visited.add(nxt)
        path.append(nxt)
        current = nxt


def _direction(points, from_end, span=6):
    """Unit direction leaving the stroke at one end (outward)."""
    if from_end:
        a, b = points[max(0, len(points) - 1 - span)], points[-1]
    else:
        a, b = points[min(len(points) - 1, span)], points[0]
    dy, dx = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dy, dx) or 1.
    return dy / n, dx / n


def _branches(skel):
    """Number of separate lines leaving each pixel (0->1 changes around it).

    Counting neighbours instead would mark every staircase corner of a thin
    curve as a junction and cut smooth curves into pieces.
    """
    s = np.pad(skel.astype(np.uint8), 1)
    h, w = skel.shape
    ring = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0)]
    vals = [s[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy, dx in ring]
    return sum(((vals[i] == 0) & (vals[i + 1] == 1)).astype(np.uint8) for i in range(8))


def trace(skel, spur_len):
    """Skeleton -> list of point lists (y, x), joined smoothly at junctions."""
    count = _neighbour_count(skel)
    junction = skel & (count >= 3) & (_branches(skel) >= 3)
    plain = skel & ~junction
    pixels = set(zip(*np.nonzero(plain)))
    plain_count = _neighbour_count(plain)
    visited = set()
    segments = []
    ends = [p for p in pixels if plain_count[p] <= 1]
    for p in ends:
        if p not in visited:
            segments.append(_walk(p, pixels, visited))
    for p in sorted(pixels):                       # closed loops
        if p not in visited:
            segments.append(_walk(p, pixels, visited))

    # Junction clusters and the segment ends touching each one.
    jcount, jlabels = cv2.connectedComponents(junction.astype(np.uint8), connectivity=8)
    if jcount > 1:
        ys, xs = np.nonzero(junction)
        centers = {}
        for label in range(1, jcount):
            sel = jlabels[ys, xs] == label
            centers[label] = (float(ys[sel].mean()), float(xs[sel].mean()))
        touch = {}
        H, W = skel.shape
        for index, seg in enumerate(segments):
            for at_end, (y, x) in ((False, seg[0]), (True, seg[-1])):
                for dy, dx in OFFSETS:
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < H and 0 <= xx < W and jlabels[yy, xx]:
                        touch.setdefault(int(jlabels[yy, xx]), []).append((index, at_end))
                        break
        # Drop short spurs: a short piece whose other end is free.
        attached = {(i, e) for lst in touch.values() for i, e in lst}
        dead = set()
        for index, seg in enumerate(segments):
            free_ends = [e for e in (False, True) if (index, e) not in attached]
            if len(seg) < spur_len and len(free_ends) == 1:
                dead.add(index)
        # Pair ends through each junction by smoothest continuation.
        partner = {}
        for label, lst in touch.items():
            lst = [item for item in lst if item[0] not in dead]
            options = []
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    a, b = lst[i], lst[j]
                    if a[0] == b[0] and len(segments[a[0]]) < 3 * spur_len:
                        continue
                    da = _direction(segments[a[0]], a[1])
                    db = _direction(segments[b[0]], b[1])
                    straightness = -(da[0] * db[0] + da[1] * db[1])  # 1 = straight through
                    if straightness > .35:
                        options.append((straightness, a, b))
            for _, a, b in sorted(options, reverse=True):
                if a not in partner and b not in partner:
                    partner[a] = (b, centers[label])
                    partner[b] = (a, centers[label])
        segments = [seg if i not in dead else None for i, seg in enumerate(segments)]
    else:
        partner = {}

    # Assemble chains of joined segments.
    strokes, used = [], set()

    def chain_from(index, enter_end):
        points = []
        while index is not None and index not in used:
            used.add(index)
            seg = segments[index]
            ordered = seg if not enter_end else list(reversed(seg))
            points.extend(ordered)
            exit_end = not enter_end
            link = partner.get((index, exit_end))
            if not link:
                break
            (nxt, nxt_end), center = link
            points.append(center)
            index, enter_end = nxt, nxt_end
        return points

    for index, seg in enumerate(segments):
        if seg is None or index in used:
            continue
        if (index, False) not in partner:
            strokes.append(chain_from(index, False))
        elif (index, True) not in partner:
            strokes.append(chain_from(index, True))
    for index, seg in enumerate(segments):           # remaining are loops
        if seg is not None and index not in used:
            strokes.append(chain_from(index, False))
    return [s for s in strokes if len(s) >= 2]


# ---------------------------------------------------------------- shaping

def simplify(points, epsilon):
    curve = np.array([(x, y) for y, x in points], np.float32).reshape(-1, 1, 2)
    closed = len(points) > 8 and math.dist(points[0], points[-1]) <= 2
    reduced = cv2.approxPolyDP(curve, epsilon, closed).reshape(-1, 2)
    pts = [(float(x), float(y)) for x, y in reduced]
    if closed and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def smooth(points, passes=1):
    """Chaikin corner cutting: rounder, hand-like curves."""
    for _ in range(passes):
        if len(points) < 3:
            return points
        closed = points[0] == points[-1]
        out = [points[0]] if not closed else []
        for a, b in zip(points, points[1:]):
            out.append((.75 * a[0] + .25 * b[0], .75 * a[1] + .25 * b[1]))
            out.append((.25 * a[0] + .75 * b[0], .25 * a[1] + .75 * b[1]))
        out.append(out[0] if closed else points[-1])
        points = out
    return points


def link_strokes(strokes, gap, min_alignment=.5):
    """Join stroke ends that are close and continue in the same direction.

    Candidate pairs come from a grid of cells one gap wide, so only nearby
    ends are compared. Pairs are joined greedily, closest first; joining two
    ends of the same chain (which would close it on itself) is skipped.
    """
    def heading(points, at_end):
        if at_end:
            a, b = points[max(0, len(points) - 4)], points[-1]
        else:
            a, b = points[min(len(points) - 1, 3)], points[0]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.
        return dx / n, dy / n
    strokes = [list(s) for s in strokes]
    ends = []
    for i, s in enumerate(strokes):
        if math.dist(s[0], s[-1]) > 2:
            ends.append((i, False, s[0], heading(s, False)))
            ends.append((i, True, s[-1], heading(s, True)))
    grid = {}
    for k, (_, _, p, _) in enumerate(ends):
        grid.setdefault((int(p[0] // gap), int(p[1] // gap)), []).append(k)
    pairs = []
    for k, (i, ei, pi, hi) in enumerate(ends):
        cx, cy = int(pi[0] // gap), int(pi[1] // gap)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for m in grid.get((gx, gy), ()):
                    if m <= k:
                        continue
                    j, ej, pj, hj = ends[m]
                    if i == j:
                        continue
                    d = math.dist(pi, pj)
                    if d > gap:
                        continue
                    if d > 1:
                        vx, vy = (pj[0] - pi[0]) / d, (pj[1] - pi[1]) / d
                        align = min(hi[0] * vx + hi[1] * vy, -(hj[0] * vx + hj[1] * vy))
                    else:
                        align = -(hi[0] * hj[0] + hi[1] * hj[1])
                    if align >= min_alignment:
                        pairs.append((d, (i, ei), (j, ej)))
    parent = list(range(len(strokes)))

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    partner = {}
    for _, a, b in sorted(pairs):
        if a in partner or b in partner or root(a[0]) == root(b[0]):
            continue
        partner[a], partner[b] = b, a
        parent[root(a[0])] = root(b[0])
    result, used = [], set()
    for i in range(len(strokes)):
        if i in used:
            continue
        # Start from a chain end: an end of this stroke without a partner.
        if (i, False) in partner and (i, True) in partner:
            continue
        index, enter_end, chain = i, (i, False) in partner, []
        while index is not None and index not in used:
            used.add(index)
            seg = strokes[index]
            chain.extend(seg if not enter_end else list(reversed(seg)))
            link = partner.get((index, not enter_end))
            index, enter_end = (link[0], link[1]) if link else (None, False)
        result.append(chain)
    result.extend(strokes[i] for i in range(len(strokes)) if i not in used)
    return result


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def order_strokes(outline, strokes, long_len):
    """Outline first, then long lines, then details; nearest-next with reversal."""
    ordered, cursor = [], (0., 0.)
    for tier in (outline,
                 [s for s in strokes if length(s) >= long_len],
                 [s for s in strokes if length(s) < long_len]):
        pending = list(tier)
        while pending:
            best = min([(math.dist(cursor, s[0]), i, False) for i, s in enumerate(pending)] +
                       [(math.dist(cursor, s[-1]), i, True) for i, s in enumerate(pending)])
            _, i, reverse = best
            s = pending.pop(i)
            if reverse:
                s = list(reversed(s))
            ordered.append(s)
            cursor = s[-1]
    return ordered


# ---------------------------------------------------------------- main

def importance(points, strength):
    """Length times average line strength under the stroke."""
    h, w = strength.shape
    values = [strength[min(h - 1, max(0, int(y))), min(w - 1, max(0, int(x)))]
              for x, y in points[::2]]
    return length(points) * (float(np.mean(values)) + .15)


def line_art_strokes(image, detail='medium', style='detailed'):
    """Ordered strokes as lists of (x, y) in original image pixels."""
    if style not in STYLES:
        raise ValueError('Choose the Clean or Detailed drawing style.')
    settings = DETAIL[detail]
    clean = CLEAN[detail] if style == 'clean' else None
    size_limit = clean['size'] if clean else settings['size']
    rgb, support, scale, (ox, oy) = prepare(image, size_limit)
    h, w = support.shape
    size = max(h, w)

    # Outer outline from the object's silhouette (only if there is transparency).
    outline = []
    if not support.all():
        contours, _ = cv2.findContours(support.astype(np.uint8), cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_NONE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            if cv2.contourArea(contour) < size * size * (.01 if clean else .002):
                continue
            pts = [(float(x), float(y)) for x, y in contour.reshape(-1, 2)]
            # The silhouette must stay accurate (thin parts like cords), so it
            # gets only light smoothing even in the Clean style.
            pts = smooth(simplify([(y, x) for x, y in pts], 1.0 if clean else .9), 1)
            if pts and pts[0] != pts[-1]:
                pts.append(pts[0])
            outline.append(pts)

    calm = calm_textures(rgb)
    sketch = is_sketch(rgb, support)
    if clean:
        calm = calm_textures(calm)           # calmer still: only real forms remain
    strong, weak = settings['strong'], settings['weak']
    if sketch:
        strong, weak = strong - .08, weak - .06
    if clean:
        strong, weak = strong + clean['raise_'], weak + clean['raise_']
    strength = teed_edges(calm)
    edges = hysteresis(strength, strong, weak)
    # Very confident lines from the unsmoothed image keep fine real detail
    # (speaker rings, screws) that smoothing softened; texture stays out.
    edges |= structural_detail(hysteresis(teed_edges(rgb), .85, .6), edges, size)
    ink = ink_lines(calm, support, sketch)
    if clean and sketch:
        ink = long_marks(ink, size * .08)     # contours yes, hatching marks no
    lines = (edges | ink) & support
    if outline:
        # The outline is drawn separately; remove its duplicate from the map.
        border = cv2.morphologyEx(support.astype(np.uint8), cv2.MORPH_GRADIENT,
                                  np.ones((3, 3), np.uint8))
        border = cv2.dilate(border, np.ones((5, 5), np.uint8)) > 0
        lines &= ~border
    # Bridge 1-pixel gaps, then reduce to centre lines.
    lines = cv2.morphologyEx(lines.astype(np.uint8), cv2.MORPH_CLOSE,
                             np.ones((3, 3), np.uint8)) > 0
    skeleton = thin(lines)
    spur = max(4, int(size * .006))
    traced = trace(skeleton, spur)

    min_len = size * (clean['min_len'] if clean else settings['min_len'])
    if clean and sketch:
        min_len *= 1.4      # sketches: shading fragments are short; real contours long
    traced = [[(float(x), float(y)) for y, x in pts] for pts in traced if len(pts) >= 3]
    if clean:
        # Join generously: an artist draws one long line, not many pieces.
        traced = link_strokes(traced, size * .03, min_alignment=.3)
    else:
        traced = link_strokes(traced, size * .012)
    traced = [[(y, x) for x, y in pts] for pts in traced]
    strokes = []
    for pts in traced:
        if len(pts) < 3:
            continue
        shaped = (smooth(simplify(pts, 1.6), 2) if clean else smooth(simplify(pts, .8), 1))
        size_of = length(shaped)
        closed = math.dist(shaped[0], shaped[-1]) <= 2
        loop_factor = (3. if sketch else 1.2) if clean else settings['loop_factor']
        # Tiny closed loops are usually highlight or texture outlines.
        if size_of >= min_len and not (closed and size_of < min_len * loop_factor):
            strokes.append(shaped)
    if clean:
        strokes.sort(key=lambda s: importance(s, strength), reverse=True)
        strokes = strokes[:clean['max_strokes']]
    else:
        strokes.sort(key=length, reverse=True)
        strokes = strokes[:settings['max_strokes']]
    ordered = order_strokes(outline, strokes, size * .06)
    inverse = 1. / scale
    return [[(x * inverse + ox, y * inverse + oy) for x, y in s] for s in ordered], len(outline)
