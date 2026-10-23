"""Painter: a paint mode that works the way a person paints a picture.

* Real parts: the picture is split into its parts (AI parts when available, else
  colour areas; image sources use their own regions). Crumbs are merged into a
  neighbour, so the hand does not hop around tiny patches.
* Human order: big parts first, then medium parts, details last; inside each
  size the hand goes on to the nearest part.
* Strokes that follow the shape: each part is painted around its form, from its
  edge inwards (like brushing along the outline, then filling towards the middle),
  instead of a straight back-and-forth scan.

The result is the same timed plan as Adaptive (adaptive_hand.PaintPlan), so the
renderer, the hand, the guide removal and the sound work unchanged.
"""
from __future__ import annotations

import math

TIERS = (.06, .008)          # share of the picture: big parts, medium parts, then details
CRUMB = .002                 # parts smaller than this share are merged into a neighbour


def _grid(drawing, image, source):
    from adaptive_hand import GRID_LIMIT, VISIBLE_ALPHA
    from color_reveal import artwork_rect, last_stroke_canvas_endpoint
    iw, ih = source.size
    ratio = min(1., GRID_LIMIT / max(iw, ih))
    gw, gh = max(1, math.ceil(iw * ratio)), max(1, math.ceil(ih * ratio))
    rect = artwork_rect(drawing, image, 1920, 1080)
    end = last_stroke_canvas_endpoint(drawing, 1920, 1080) if drawing.strokes else (rect.x(), rect.y())
    origin = ((end[0] - rect.x()) * gw / rect.width(), (end[1] - rect.y()) * gh / rect.height())
    support = bytearray(gw * gh); faint = bytearray(gw * gh)
    for i, a in enumerate(source.getchannel('A').tobytes()):
        if a:
            cell = min(gh - 1, (2 * (i // iw) + 1) * gh // (2 * ih)) * gw + min(gw - 1, (2 * (i % iw) + 1) * gw // (2 * iw))
            if a >= VISIBLE_ALPHA:
                support[cell] = 1
            else:
                faint[cell] = 1
    if not any(support):
        if not any(faint):
            raise ValueError('The color image has no nontransparent pixels.')
        support, faint = faint, bytearray(gw * gh)
    return gw, gh, origin, support, faint


def part_labels(drawing, source, support, gw, gh):
    """One label per grid cell (0 = nothing to paint): the picture's parts."""
    import numpy as np
    from PIL import Image
    found = getattr(drawing, 'ai_parts_image', None)            # AI parts (ai_parts.py), when found
    if found is not None:
        from ai_parts import regions_of
        ids = regions_of(found, (gw, gh))
    else:
        parts = getattr(drawing, 'image_regions', None)
        if parts is None:
            from image_regions import segment_regions
            parts = segment_regions(source, 'medium')
        ids = parts.labels
        if tuple(parts.size) != (gw, gh):
            im = Image.new('I', tuple(parts.size)); im.putdata(list(parts.labels))
            ids = list(im.resize((gw, gh), Image.Resampling.NEAREST).getdata())
    raw = np.asarray(ids, np.int32).reshape(gh, gw)
    sup = np.asarray(support, np.uint8).reshape(gh, gw) > 0
    raw = np.where(sup, np.where(raw > 0, raw, 1), 0)
    return _merge_crumbs(_split_pieces(raw), sup)


def apply_circles(labels, circles):
    """Parts circled in the Line order window (Painting): everything inside a circle becomes
    one part of its own, cut out of whatever parts it covers (a shoulder no longer pulls
    the wall behind it along). circles: [[(x, y), ...] as fractions of the picture], in
    order; a place inside two circles belongs to the first. Returns (labels, circle ids)."""
    import numpy as np
    from PIL import Image, ImageDraw
    if not circles:
        return labels, []
    gh, gw = labels.shape
    out = labels.copy()
    taken = np.zeros(labels.shape, bool)
    base = int(labels.max()) + 1
    ids = []
    for k, poly in enumerate(circles):
        if len(poly) < 3:
            continue
        mask = Image.new('L', (gw, gh), 0)
        ImageDraw.Draw(mask).polygon([(x * gw, y * gh) for x, y in poly], fill=1)
        inside = (np.asarray(mask) > 0) & (labels > 0) & ~taken
        if not inside.any():
            continue
        rid = base + k
        out[inside] = rid
        taken |= inside
        ids.append(rid)
    return out, ids


def labels_for(drawing, source, support, gw, gh, circles=None):
    """The parts Painter paints, with the circled parts cut in: (labels, circle ids)."""
    labels = part_labels(drawing, source, support, gw, gh)
    if circles is None:
        circles = getattr(drawing, 'paint_circles', None)
    return apply_circles(labels, circles)


def _split_pieces(raw):
    """Each connected piece of a part is painted on its own."""
    import cv2
    import numpy as np
    out = np.zeros_like(raw); next_id = 1
    for rid in np.unique(raw):
        if rid == 0:
            continue
        n, comp = cv2.connectedComponents((raw == rid).astype(np.uint8), connectivity=4)
        for c in range(1, n):
            out[comp == c] = next_id; next_id += 1
    return out


def _merge_crumbs(labels, support):
    """Tiny pieces join the neighbouring part they share the longest edge with."""
    import numpy as np
    painted = int(support.sum())
    limit = max(6, int(CRUMB * painted))
    for _ in range(4):
        ids, counts = np.unique(labels[labels > 0], return_counts=True)
        small = [int(i) for i, n in zip(ids, counts) if n < limit]
        if not small:
            break
        changed = False
        for rid in sorted(small, key=lambda r: int((labels == r).sum())):
            mask = labels == rid
            if not mask.any():
                continue
            ring = np.zeros_like(mask)
            ring[1:, :] |= mask[:-1, :]; ring[:-1, :] |= mask[1:, :]
            ring[:, 1:] |= mask[:, :-1]; ring[:, :-1] |= mask[:, 1:]
            neighbours = labels[ring & ~mask]
            neighbours = neighbours[(neighbours > 0) & (neighbours != rid)]
            if neighbours.size:
                best = np.bincount(neighbours).argmax()
                labels[mask] = best; changed = True
        if not changed:
            break
    # Renumber 1..n.
    out = np.zeros_like(labels)
    for new, rid in enumerate([int(i) for i in np.unique(labels) if i > 0], 1):
        out[labels == rid] = new
    return out


def part_order(labels, origin, custom=None):
    """Big parts first, then medium, details last; nearest next within each size.

    custom: the order chosen in the Line order window (Painting), as part ids; parts
    it does not name follow in the default order."""
    import numpy as np
    painted = max(1, int((labels > 0).sum()))
    info = []
    for rid in [int(i) for i in np.unique(labels) if i > 0]:
        ys, xs = np.nonzero(labels == rid)
        share = len(xs) / painted
        tier = 0 if share >= TIERS[0] else (1 if share >= TIERS[1] else 2)
        info.append((rid, tier, (float(xs.mean()) + .5, float(ys.mean()) + .5)))
    order, cursor = [], origin
    if custom:
        known = {p[0] for p in info}
        first = [int(r) for r in custom if int(r) in known]
        chosen = set(first)
        rest = part_order(labels, origin) if len(chosen) < len(known) else []
        return first + [r for r in rest if r not in chosen]
    for tier in (0, 1, 2):
        left = [p for p in info if p[1] == tier]
        while left:
            nxt = min(left, key=lambda p: math.dist(cursor, p[2]))
            left.remove(nxt); order.append(nxt[0]); cursor = nxt[2]
    return order


def shape_strokes(mask, gap):
    """Strokes around the part's form, from its edge inwards: [[(x, y), ...], ...].

    Level k follows the outline of the part shrunk by k * gap (distance inside the
    part), so the brush goes along the shape, ring after ring."""
    import cv2
    import numpy as np
    depth = cv2.distanceTransform(np.pad(mask.astype(np.uint8), 1), cv2.DIST_L2, 3)[1:-1, 1:-1]
    strokes = []
    k = 0
    while True:
        level = (depth > k * gap).astype(np.uint8)
        if not level.any():
            break
        contours, _ = cv2.findContours(level, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for c in sorted(contours, key=lambda c: -len(c)):
            pts = [(float(p[0][0]) + .5, float(p[0][1]) + .5) for p in c]
            if len(pts) > 3:
                pts = pts[::2] + [pts[0]]            # every other cell; closed around the shape
            strokes.append(pts if len(strokes) % 2 == 0 else pts[::-1])
        k += 1
    return strokes


def build_painter_plan(drawing, image, brush_width=.14, stroke_spacing=.55):
    import numpy as np
    from adaptive_hand import PaintPlan, Segment, _reveal_faint_with_neighbours, pil_image
    source = pil_image(image)
    gw, gh, origin, support, faint = _grid(drawing, image, source)
    grid, circled = labels_for(drawing, source, support, gw, gh)
    labels = [int(v) for v in grid.ravel()]
    maximum = max(.72, gw * max(.02, min(.5, float(brush_width))) / 2)
    spacing = max(.2, min(.9, float(stroke_spacing)))
    gap = max(1., 2 * maximum * spacing)
    radius = max(.9, gap * .75)
    arrival = [float('inf')] * len(labels)
    segments = []
    clock = 0.
    cursor = origin

    def stamp(point, rid, when):
        x, y = point
        for yy in range(max(0, math.floor(y - radius)), min(gh, math.ceil(y + radius))):
            for xx in range(max(0, math.floor(x - radius)), min(gw, math.ceil(x + radius))):
                cell = yy * gw + xx
                if labels[cell] == rid and (xx + .5 - x) ** 2 + (yy + .5 - y) ** 2 <= radius * radius \
                        and when < arrival[cell]:
                    arrival[cell] = when

    def move(point, rid, painting):
        nonlocal clock, cursor
        distance = math.dist(cursor, point)
        duration = max(.05, distance) if painting else max(.4, min(10., distance * .18))
        segments.append(Segment(cursor, point, radius, rid, painting, clock, clock + duration))
        if painting:
            steps = max(1, math.ceil(distance / max(.35, radius * .5)))
            for j in range(steps + 1):
                f = j / steps
                stamp((cursor[0] + (point[0] - cursor[0]) * f, cursor[1] + (point[1] - cursor[1]) * f),
                      rid, clock + duration * f)
        clock += duration; cursor = point

    for rid in part_order(grid, origin, getattr(drawing, 'paint_part_order', None) or circled):
        mask = grid == rid
        for stroke in shape_strokes(mask, gap):
            # Start each stroke at its end nearer to the hand.
            if math.dist(cursor, stroke[-1]) < math.dist(cursor, stroke[0]):
                stroke = stroke[::-1]
            far = math.dist(cursor, stroke[0])
            move(stroke[0], rid, far <= radius * 2)           # a short step keeps painting; else lift
            for point in stroke[1:]:
                move(point, rid, True)
        # Anything the rings missed: small dabs, nearest first.
        cells = np.flatnonzero(mask.ravel())
        missing = [int(c) for c in cells if not math.isfinite(arrival[int(c)])]
        while missing:
            target = min(missing, key=lambda c: math.dist(cursor, (c % gw + .5, c // gw + .5)))
            point = (target % gw + .5, target // gw + .5)
            move(point, rid, math.dist(cursor, point) <= radius * 3)
            if not math.isfinite(arrival[target]):
                stamp(point, rid, clock)
            missing = [c for c in missing if not math.isfinite(arrival[c])]
    _reveal_faint_with_neighbours(arrival, labels, faint, gw, gh)
    return PaintPlan((gw, gh), labels, segments, [s.end for s in segments], arrival,
                     origin, clock, [], int(grid.max()))


def parts_for_window(drawing, image, circles=None):
    """What the Line order window (Painting) needs: (grid labels, default order, centres, circle ids).

    grid: numpy array of part ids (0 = nothing), the same parts Painter paints;
    circles: the circled parts to cut in (None: the element's own)."""
    from adaptive_hand import pil_image
    source = pil_image(image)
    gw, gh, origin, support, faint = _grid(drawing, image, source)
    grid, circled = labels_for(drawing, source, support, gw, gh, circles)
    import numpy as np
    import cv2
    centres = {}
    for rid in [int(i) for i in np.unique(grid) if i > 0]:
        mask = (grid == rid).astype(np.uint8)
        # A point well inside the part (the farthest from its edge), not its average:
        # the average of a wall around people falls on the people (exp.101).
        depth = cv2.distanceTransform(np.pad(mask, 1), cv2.DIST_L2, 3)[1:-1, 1:-1]
        y, x = np.unravel_index(int(depth.argmax()), depth.shape)
        centres[rid] = (float(x) + .5, float(y) + .5, int(mask.sum()))
    return grid, part_order(grid, origin), centres, circled
