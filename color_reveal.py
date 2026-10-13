"""Final color artwork reveal for SVG pen animations.

The SVG determines the drawing movement; the original PNG supplies final color.
Brush painting uses an alpha mask, never raster-to-SVG quantization.
"""
import math
from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor
from engine import render


def load_color_image(filename):
    """Load a PNG without changing its colors; crop only transparent margins."""
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


def timeline_duration(draw_duration, final_image=None, fade_duration=.4, hold_duration=.6):
    base = max(.001, float(draw_duration))
    if final_image is None or final_image.isNull():
        return base
    return base + max(0., float(fade_duration)) + max(0., float(hold_duration))


def timeline_state(seconds, draw_duration, fade_duration):
    """Backward-compatible stroke progress and reveal progress calculation."""
    seconds = max(0., float(seconds))
    draw_duration = max(.001, float(draw_duration))
    fade_duration = max(0., float(fade_duration))
    if seconds <= draw_duration:
        return min(1., seconds / draw_duration), 0.
    if fade_duration == 0:
        return 1., 1.
    return 1., min(1., (seconds - draw_duration) / fade_duration)


def artwork_rect(drawing, image, width, height):
    """Aspect-fit the PNG to the same canvas region as the SVG stroke bounds."""
    x0, y0, x1, y1 = drawing.bounds
    w, h = max(1., x1 - x0), max(1., y1 - y0)
    scale = min(width * .82 / w, height * .78 / h)
    target_w, target_h = w * scale, h * scale
    fit = min(target_w / image.width(), target_h / image.height())
    actual_w, actual_h = image.width() * fit, image.height() * fit
    return QRectF((width - actual_w) / 2, (height - actual_h) / 2, actual_w, actual_h)


def brush_route(rect, brush_fraction):
    """Vertical down/up serpentine covering the entire rectangular artwork area."""
    brush_px = max(2., rect.width() * max(.02, min(.5, float(brush_fraction))))
    gap = brush_px * .72
    count = max(2, math.ceil(rect.width() / gap) + 1)
    points = []
    for i in range(count):
        x = rect.left() + rect.width() * i / (count - 1)
        start_y = rect.top() if i % 2 == 0 else rect.bottom()
        end_y = rect.bottom() if i % 2 == 0 else rect.top()
        points.extend(((x, start_y), (x, end_y)))
    return points, brush_px


def partial_brush_path(points, fraction):
    """Arc-length-progressive paint path; return both path and brush-tip position."""
    progress = max(0., min(1., float(fraction)))
    path = QPainterPath(QPointF(*points[0]))
    lengths = [math.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(points,points[1:])]
    remaining = sum(lengths) * progress
    tip = points[0]
    if progress <= 0:
        return path, None
    for i, length in enumerate(lengths):
        a, b = points[i], points[i+1]
        if remaining >= length:
            path.lineTo(*b)
            tip = b
            remaining -= length
        else:
            factor = remaining / length if length else 1.
            tip = (a[0] + (b[0]-a[0])*factor, a[1] + (b[1]-a[1])*factor)
            path.lineTo(*tip)
            break
    return path, tip


def paint_mask(width, height, rect, progress, brush_fraction):
    """Return soft-edged opaque-mask pixels and the current brush tip."""
    progress = max(0., min(1., float(progress)))
    mask = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    points, brush_px = brush_route(rect, brush_fraction)
    path, tip = partial_brush_path(points, progress)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if progress >= 1:
        # Guarantees no uncovered holes, including the corners.
        painter.fillRect(rect, QColor(255,255,255))
        tip = None
    elif progress > 0:
        pen = QPen(QColor(255,255,255), brush_px, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
    painter.end()
    return mask, tip


def draw_hand(painter, tip, hand, width, hand_scale, anchor):
    if tip is None or hand is None or hand.isNull():
        return
    hand_w = width * hand_scale
    hand_h = hand_w * hand.height() / hand.width()
    painter.drawImage(QRectF(tip[0]-anchor[0]*hand_w,tip[1]-anchor[1]*hand_h,
                             hand_w,hand_h),hand)


def render_color_timeline(drawing, fraction, width=1920, height=1080,
                          duration=4, fade_duration=.4, hold_duration=.6,
                          final_image=None, thickness=1., hand=None,
                          hand_scale=.18, anchor=(.1,.1), reveal_mode='fade',
                          brush_width=.14, painting_hand=None):
    """Show SVG drawing, then either fade or brush-paint the original PNG."""
    if final_image is None or final_image.isNull():
        return render(drawing,fraction,width,height,thickness,hand,hand_scale,anchor)
    total = timeline_duration(duration, final_image, fade_duration, hold_duration)
    elapsed = max(0., min(1., float(fraction))) * total
    stroke_progress, reveal_progress = timeline_state(elapsed,duration,fade_duration)
    if reveal_progress == 0:
        return render(drawing,stroke_progress,width,height,thickness,hand,hand_scale,anchor)

    rect = artwork_rect(drawing,final_image,width,height)
    canvas = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    if reveal_mode == 'brush':
        if reveal_progress >= 1:
            painter.drawImage(rect, final_image)
            painter.end()
            return canvas
        # Preserve completed strokes until the paint sweep reaches them.
        mask, tip = paint_mask(width,height,rect,reveal_progress,brush_width)
        outline = render(drawing,1,width,height,thickness)
        erase = QPainter(outline)
        erase.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        erase.drawImage(0,0,mask)
        erase.end()
        painter.drawImage(0,0,outline)
        painted = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        painted.fill(Qt.GlobalColor.transparent)
        pp = QPainter(painted)
        pp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pp.drawImage(rect,final_image)
        pp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        pp.drawImage(0,0,mask)
        pp.end()
        painter.drawImage(0,0,painted)
        draw_hand(painter,tip,painting_hand,width,hand_scale,anchor)
    else:
        # Existing fade remains unchanged as an alternative reveal mode.
        painter.setOpacity(1.-reveal_progress)
        painter.drawImage(0,0,render(drawing,1,width,height,thickness))
        painter.setOpacity(reveal_progress)
        painter.drawImage(rect,final_image)
    painter.end()
    return canvas
