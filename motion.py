"""Where the pen is, and what it is doing, at any moment of the animation.

Used by the camera (follow the hand) and by the sound (scratch while the pen
draws, brush while it paints). It follows exactly the same timeline rules as
the renderers, but only computes the pen position, so a whole animation can be
sampled quickly. Positions are in output-frame pixels, after Artwork size.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

DRAW, PAINT, LIFT = 'draw', 'paint', 'lift'


@dataclass(frozen=True)
class PenSample:
    point: tuple | None      # output pixels, or None when there is no pen
    kind: str | None         # 'draw', 'paint', 'lift' or None


def _point_at(stroke, distance):
    if distance >= stroke.length:
        return stroke.points[-1]
    d = stroke.distances
    i = bisect.bisect_right(d, max(0., distance))
    if i >= len(stroke.points):
        return stroke.points[-1]
    a, b = stroke.points[i - 1], stroke.points[i]
    span = d[i] - d[i - 1]
    f = (distance - d[i - 1]) / span if span else 0.
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _ink_tip(drawing, stroke_progress):
    """Pen tip at a fraction of the total ink length (drawing coordinates)."""
    remaining = sum(s.length for s in drawing.strokes) * max(0., min(1., stroke_progress))
    tip = None
    for stroke in drawing.strokes:
        if not stroke.points:
            continue
        if remaining <= stroke.length:
            return _point_at(stroke, remaining)
        remaining -= stroke.length
        tip = stroke.points[-1]
    return tip


def _to_canvas(drawing, point, width, height):
    x0, y0, x1, y1 = drawing.bounds
    scale = min(width * .82 / max(1., x1 - x0), height * .78 / max(1., y1 - y0))
    ox = (width - (x1 - x0) * scale) / 2 - x0 * scale
    oy = (height - (y1 - y0) * scale) / 2 - y0 * scale
    return (point[0] * scale + ox, point[1] * scale + oy)


def _drawing_pen(drawing, fraction, width, height):
    """Pen during the drawing phase."""
    fraction = max(0., min(1., float(fraction)))
    if fraction <= 0 or fraction >= 1 or not drawing.strokes:
        return PenSample(None, None)
    kind = getattr(drawing, 'source_kind', None)
    if kind == 'font' and getattr(drawing, 'font_ink', None) is not None:
        from font_stroke_reveal import _pen_state
        point, down, _ = _pen_state(drawing, fraction)
        iw, ih = drawing.font_ink.size
        scale = min(width * .82 / max(1, iw), height * .78 / max(1, ih))
        ox, oy = (width - iw * scale) / 2, (height - ih * scale) / 2
        return PenSample((ox + point[0] * scale, oy + point[1] * scale), DRAW if down else LIFT)
    if kind == 'image':
        from image_drawing import drawing_state
        state = drawing_state(drawing, fraction)
        if state.painting:
            tip = _ink_tip(drawing, state.stroke_progress)
            return PenSample(_to_canvas(drawing, tip, width, height) if tip else None, DRAW)
        if state.lift_point is not None:
            return PenSample(_to_canvas(drawing, state.lift_point, width, height), LIFT)
        return PenSample(None, None)
    tip = _ink_tip(drawing, fraction)
    return PenSample(_to_canvas(drawing, tip, width, height) if tip else None, DRAW)


def _plan_pen(drawing, image, progress, width, height, brush_width, stroke_spacing):
    """Pen while painting with a brush plan (Adaptive or Zigzag)."""
    from adaptive_hand import plan_for
    from color_reveal import artwork_rect
    try:
        plan = plan_for(drawing, image, brush_width, stroke_spacing)
    except Exception:
        return PenSample(None, PAINT)
    segment, tip = plan.state(progress)
    if tip is None:
        return PenSample(None, None)
    rect = artwork_rect(drawing, image, width, height)
    point = (rect.x() + tip[0] * rect.width() / plan.size[0],
             rect.y() + tip[1] * rect.height() / plan.size[1])
    return PenSample(point, PAINT if segment.painting else LIFT)


ERASE = 'erase'


def strokes_on_canvas(drawing, width, height, artwork_scale=1.0):
    """Every stroke's points in output pixels (after Artwork size), in drawing order."""
    cx, cy = width / 2, height / 2
    font = getattr(drawing, 'source_kind', None) == 'font' and getattr(drawing, 'font_ink', None) is not None
    if font:
        iw, ih = drawing.font_ink.size
        scale = min(width * .82 / max(1, iw), height * .78 / max(1, ih))
        ox, oy = (width - iw * scale) / 2, (height - ih * scale) / 2
        to = lambda p: (ox + p[0] * scale, oy + p[1] * scale)
    else:
        to = lambda p: _to_canvas(drawing, p, width, height)
    out = []
    for stroke in drawing.strokes:
        pts = [to(p) for p in stroke.points]
        out.append([(cx + (x - cx) * artwork_scale, cy + (y - cy) * artwork_scale) for x, y in pts])
    return out


