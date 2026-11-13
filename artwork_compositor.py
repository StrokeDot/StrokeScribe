"""Artwork-only scene compositing; hands are always drawn with SourceOver.

The renderer can produce the artwork and hand separately through its existing
"art" / "hand" layer modes. Do not blend a combined frame: Qt's Multiply,
Screen, etc. would also color-shift the moving pencil or paint brush.
"""
from __future__ import annotations


def bounded_opacity(value):
    """Legacy projects have no opacity key: keep their original 100% artwork."""
    try:
        return max(0.0, min(1.0, float(value) / 100.0))
    except (ValueError, TypeError):
        return 1.0


def composite_element(base, drawing, fraction, options, camera_path=None):
    """Compose earlier artwork -> this artwork -> unmodified moving hand.

    When compositing a page of overlapping elements, scene artwork must be
    rendered without its hand. The separate hand-only pass keeps the same
    timings, positions, and camera transformations. Other source images and
    project settings are never mutated.
    """
    from PySide6.QtGui import QImage
    from frame_render import _compose_raw_frame
    from scenes import stack

    from frame_render import _set_spec, last_hand_spec, paint_hand_spec
    layers = options.get('layers', 'all')
    _set_spec(None)
    if layers == 'hand':
        return paint_hand_spec(_compose_raw_frame(drawing, fraction, options, camera_path), last_hand_spec(), options)
    art_opts = dict(options, layers='art', ghost=0)
    artwork = _compose_raw_frame(drawing, fraction, art_opts, camera_path)
    if base is None:
        base = QImage(artwork.size(), QImage.Format.Format_ARGB32_Premultiplied)
        base.fill(0)
    result = stack(base, artwork, options.get('blend_mode', 'Normal'),
                   options.get('artwork_opacity', 100))
    if layers == 'all':
        hand_opts = dict(options, layers='hand', ghost=0, background=False)
        hand = _compose_raw_frame(drawing, fraction, hand_opts, camera_path)
        result = stack(result, hand, 'Normal', 100)
        # exp.149: the drawing hand on top, at its own size (whatever the camera's zoom)
        result = paint_hand_spec(result, last_hand_spec(), options)
    return result
