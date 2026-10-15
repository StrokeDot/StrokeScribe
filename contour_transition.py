"""Optional image-only contour lifecycle; no wall-clock or mutable frame state.

Paint occupies 70% of the existing paint phase. A conservative, ordered
cleanup occupies 28%; 2% is settled. Retirement waits for ALL source color,
so imperfect contours cannot expose a hole. Legacy rendering is untouched.
"""
from engine import Drawing, Stroke, render
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

PAINT_END = .70
RETIRE_END = .98

def retirement_states(drawing, progress):
    """Ordered (lifecycle, erased fraction) per stroke, weighted by arc length."""
    amount = max(0., min(1., (progress-PAINT_END)/(RETIRE_END-PAINT_END)))
    lengths = [max(1e-9, s.length) for s in drawing.strokes]
    remaining = sum(lengths)*amount
    states = []
    for length in lengths:
        erased = max(0., min(1., remaining/length))
        states.append(('removed' if erased >= 1 else 'retiring' if erased > 0
                       else 'waiting', erased))
        remaining -= length
    return states

def contour_lifecycle(drawing, draw_progress, paint_progress=None):
    """Inspectable states for the drawing and optional retirement phases."""
    if paint_progress is not None:
        return retirement_states(drawing,paint_progress)
    from image_drawing import drawing_state
    # Exact endpoints are semantic states, not floating-point arc-length
    # comparisons. Multiplication/summation can otherwise round the final
    # stroke a few ulps short and mark it "drawing" at 100%.
    fraction = max(0., min(1., float(draw_progress)))
    if fraction >= 1.:
        return [('completed',1.) for stroke in drawing.strokes]
    if fraction <= 0.:
        return [('hidden',0.) for stroke in drawing.strokes]
    state = drawing_state(drawing,fraction)
    remaining = sum(s.length for s in drawing.strokes)*state.stroke_progress
    result = []
    for stroke in drawing.strokes:
        if remaining >= stroke.length and stroke.length > 0:
            result.append(('completed',1.))
        elif remaining > 0 and stroke.length > 0:
            result.append(('drawing',remaining/stroke.length))
        else:
            result.append(('hidden',0.))
        remaining -= stroke.length
    return result

def remaining_contours(drawing, progress, direction='forward'):
    strokes = []
    for stroke, (_, erased) in zip(drawing.strokes, retirement_states(drawing, progress)):
        if erased >= 1:
            continue
        if erased <= 0:
            points = stroke.points
        elif direction == 'reverse':
            points = stroke.portion(stroke.length*(1-erased))
        else:
            reverse = Stroke(stroke.name, list(reversed(stroke.points)), stroke.color, stroke.width)
            points = list(reversed(reverse.portion(stroke.length*(1-erased))))
        strokes.append(Stroke(stroke.name, points, stroke.color, stroke.width))
    # Plain Drawing intentionally avoids image timing/debug visibility dispatch.
    return Drawing(strokes, drawing.bounds, [])

def source_frame(drawing, image, width, height):
    from color_reveal import artwork_rect
    frame = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    frame.fill(Qt.GlobalColor.transparent)
    painter = QPainter(frame)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(artwork_rect(drawing, image, width, height), image)
    painter.end()
    return frame

def render_transition(drawing, image, width, height, progress, thickness,
                      brush_width, stroke_spacing, hand, hand_scale, anchor,
                      reveal_mode='adaptive'):
    from color_reveal import artwork_rect, paint_mask, draw_hand, last_stroke_canvas_endpoint
    progress = max(0., min(1., float(progress)))
    if progress <= 0:
        return render(drawing,1,width,height,thickness)
    original = source_frame(drawing, image, width, height)
    if progress >= RETIRE_END:
        return original
    rect = artwork_rect(drawing, image, width, height)
    paint_progress = min(1., progress/PAINT_END)
    if paint_progress >= 1:
        mask = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        mask.fill(Qt.GlobalColor.white)
        tip = None
    elif reveal_mode == 'adaptive':
        from adaptive_hand import adaptive_paint_mask
        mask, tip = adaptive_paint_mask(drawing,image,width,height,rect,
                                       paint_progress,brush_width,stroke_spacing)
    elif reveal_mode == 'guided':
        from stroke_guided import guided_paint_mask
        mask, tip = guided_paint_mask(drawing,width,height,rect,paint_progress,brush_width)
    elif reveal_mode == 'clean':
        from clean_paint import clean_paint_mask
        mask, tip = clean_paint_mask(drawing,width,height,rect,paint_progress,brush_width)
    elif reveal_mode in ('brush','continue'):
        origin = last_stroke_canvas_endpoint(drawing,width,height) if reveal_mode == 'continue' else None
        mask, tip = paint_mask(width,height,rect,paint_progress,brush_width,origin)
    else:
        mask = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        mask.fill(Qt.GlobalColor.transparent)
        painter = QPainter(mask)
        painter.setOpacity(paint_progress)
        painter.fillRect(mask.rect(),Qt.GlobalColor.white)
        painter.end()
        tip = None
    painted = original.copy()
    painter = QPainter(painted)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0,0,mask)
    painter.end()
    contours = remaining_contours(drawing,progress,
                                  getattr(drawing,'retirement_direction','forward'))
    outline = render(contours,1,width,height,thickness)
    if getattr(drawing,'contour_transition','legacy') == 'paint':
        # Erase with coverage, NOT colored PNG alpha. Keep outside-mask
        # contours until the path-based cleanup. Never globally fade ink.
        if paint_progress < 1:
            painter = QPainter(outline)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            painter.drawImage(0,0,mask)
            painter.end()
        else:
            # Retain the last actual paint footprint during cleanup, instead
            # of erasing all outside-source contours at the phase boundary.
            if reveal_mode == 'adaptive':
                from adaptive_hand import adaptive_paint_mask
                coverage, _ = adaptive_paint_mask(drawing,image,width,height,rect,1,
                                                brush_width,stroke_spacing)
            else:
                coverage = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
                coverage.fill(Qt.GlobalColor.transparent)
                painter = QPainter(coverage); painter.fillRect(rect,Qt.GlobalColor.white); painter.end()
            painter = QPainter(outline)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            painter.drawImage(0,0,coverage)
            painter.end()
    painter = QPainter(painted)
    painter.drawImage(0,0,outline)
    draw_hand(painter,tip,hand,width,hand_scale,anchor)
    painter.end()
    return painted
