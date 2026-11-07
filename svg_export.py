"""Save a StrokeScribe drawing as an editable SVG plus its matching colour PNG.

The SVG uses smooth cubic curves (open in Inkscape and edit any line), keeps
the drawing order, and names every path. Re-import it with SVG source +
"Load matching colored PNG..." using the PNG saved next to it.

The frame (data-strokescribe-frame on the <svg> element) records the exact
image area, so the colour PNG lines up perfectly on re-import even when the
lines do not reach the image edges.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

ALPHA_VISIBLE = 8   # same threshold the app uses when loading a colour PNG


def _num(value):
    text = f'{value:.2f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def path_data(points):
    """Smooth cubic Bézier path through the points (Catmull-Rom)."""
    pts = [points[0]] + [p for a, p in zip(points, points[1:]) if math.dist(a, p) > 1e-6]
    if len(pts) < 2:
        return ''
    closed = len(pts) > 3 and math.dist(pts[0], pts[-1]) <= 1e-3
    out = [f'M{_num(pts[0][0])} {_num(pts[0][1])}']
    if len(pts) == 2:
        out.append(f'L{_num(pts[1][0])} {_num(pts[1][1])}')
        return ' '.join(out)
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else (pts[-2] if closed else pts[0])
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else (pts[1] if closed else pts[-1])
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        out.append('C' + ' '.join(_num(v) for v in (*c1, *c2, *p2)))
    if closed:
        out.append('Z')
    return ' '.join(out)


def _slug(name, index):
    text = re.sub(r'[^A-Za-z0-9_-]+', '-', name).strip('-').lower() or 'stroke'
    return f'{index:03d}-{text}'


def svg_document(strokes, width, height, color='#303946', stroke_width=None, title='StrokeScribe drawing'):
    """SVG text for strokes [(name, points)] in a width x height frame."""
    stroke_width = stroke_width or max(width, height) * .0025
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_num(width)}" height="{_num(height)}" viewBox="0 0 {_num(width)} {_num(height)}" '
        f'data-strokescribe-frame="0 0 {_num(width)} {_num(height)}">',
        f' <title>{title}</title>',
        ' <desc>Exported by StrokeScribe. Paths are in drawing order; edit or delete any '
        'line, then re-import with SVG source and the matching colour PNG.</desc>',
        f' <g fill="none" stroke={quoteattr(color)} stroke-width="{_num(stroke_width)}" '
        'stroke-linecap="round" stroke-linejoin="round">',
    ]
    for index, item in enumerate(strokes, 1):
        name, points = item[0], item[1]
        data = path_data(points)
        if not data:
            continue
        style = ''
        if len(item) >= 4 and item[2] and item[2].lower() != color.lower():
            # Layered drawings keep each layer's colour and line weight.
            style = f' stroke={quoteattr(item[2])} stroke-width="{_num(item[3])}"'
        lines.append(f'  <path id={quoteattr(_slug(name, index))}{style} d={quoteattr(data)}/>')
    lines += [' </g>', '</svg>', '']
    return '\n'.join(lines)


def visible_box(image):
    """Box of pixels the app treats as visible when loading a colour PNG."""
    box = image.getchannel('A').point(lambda a: 255 if a >= ALPHA_VISIBLE else 0).getbbox()
    return box or (0, 0, image.width, image.height)


def export_drawing(strokes, image, folder, stem):
    """Write <stem>.svg and <stem>_color.png; return both paths.

    strokes: [(name, points)] or [(name, points, color, width)] in the image's
    pixel coordinates.
    image: the PIL RGBA image the strokes were drawn from.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = visible_box(image)
    shifted = [(item[0], [(x - left, y - top) for x, y in item[1]], *item[2:]) for item in strokes]
    svg_path = folder / f'{stem}.svg'
    png_path = folder / f'{stem}_color.png'
    svg_path.write_text(svg_document(shifted, right - left, bottom - top,
                                     stroke_width=max(image.size) * .0025,
                                     title=f'{stem} — StrokeScribe line drawing'),
                        encoding='utf-8')
    image.crop((left, top, right, bottom)).save(png_path)
    return svg_path, png_path
