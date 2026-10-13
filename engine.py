"""Local vector-stroke renderer. All raster output starts with transparent pixels."""
from __future__ import annotations
import bisect, math, json, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor
from svgelements import SVG, Shape, Path as SVGPath, Move

@dataclass
class Stroke:
    name: str
    points: list[tuple[float, float]]
    color: str = '#153c54'
    width: float = 3
    def __post_init__(self):
        self.distances = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.distances.append(self.distances[-1] + math.dist(a, b))
        self.length = self.distances[-1]
    def portion(self, distance):
        if distance >= self.length: return self.points
        i = bisect.bisect_right(self.distances, max(0, distance))
        if i >= len(self.points): return self.points
        a, b = self.points[i-1], self.points[i]
        span = self.distances[i] - self.distances[i-1]
        f = (distance-self.distances[i-1])/span if span else 0
        return self.points[:i] + [(a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f)]

@dataclass
class Drawing:
    strokes: list[Stroke]
    bounds: tuple[float, float, float, float]
    warnings: list[str]

def import_svg(filename):
    raw = Path(filename).read_text(encoding='utf-8-sig')
    if len(raw) > 5_000_000: raise ValueError('SVG is too large for this prototype (5 MB limit).')
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper(): raise ValueError('SVG document entities are unsupported.')
    root = ET.fromstring(raw)
    warnings = set()
    for e in root.iter():
        tag = e.tag.split('}')[-1]
        if tag in {'text','image','clipPath','mask','filter','linearGradient','radialGradient','style','foreignObject','svg'} and e is not root:
            warnings.add(f'{tag}: unsupported; convert to plain stroked paths for predictable results.')
        if any(k in e.attrib for k in ('clip-path','mask','filter')):
            warnings.add('Clipping, masks and filters are ignored.')
    svg = SVG.parse(filename, reify=True)
    strokes = []
    for el in svg.elements():
        if not isinstance(el, Shape): continue
        if el.values.get('visibility') == 'hidden' or el.values.get('display') == 'none': continue
        p = SVGPath(el)
        p.reify()
        if not len(p): continue
        color = str(el.stroke) if el.stroke is not None else 'None'
        if color in ('None', 'none'):
            color = str(el.fill) if el.fill is not None else '#153c54'
            if color in ('None','none'): continue
            warnings.add('Filled shapes are drawn as outlines; fills are not reconstructed as pen strokes.')
        for sub_index, sub in enumerate(p.as_subpaths()):
            points=[]
            for seg in sub:
                if isinstance(seg, Move): continue
                # Dense curve sampling, then arc-length timing along the resulting geometry.
                n = max(1, min(20000, math.ceil(seg.length(error=1e-5)/0.4)))
                for j in range(n+1):
                    pt=seg.point(j/n)
                    xy=(float(pt.x),float(pt.y))
                    if not all(math.isfinite(v) for v in xy): raise ValueError('Non-finite SVG coordinates.')
                    if not points or math.dist(points[-1],xy)>1e-9: points.append(xy)
            if len(points)>1:
                strokes.append(Stroke(f'{el.id or "shape"} / {sub_index+1}',points,color,float(el.stroke_width or 3)))
            if sum(len(s.points) for s in strokes)>500000: raise ValueError('Drawing is too complex (500,000 sampled points maximum).')
    if not strokes: raise ValueError('No drawable vector strokes found. Convert text or images to SVG paths first.')
    allpts=[pt for s in strokes for pt in s.points]
    xs,ys=zip(*allpts)
    return Drawing(strokes,(min(xs),min(ys),max(xs),max(ys)),sorted(warnings))

def render(drawing, progress, width=1920, height=1080, thickness=1.0, hand=None, hand_scale=0.18, anchor=(0.1,0.1)):
    image=QImage(width,height,QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    x0,y0,x1,y1=drawing.bounds
    scale=min(width*0.82/max(1,x1-x0),height*0.78/max(1,y1-y0))
    ox=(width-(x1-x0)*scale)/2-x0*scale
    oy=(height-(y1-y0)*scale)/2-y0*scale
    remaining=sum(s.length for s in drawing.strokes)*max(0,min(1,progress))
    tip=None
    for stroke in drawing.strokes:
        if remaining<=0: break
        points=stroke.portion(min(remaining,stroke.length))
        path=QPainterPath(QPointF(points[0][0]*scale+ox,points[0][1]*scale+oy))
        for x,y in points[1:]: path.lineTo(x*scale+ox,y*scale+oy)
        pen=QPen(QColor(stroke.color),max(0.1,stroke.width*thickness*scale),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        tip=(points[-1][0]*scale+ox,points[-1][1]*scale+oy)
        remaining-=stroke.length
    if hand is not None and not hand.isNull() and tip and 0<progress<1:
        hw=width*hand_scale
        hh=hw*hand.height()/hand.width()
        painter.drawImage(QRectF(tip[0]-anchor[0]*hw,tip[1]-anchor[1]*hh,hw,hh),hand)
    painter.end()
    return image

def export_frames(drawing, folder, duration=4, fps=30, width=1920, height=1080, thickness=1, hand=None, hand_scale=.18, anchor=(.1,.1), callback=None, final_image=None, fade_duration=.4, hold_duration=.6, reveal_mode='fade', brush_width=.14, painting_hand=None):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    use_color = final_image is not None and not final_image.isNull()
    if use_color:
        from color_reveal import timeline_duration, render_color_timeline
        total=timeline_duration(duration,final_image,fade_duration,hold_duration)
    else:
        total=duration
    count=max(2,round(total*fps))
    for i in range(count):
        fraction=i/(count-1)
        if use_color:
            img=render_color_timeline(drawing,fraction,width,height,duration,fade_duration,hold_duration,
                                      final_image,thickness,hand,hand_scale,anchor,
                                      reveal_mode,brush_width,painting_hand)
        else:
            img=render(drawing,fraction,width,height,thickness,hand,hand_scale,anchor)
        if not img.save(str(folder/f'frame_{i:06d}.png')): raise OSError('Unable to save PNG frame.')
        if callback and callback(i+1,count) is False: raise InterruptedError('Export cancelled; partial frames remain in the export folder.')
    (folder/'sequence.json').write_text(json.dumps(dict(width=width,height=height,fps=fps,frames=count,
        duration=count/fps,draw_duration=duration,color_reveal=use_color,
        color_fade_seconds=fade_duration if use_color else 0,
        color_hold_seconds=hold_duration if use_color else 0,
        reveal_mode=reveal_mode if use_color else 'none',
        brush_width=brush_width if use_color and reveal_mode=='brush' else None,
        painting_hand=bool(use_color and reveal_mode=='brush' and painting_hand is not None and not painting_hand.isNull()),
        alpha=True,first_frame='transparent',
        last_frame='original_color_png' if use_color else 'complete'),indent=2))
    return count

def encode_mov(folder, fps=30):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg: raise RuntimeError('FFmpeg was not found on PATH. PNG frames have still been exported.')
    output=Path(folder)/'animation_prores4444.mov'
    cmd=[ffmpeg,'-n','-hide_banner','-loglevel','error','-framerate',str(fps),'-i',str(Path(folder)/'frame_%06d.png'),'-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le','-alpha_bits','16',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise RuntimeError(result.stderr[-2000:])
    return output
