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
    return render(drawing,state.stroke_progress,width,height,thickness,
                  hand if state.painting else None,hand_scale,anchor,image_timing=False)
