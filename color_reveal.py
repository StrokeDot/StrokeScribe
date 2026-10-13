"""Optional SVG-stroke to original-color artwork transition.

The imported PNG remains intact. Transparent outer margins are cropped once
to align the visible artwork with the SVG's drawing bounds.
"""
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter
from engine import render


def load_color_image(filename):
    """Load a PNG; trim transparent outside margins but do not alter its colors."""
    filename = Path(filename)
    with Image.open(filename) as im:
        if im.format != 'PNG':
            raise ValueError('Choose a PNG image (preferably with transparency).')
        alpha = im.convert('RGBA').getchannel('A')
        bbox = alpha.point(lambda value: 255 if value >= 8 else 0).getbbox()
        if bbox is None:
            raise ValueError('The PNG contains no visible artwork.')
    qimage = QImage(str(filename))
    if qimage.isNull():
        raise ValueError('Could not load the PNG file.')
    left, top, right, bottom = bbox
    return qimage.copy(left, top, right - left, bottom - top)


def timeline_duration(draw_duration, final_image=None, fade_duration=0.4, hold_duration=0.6):
    base = max(0.001, float(draw_duration))
    if final_image is None or final_image.isNull():
        return base
    return base + max(0.0, float(fade_duration)) + max(0.0, float(hold_duration))


def timeline_state(seconds, draw_duration, fade_duration):
    """Return (stroke completion, color opacity) for elapsed seconds."""
    seconds = max(0.0, float(seconds))
    draw_duration = max(0.001, float(draw_duration))
    fade_duration = max(0.0, float(fade_duration))
    if seconds <= draw_duration:
        return min(1.0, seconds / draw_duration), 0.0
    if fade_duration == 0:
        return 1.0, 1.0
    return 1.0, min(1.0, (seconds - draw_duration) / fade_duration)


def render_color_timeline(drawing, fraction, width=1920, height=1080,
                          duration=4, fade_duration=0.4, hold_duration=0.6,
                          final_image=None, thickness=1.0, hand=None,
                          hand_scale=0.18, anchor=(0.1, 0.1)):
    """Draw strokes, crossfade to the original PNG, then hold the final image."""
    if final_image is None or final_image.isNull():
        return render(drawing, fraction, width, height, thickness, hand, hand_scale, anchor)

    total = timeline_duration(duration, final_image, fade_duration, hold_duration)
    elapsed = min(1.0, max(0.0, float(fraction))) * total
    progress, opacity = timeline_state(elapsed, duration, fade_duration)
    strokes = render(drawing, progress, width, height, thickness, hand, hand_scale, anchor)
    if opacity == 0:
        return strokes

    canvas = QImage(width, height, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(1.0 - opacity)
    painter.drawImage(0, 0, strokes)
    painter.setOpacity(opacity)

    x0, y0, x1, y1 = drawing.bounds
    svg_width = max(1.0, x1 - x0)
    svg_height = max(1.0, y1 - y0)
    scale = min(width * 0.82 / svg_width, height * 0.78 / svg_height)
    target_width = svg_width * scale
    target_height = svg_height * scale
    fit_scale = min(target_width / final_image.width(), target_height / final_image.height())
    art_width = final_image.width() * fit_scale
    art_height = final_image.height() * fit_scale
    painter.drawImage(QRectF((width - art_width) / 2, (height - art_height) / 2,
                             art_width, art_height), final_image)
    painter.end()
    return canvas
