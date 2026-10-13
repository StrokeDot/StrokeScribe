"""SVG-contour-guided color reveal for StrokeScribe.

Uses a low-resolution travel-time field seeded along vector strokes. Color
spreads from those lines while the optional hand follows the vector route.
No neural model or additional third-party package is needed.
"""
from __future__ import annotations

import heapq
import math
from collections import OrderedDict

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

_CACHE = OrderedDict()
_NEIGHBORS = ((1, 0, 1.), (-1, 0, 1.), (0, 1, 1.), (0, -1, 1.),
              (1, 1, 1.4142), (1, -1, 1.4142),
              (-1, 1, 1.4142), (-1, -1, 1.4142))


def project(drawing, width, height, point):
    x0, y0, x1, y1 = drawing.bounds
    scale = min(width * .82 / max(1., x1-x0), height * .78 / max(1., y1-y0))
    ox = (width - (x1-x0)*scale)/2 - x0*scale
    oy = (height - (y1-y0)*scale)/2 - y0*scale
    return point[0]*scale + ox, point[1]*scale + oy


def guided_route(drawing, width, height):
    """Start at the last stroke's end; then follow nearby SVG paths.

    Transfers between disconnected strokes are hand travel, not paint.
    A route entry holds (x, y, paints_from_previous).
    """
    if not drawing.strokes:
        raise ValueError("SVG drawing has no strokes.")
    last = drawing.strokes[-1]
    ordered = [list(reversed(last.points))]
    cursor = last.points[0]
    remaining = list(drawing.strokes[:-1])
    while remaining:
        choice = min(
            ((math.dist(cursor, s.points[-1] if reverse else s.points[0]),
              index, reverse)
             for index, s in enumerate(remaining) for reverse in (False, True)),
            key=lambda item: item[0])
        _, index, reverse = choice
        selected = remaining.pop(index)
        points = list(reversed(selected.points)) if reverse else selected.points
        ordered.append(points)
        cursor = points[-1]
    route = []
    for points in ordered:
        # The SVG importer samples curves very densely. The low-res mask needs
        # only one vertex every ~3 canvas pixels, avoiding expensive work.
        samples = [project(drawing, width, height, p) for p in points]
        reduced = [samples[0]]
        for p in samples[1:-1]:
            if math.dist(reduced[-1], p) >= 3:
                reduced.append(p)
        if samples[-1] != reduced[-1]:
            reduced.append(samples[-1])
        if not route:
            route.append((reduced[0][0], reduced[0][1], False))
        elif math.dist(route[-1][:2], reduced[0]) > .01:
            route.append((reduced[0][0], reduced[0][1], False))
        for p in reduced[1:]:
            if math.dist(route[-1][:2], p) > .01:
                route.append((p[0], p[1], True))
    return route


def guided_hand_tip(route, progress):
    """Hand stays on the current stroke or travels to the next SVG contour."""
    if not route:
        return None
    lengths = [math.dist(route[i-1][:2], route[i][:2])
               for i in range(1, len(route))]
    remaining = max(0., min(1., progress)) * sum(lengths)
    for i, length in enumerate(lengths, 1):
        if remaining <= length:
            a, b = route[i-1], route[i]
            fraction = remaining / length if length else 0.
            return (a[0] + (b[0]-a[0])*fraction,
                    a[1] + (b[1]-a[1])*fraction)
        remaining -= length
    return route[-1][:2]


def _timing_field(drawing, width, height, rect, brush_width):
    """Build a low-resolution spatial wavefront around SVG stroke segments."""
    gw = 260
    gh = max(48, min(350, round(gw * rect.height() / max(1., rect.width()))))
    route = guided_route(drawing, width, height)
    distances = [math.dist(route[i-1][:2], route[i][:2])
                 for i in range(1, len(route))]
    total_length = max(.001, sum(distances))
    field = [float("inf")] * (gw*gh)
    heap = []

    def seed(px, py, tick):
        cx = max(0, min(gw-1, round((px-rect.left())*gw/rect.width()-.5)))
        cy = max(0, min(gh-1, round((py-rect.top())*gh/rect.height()-.5)))
        pos = cy*gw + cx
        if tick < field[pos]:
            field[pos] = tick
            heapq.heappush(heap, (tick, pos))

    seed(*route[0][:2], 0.)
    distance_so_far = 0.
    for i, distance in enumerate(distances, 1):
        if route[i][2]:
            start, end = route[i-1], route[i]
            count = max(1, math.ceil(distance/(rect.width()/gw)))
            for k in range(count+1):
                fraction = k/count
                seed(start[0]+(end[0]-start[0])*fraction,
                     start[1]+(end[1]-start[1])*fraction,
                     .78*(distance_so_far+distance*fraction)/total_length)
        distance_so_far += distance

    # Spreading outwards from the drawn contours fills broad interior regions,
    # rather than wiping the rectangular frame with vertical stripes.
    spread = .22 / max(2., min(gw, gh) * max(.02, min(.5, brush_width)))
    while heap:
        tick, at = heapq.heappop(heap)
        if tick > field[at] + 1e-10:
            continue
        x, y = at % gw, at // gw
        for dx, dy, length in _NEIGHBORS:
            xx, yy = x + dx, y + dy
            if not (0 <= xx < gw and 0 <= yy < gh):
                continue
            index = yy*gw+xx
            new_tick = tick + spread*length
            if new_tick < field[index]:
                field[index] = new_tick
                heapq.heappush(heap, (new_tick, index))
    max_tick = max(field)
    if max_tick <= 0 or not math.isfinite(max_tick):
        max_tick = 1.
    data = bytes(max(0, min(254, round(254*tick/max_tick))) for tick in field)
    return gw, gh, data, route


def _cached_field(drawing, width, height, rect, brush_width):
    # Order is part of the key, so Move Up/Down updates the painting path.
    strokes = tuple((id(s), len(s.points), s.points[0], s.points[-1])
                    for s in drawing.strokes)
    key = (strokes, width, height, round(rect.x(), 2), round(rect.y(), 2),
           round(rect.width(), 2), round(rect.height(), 2), round(brush_width, 3))
    if key not in _CACHE:
        _CACHE[key] = _timing_field(drawing, width, height, rect, brush_width)
        if len(_CACHE) > 3:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return _CACHE[key]


def guided_paint_mask(drawing, width, height, rect, progress, brush_width):
    """Make the color reveal mask and return the optional hand position."""
    progress = max(0., min(1., progress))
    canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    if progress >= 1.:
        painter = QPainter(canvas)
        painter.fillRect(rect, Qt.GlobalColor.white)
        painter.end()
        return canvas, None
    gw, gh, field, route = _cached_field(drawing, width, height, rect, brush_width)
    tip = guided_hand_tip(route, progress)
    if progress <= 0.:
        return canvas, tip
    threshold = progress * 254.
    # Soft edge, not an all-at-once opacity fade.
    lut = [max(0, min(255, round((threshold - value + 4)*255/8)))
           for value in range(256)]
    alpha = Image.frombytes('L', (gw, gh), field).point(lut)
    rgba = Image.new('RGBA', (gw, gh), (255, 255, 255, 0))
    rgba.putalpha(alpha)
    pixels = rgba.tobytes()
    small = QImage(pixels, gw, gh, gw*4, QImage.Format.Format_RGBA8888).copy()
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(rect, small)
    painter.end()
    return canvas, tip
