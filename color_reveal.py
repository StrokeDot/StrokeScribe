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


def last_stroke_canvas_endpoint(drawing, width, height):
    """Canvas position of the final stroke endpoint, after user reordering."""
    if not drawing.strokes or not drawing.strokes[-1].points:
        raise ValueError('A drawable final stroke is needed for continuous painting.')
    x0,y0,x1,y1 = drawing.bounds
    scale = min(width*.82/max(1.,x1-x0),height*.78/max(1.,y1-y0))
    ox = (width-(x1-x0)*scale)/2-x0*scale
    oy = (height-(y1-y0)*scale)/2-y0*scale
    x,y = drawing.strokes[-1].points[-1]
    return (x*scale+ox,y*scale+oy)


def continuation_brush_route(rect, brush_fraction, origin):
    """Continuous down/up coverage beginning at the actual last-stroke endpoint.

    Begin at origin without teleportation, cover its vertical stripe, sweep
    toward the nearest side, then cover the opposite side. Connecting strokes
    remain continuous; the final pass reaches both edges of the artwork.
    """
    brush_px = max(2.,rect.width()*max(.02,min(.5,float(brush_fraction))))
    gap = max(1.,brush_px*.72)
    x = min(rect.right(),max(rect.left(),float(origin[0])))
    y = min(rect.bottom(),max(rect.top(),float(origin[1])))
    top,bottom = rect.top(),rect.bottom()
    near_y = top if abs(y-top)<=abs(y-bottom) else bottom
    far_y = bottom if near_y==top else top
    points = [(float(origin[0]),float(origin[1]))]
    def append(px,py):
        if math.hypot(px-points[-1][0],py-points[-1][1])>1e-7:
            points.append((px,py))
    # If source SVG and final PNG are not perfectly aligned, travel smoothly
    # to the closest edge of the painted region instead of teleporting.
    append(x,y)
    append(x,near_y)
    append(x,far_y)
    at_y = far_y

    def sweep(start,end,y_at_start):
        if abs(end-start)<1e-7:
            return y_at_start
        columns=max(1,math.ceil(abs(end-start)/gap))
        y_position=y_at_start
        for index in range(1,columns+1):
            xpos=start+(end-start)*index/columns
            append(xpos,y_position)
            y_position=bottom if y_position==top else top
            append(xpos,y_position)
        return y_position

    nearest = rect.left() if x-rect.left()<=rect.right()-x else rect.right()
    opposite = rect.right() if nearest==rect.left() else rect.left()
    at_y=sweep(x,nearest,at_y)
    # Travel back along the edge, then cover the other side.
    append(x,at_y)
    sweep(x,opposite,at_y)
    return points,brush_px


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


def paint_mask(width, height, rect, progress, brush_fraction, origin=None):
    """Return soft-edged opaque-mask pixels and the current brush tip."""
    progress = max(0., min(1., float(progress)))
    mask = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    points, brush_px = (brush_route(rect, brush_fraction) if origin is None
                        else continuation_brush_route(rect, brush_fraction, origin))
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