def pen_at(drawing, fraction, width=1920, height=1080, duration=4, fade_duration=.4,
           hold_duration=.6, final_image=None, reveal_mode='adaptive', brush_width=.14,
           stroke_spacing=.55, artwork_scale=1.0, erase=None, **_ignored):
    """The pen at a timeline position 0..1 (same rules as render_color_timeline)."""
    if erase and erase.get('mode'):
        from frame_render import erase_setup, split_erase
        options = dict(width=width, height=height, duration=duration, fade_duration=fade_duration,
                       hold_duration=hold_duration, final_image=final_image, reveal_mode=reveal_mode,
                       brush_width=brush_width, stroke_spacing=stroke_spacing,
                       artwork_scale=artwork_scale, erase=erase, **_ignored)
        opts, erase, base_fraction, progress = split_erase(drawing, fraction, options)
        if progress is not None:
            _, plan = erase_setup(drawing, opts, erase)
            point, rubbing = plan.state(progress)
            return PenSample(point, ERASE if rubbing else (LIFT if point else None))
        fraction = base_fraction
    sample = _pen_canvas(drawing, fraction, width, height, duration, fade_duration, hold_duration,
                         final_image, reveal_mode, brush_width, stroke_spacing)
    if sample.point is None or abs(artwork_scale - 1.) < 1e-9:
        return sample
    cx, cy = width / 2, height / 2
    x, y = sample.point
    return PenSample((cx + (x - cx) * artwork_scale, cy + (y - cy) * artwork_scale), sample.kind)


def _pen_canvas(drawing, fraction, width, height, duration, fade_duration, hold_duration,
                final_image, reveal_mode, brush_width, stroke_spacing):
    from color_reveal import timeline_duration, timeline_state
    fraction = max(0., min(1., float(fraction)))
    if final_image is None or final_image.isNull():
        return _drawing_pen(drawing, fraction, width, height)
    if reveal_mode in ('adaptive', 'zigzag'):
        drawing.paint_method = reveal_mode
        reveal_mode = 'adaptive'
    animation = getattr(drawing, 'image_animation', None)
    if getattr(drawing, 'source_kind', None) == 'image' and animation in ('draw_paint', 'paint_only'):
        if animation == 'paint_only':
            paint_length = max(.001, float(fade_duration))
            elapsed = fraction * (paint_length + max(0., float(hold_duration)))
            return _plan_pen(drawing, final_image, min(1., elapsed / paint_length), width, height,
                             brush_width, stroke_spacing)
        total = timeline_duration(duration, final_image, fade_duration, hold_duration)
        elapsed = fraction * total
        stroke_progress, paint_progress = timeline_state(elapsed, duration, fade_duration)
        if elapsed < max(.001, float(duration)):
            return _drawing_pen(drawing, stroke_progress, width, height)
        if paint_progress <= 0 or paint_progress >= 1:
            return PenSample(None, None)
        return _plan_pen(drawing, final_image, paint_progress, width, height, brush_width,
                         stroke_spacing)
    total = timeline_duration(duration, final_image, fade_duration, hold_duration)
    elapsed = fraction * total
    stroke_progress, reveal_progress = timeline_state(elapsed, duration, fade_duration)
    if elapsed < duration:
        return _drawing_pen(drawing, stroke_progress, width, height)
    if reveal_progress <= 0 or reveal_progress >= 1:
        return PenSample(None, None)
    if reveal_mode == 'adaptive' and getattr(drawing, 'contour_transition', 'legacy') == 'legacy':
        return _plan_pen(drawing, final_image, reveal_progress, width, height, brush_width,
                         stroke_spacing)
    return PenSample(None, PAINT)                 # other painting modes: no tracked position


def track(drawing, options, total_seconds, rate=30.):
    """[(time_s, PenSample)] sampled `rate` times a second over the animation."""
    count = max(2, int(math.ceil(total_seconds * rate)) + 1)
    return [((i / (count - 1)) * total_seconds, pen_at(drawing, i / (count - 1), **options))
            for i in range(count)]
