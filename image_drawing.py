"""Drawing-phase timing with visible pen lifts for reconstructed raster paths."""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class DrawState:
    stroke_progress: float
    painting: bool

def drawing_state(drawing,fraction):
    strokes=drawing.strokes
    ink=sum(s.length for s in strokes)
    if ink<=0: return DrawState(0.,False)
    phases=[]; previous=None
    for stroke in strokes:
        if previous is not None:
            distance=math.dist(previous,stroke.points[0])
            if distance>1e-6:
                phases.append((min(distance*.25,ink*.02),0.,False))
        phases.append((stroke.length,stroke.length,True))
        previous=stroke.points[-1]
    remaining=max(0.,min(1.,float(fraction)))*sum(p[0] for p in phases)
    done=0.
    for duration,paint_length,painting in phases:
        if remaining<duration:
            return DrawState((done+(paint_length*remaining/duration if painting else 0.))/ink,painting)
        remaining-=duration; done+=paint_length
    return DrawState(1.,False)

def render_image_lines(drawing,progress,width,height,thickness,hand,hand_scale,anchor):
    from engine import render
    state=drawing_state(drawing,progress)
    if getattr(drawing,'drawing_visibility','progressive') == 'full':
        from PySide6.QtGui import QPainter
        from color_reveal import draw_hand
        frame = render(drawing,1,width,height,thickness,image_timing=False)
        if state.painting and 0 < progress < 1 and hand is not None:
            remaining = sum(s.length for s in drawing.strokes)*state.stroke_progress
            tip = None
            for stroke in drawing.strokes:
                if remaining <= 0: break
                tip = stroke.portion(min(remaining,stroke.length))[-1]
                remaining -= stroke.length
            if tip is not None:
                x0,y0,x1,y1 = drawing.bounds
                scale = min(width*.82/max(1,x1-x0),height*.78/max(1,y1-y0))
                tip = ((tip[0]-(x0+x1)/2)*scale+width/2,
                       (tip[1]-(y0+y1)/2)*scale+height/2)
                painter = QPainter(frame)
                draw_hand(painter,tip,hand,width,hand_scale,anchor)
                painter.end()
        return frame
    return render(drawing,state.stroke_progress,width,height,thickness,
                  hand if state.painting else None,hand_scale,anchor,image_timing=False)