def replace_outlines_with_painted_pixels(outline, painted):
    """Replace SVG ink only where color pixels are actually being revealed.

    Erase using *painted image alpha*, not the bare brush mask. This preserves
    complete SVG contours in transparent/unpainted parts of the original PNG
    even when the SVG and PNG are imperfectly aligned.
    """
    painter=QPainter(outline)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawImage(0,0,painted)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.drawImage(0,0,painted)
    painter.end()
    return outline


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
                          brush_width=.14, painting_hand=None, stroke_spacing=.55):
    """Show SVG drawing, then fade, serpentine, or endpoint-continuous painting."""
    if final_image is None or final_image.isNull():
        return render(drawing,fraction,width,height,thickness,hand,hand_scale,anchor)
    image_animation=getattr(drawing,'image_animation',None)
    if getattr(drawing,'source_kind',None)=='image' and image_animation in ('draw_paint','paint_only'):
        # This is a choice of visible animation, not an AI recognition mode.
        # Paint Only has zero drawing time. Both choices reuse the SAME
        # reconstructed regions and the SAME continuous paint clock.
        from image_painting import paint_frame
        if image_animation=='paint_only':
            paint_length=max(.001,float(fade_duration))
            total=paint_length+max(0.,float(hold_duration))
            elapsed=max(0.,min(1.,float(fraction)))*total
            paint_progress=min(1.,elapsed/paint_length)
            return paint_frame(drawing,final_image,width,height,paint_progress,
                               thickness,brush_width,stroke_spacing,
                               painting_hand,hand_scale,anchor,False)
        total=timeline_duration(duration,final_image,fade_duration,hold_duration)
        elapsed=max(0.,min(1.,float(fraction)))*total
        stroke_progress,paint_progress=timeline_state(elapsed,duration,fade_duration)
        if elapsed < max(.001,float(duration)):
            return render(drawing,stroke_progress,width,height,thickness,
                          hand,hand_scale,anchor)
        return paint_frame(drawing,final_image,width,height,paint_progress,
                           thickness,brush_width,stroke_spacing,
                           painting_hand,hand_scale,anchor,True)
    total = timeline_duration(duration, final_image, fade_duration, hold_duration)
    elapsed = max(0., min(1., float(fraction))) * total
    stroke_progress, reveal_progress = timeline_state(elapsed,duration,fade_duration)
    if (getattr(drawing,'source_kind',None) == 'image'
            and getattr(drawing,'contour_transition','legacy') != 'legacy'
            and elapsed >= duration):
        from contour_transition import render_transition
        return render_transition(drawing,final_image,width,height,reveal_progress,
                                 thickness,brush_width,stroke_spacing,painting_hand,
                                 hand_scale,anchor,reveal_mode)
    if reveal_mode == 'adaptive' and elapsed >= duration:
        from adaptive_hand import render_adaptive
        return render_adaptive(drawing,final_image,width,height,reveal_progress,
                               thickness,brush_width,stroke_spacing,
                               painting_hand,hand_scale,anchor)
    if reveal_progress == 0:
        frame = render(drawing,stroke_progress,width,height,thickness,hand,hand_scale,anchor)
        # At the exact phase boundary, keep the painting hand at the endpoint
        # instead of hiding it and making it reappear one frame later.
        if (reveal_mode in ('continue','guided','clean') and elapsed >= duration
                and painting_hand is not None and not painting_hand.isNull()):
            painter = QPainter(frame)
            draw_hand(painter,last_stroke_canvas_endpoint(drawing,width,height),
                      painting_hand,width,hand_scale,anchor)
            painter.end()
        return frame

    rect = artwork_rect(drawing,final_image,width,height)
    canvas = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    if reveal_mode in ('brush','continue','guided','clean'):
        if reveal_progress >= 1:
            painter.drawImage(rect, final_image)
            painter.end()
            return canvas
        # Preserve completed strokes until the paint sweep reaches them.
        origin = (last_stroke_canvas_endpoint(drawing,width,height)
                  if reveal_mode=='continue' else None)
        if reveal_mode == 'clean':
            from clean_paint import clean_paint_mask
            mask, tip = clean_paint_mask(drawing,width,height,rect,reveal_progress,brush_width)
        elif reveal_mode == 'guided':
            from stroke_guided import guided_paint_mask
            mask, tip = guided_paint_mask(drawing,width,height,rect,reveal_progress,brush_width)
        else:
            mask, tip = paint_mask(width,height,rect,reveal_progress,brush_width,origin=origin)
        # Build actual colored pixels first; mask-only erasure incorrectly
        # deleted traced contours in PNG-transparent regions.
        painted = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        painted.fill(Qt.GlobalColor.transparent)
        pp = QPainter(painted)
        pp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pp.drawImage(rect,final_image)
        pp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        pp.drawImage(0,0,mask)
        pp.end()
        # The colored image and temporary SVG ink are distinct layers.
        # Retire ink according to the same brush mask that reveals the PNG,
        # even when imperfect SVG paths extend outside the PNG silhouette.
        from svg_guide_cleanup import remove_svg_guides
        outline=remove_svg_guides(render(drawing,1,width,height,thickness),
                                  mask,final_image,rect)
        over=QPainter(outline)
        over.drawImage(0,0,painted)
        over.end()
        painter.drawImage(0,0,outline)
        draw_hand(painter,tip,painting_hand,width,hand_scale,anchor)
    else:
        # Existing fade remains unchanged as an alternative reveal mode.
        painter.setOpacity(1.-reveal_progress)
        painter.drawImage(0,0,render(drawing,1,width,height,thickness))
        painter.setOpacity(reveal_progress)
        painter.drawImage(rect,final_image)
    painter.end()
    return canvas
