"""Trace-driven reveal of complete TrueType/OpenType glyph ink.

Fonts define OUTLINES, not pen trajectories. We infer plausible centerline
strokes from each rasterized glyph, then give every genuine glyph pixel a
reveal time based on its nearest traced path. This keeps final lettering fully
legible without using a horizontal wipe.
"""
from __future__ import annotations

import bisect
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from engine import Drawing, Stroke
from stroke_timing import NATURAL_LENGTH, ease


def _thin(mask):
    """Fast vectorized Zhang-Suen thinning for pen skeletons."""
    a=np.pad((mask>0).astype(np.uint8),1)
    for _ in range(80):
        changed=False
        for phase in range(2):
            c=a[1:-1,1:-1]
            p2=a[:-2,1:-1]; p3=a[:-2,2:]; p4=a[1:-1,2:]
            p5=a[2:,2:]; p6=a[2:,1:-1]; p7=a[2:,:-2]
            p8=a[1:-1,:-2]; p9=a[:-2,:-2]
            n=p2+p3+p4+p5+p6+p7+p8+p9
            # Count 0 -> 1 transitions around each skeleton candidate.
            t=np.zeros_like(n)
            neighbors=(p2,p3,p4,p5,p6,p7,p8,p9,p2)
            for i in range(8):
                t+=((neighbors[i]==0)&(neighbors[i+1]==1)).astype(np.uint8)
            base=(c==1)&(n>=2)&(n<=6)&(t==1)
            if phase==0:
                erase=base&(p2*p4*p6==0)&(p4*p6*p8==0)
            else:
                erase=base&(p2*p4*p8==0)&(p2*p6*p8==0)
            if erase.any():
                c[erase]=0
                changed=True
        if not changed:break
    return a[1:-1,1:-1].astype(bool)


def _direction(route,back=6):
    """Unit direction of the last few pixels of a route."""
    a=route[max(0,len(route)-1-back)]; b=route[-1]
    dx,dy=b[0]-a[0],b[1]-a[1]
    n=math.hypot(dx,dy)
    return (dx/n,dy/n) if n else (0.,0.)


def _orient(path):
    """Write like a hand: mostly-vertical lines go DOWN, the others go to the RIGHT
    (the same for upright and slanted fonts). Closed loops keep their direction."""
    (x0,y0),(x1,y1)=path[0],path[-1]
    dx,dy=x1-x0,y1-y0
    if abs(dx)<1e-9 and abs(dy)<1e-9:
        return path
    if abs(dy)>abs(dx)*.8:
        return path if dy>0 else path[::-1]
    return path if dx>0 else path[::-1]


def _paths_from_binary(binary,scale=1.):
    """Pen passes over a thinned glyph, in a handwriting-like order.

    At a crossing or a join, the pen goes straight on along the branch that best
    continues its direction (so an "e", an "o" or an "l" is one smooth line instead
    of small pieces). Lines are oriented like a hand writes them (down, or to the
    right), and the passes of a letter are chained from the top-left.

    scale: the letter size compared with the usual Letter detail (68). Sizes in
    pixels (spurs, small gaps) follow it, so the writing is the same at any detail."""
    pts={(int(x),int(y)) for y,x in zip(*np.nonzero(binary))}
    if not pts:return []
    def adjacent(p):
        # A diagonal step is skipped when the two pixels already touch through a
        # side neighbour: otherwise every staircase is full of tiny triangles,
        # every pixel looks like a crossing and the line breaks into pieces.
        x,y=p
        out=[]
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                q=(x+dx,y+dy)
                if not (dx or dy) or q not in pts:continue
                if dx and dy and ((x+dx,y) in pts or (x,y+dy) in pts):continue
                out.append(q)
        return sorted(out)
    graph={p:adjacent(p) for p in pts}
    used=set()
    def edge(a,b):return (a,b) if a<b else (b,a)
    def free(p):return [q for q in graph[p] if edge(p,q) not in used]
    turn=math.cos(math.radians(70))      # a branch must continue within ~70 degrees
    def walk(a,b):
        route=[a,b]
        used.add(edge(a,b))
        while len(route)<8000:
            options=free(route[-1])
            if not options:break
            if len(options)>1 or len(graph[route[-1]])>2:
                d=_direction(route)
                def score(q):
                    # Look a few pixels down each branch, not only at the next pixel.
                    probe=[route[-1],q]; seen={edge(route[-1],q)}
                    for _ in range(5):
                        nxt=[r for r in graph[probe[-1]] if edge(probe[-1],r) not in used
                             and edge(probe[-1],r) not in seen and r not in probe]
                        if not nxt:break
                        seen.add(edge(probe[-1],nxt[0])); probe.append(nxt[0])
                    e=_direction(probe,len(probe)-1)
                    return d[0]*e[0]+d[1]*e[1]
                best=max(options,key=score)
                if d!=(0.,0.) and score(best)<turn and len(route)>3:
                    break                          # a sharp corner at a join: lift here
                nxt=best
            else:
                nxt=options[0]
            used.add(edge(route[-1],nxt))
            route.append(nxt)
        return route
    def top_left(p):return (p[1]+p[0]*.35,p[0])
    paths=[]
    # Line ends first (a hand starts at an end, top-left first), then joins, then loops.
    for group in (lambda p:len(graph[p])==1, lambda p:len(graph[p])>2, lambda p:True):
        for p in sorted((p for p in graph if group(p)),key=top_left):
            while free(p):
                paths.append(walk(p,free(p)[0]))
    # A 1-pixel mark still needs a stroke and paint coverage.
    if not paths:
        paths=[[(x,y),(x+.01,y)] for x,y in sorted(pts)]
    def length(path):
        return sum(math.dist(a,b) for a,b in zip(path,path[1:]))
    # Suppress tiny skeleton spurs near existing longer strokes. These are
    # topology artifacts at joins/corners; otherwise the hand returns to
    # finish a 1-3 px leftover after writing the letter. Distant tiny marks
    # (e.g. a dot or punctuation) are retained.
    paths=[p for p in paths if len(p)>=2]
    spur=4.*max(1.,scale)
    substantial=[p for p in paths if length(p)>=spur]
    if substantial:
        kept=[]
        for path in paths:
            if length(path)>=spur:
                kept.append(path); continue
            near=any(min(math.dist(path[0],q),math.dist(path[-1],q))<=3.*max(1.,scale)
                     for major in substantial for q in major)
            if not near:
                kept.append(path)
        paths=kept
    if not paths:return []
    paths=[_orient(p) for p in paths]
    # The first pass starts nearest the top-left; then the nearest next start.
    # A vertical line is never written upwards to save a short trip.
    remaining=sorted(paths,key=lambda p:top_left(p[0]))
    chain=[remaining.pop(0)]
    while remaining:
        tip=chain[-1][-1]
        ranked=[]
        for i,path in enumerate(remaining):
            ranked.append((math.dist(tip,path[0]),i,False))
            (x0,y0),(x1,y1)=path[0],path[-1]
            if abs(y1-y0)<=abs(x1-x0)*.8:          # not a down stroke: may be written backwards
                ranked.append((math.dist(tip,path[-1])*1.25,i,True))
        _,i,reverse=min(ranked)
        chosen=remaining.pop(i)
        if reverse: chosen=list(reversed(chosen))
        # Pieces that touch (skeleton joins) are one pen movement, not a new stroke.
        if math.dist(chain[-1][-1],chosen[0])<=1.5:
            chain[-1]=chain[-1]+chosen[1:]
        else:
            chain.append(chosen)
    return chain


SHARP_POINT=128          # the ink is always drawn this big (when the text fits), so it stays sharp
MAX_INK_PIXELS=2_600_000


def create_font_drawing(text,fontfile,point_size=68):
    """Font lettering: the real glyph ink plus estimated pen paths.

    Letter detail (point_size) decides how finely the pen paths are traced. The ink
    itself is drawn at SHARP_POINT (if the text is not too long), so the letters are
    equally sharp at every Letter detail and the hand follows the same rhythm."""
    if not text.strip():raise ValueError('Enter some lettering to animate.')
    if len(text)>240:raise ValueError('Font lettering supports at most 240 characters.')
    point_size=int(point_size)
    if not 24<=point_size<=128:raise ValueError('Choose a font detail size from 24 to 128.')
    font=ImageFont.truetype(str(fontfile),point_size)
    lines=text.split('\n')
    ascent,descent=font.getmetrics()
    # Margins follow the letter size, so the text sits the same at any Letter detail.
    pad=point_size/68.
    line_height=ascent+descent+12*pad
    w=max(20,math.ceil(max(font.getlength(line) for line in lines)+40*pad))
    h=max(20,math.ceil(len(lines)*line_height+32*pad))
    if w*h>MAX_INK_PIXELS:
        raise ValueError('Text is too large for tracing. Shorten it or lower the font size.')
    # How much bigger the ink is drawn than the tracing (1 = the same size).
    k=max(1.,SHARP_POINT/point_size)
    while k>1. and w*h*k*k>MAX_INK_PIXELS:
        k=max(1.,k*.9)
    big=ImageFont.truetype(str(fontfile),max(point_size,round(point_size*k))) if k>1. else font
    k=big.size/point_size
    W,H=max(20,math.ceil(w*k)),max(20,math.ceil(h*k))
    ink=Image.new('RGBA',(W,H),(0,0,0,0))
    painter=ImageDraw.Draw(ink)
    measure=ImageDraw.Draw(Image.new('L',(1,1)))
    strokes=[]
    boxes=[]
    for row,line in enumerate(lines):
        y=10*pad+row*line_height
        painter.text((18*pad*k,y*k),line,font=big,fill=(37,54,74,255))
        for index,char in enumerate(line):
            if char.isspace():continue
            x=18*pad+font.getlength(line[:index])
            left,top,right,bottom=measure.textbbox((x,y),char,font=font)
            left=max(0,math.floor(left)-2); top=max(0,math.floor(top)-2)
            right=min(w,math.ceil(right)+2);bottom=min(h,math.ceil(bottom)+2)
            if right-left<2 or bottom-top<2:continue
            # Render the individual original glyph for centerline inference.
            cell=Image.new('L',(right-left,bottom-top))
            ImageDraw.Draw(cell).text((x-left,y-top),char,font=font,fill=255)
            skeleton=_thin(np.asarray(cell)>90)
            paths=_paths_from_binary(skeleton,point_size/68.)
            if not paths:
                paths=[[(0,(bottom-top)/2),(right-left,(bottom-top)/2)]]
            piece=len(boxes)
            boxes.append((left*k,top*k,right*k,bottom*k))
            for route in paths[:150]:
                points=[(float((left+px)*k),float((top+py)*k)) for px,py in route]
                if len(points)<2:continue
                s=Stroke(f'Pen {char} / {len(strokes)+1}',points,'#25364a',1.)
                s.font_piece=piece
                strokes.append(s)
            if len(strokes)>3000:
                raise ValueError('Font has too many detail paths. Reduce the text length.')
    if not strokes:raise ValueError('No drawable glyph strokes were found.')
    drawing=Drawing(strokes,(0.,0.,float(W),float(H)),[
        'Estimated pen strokes trace real typeface shapes, with complete original glyph ink.',
        'A regular font does not record its human writing order; pen paths are approximations.',
    ])
    drawing.source_kind='font'
    drawing.font_point=point_size
    drawing.font_scale=k                 # ink pixels per traced pixel
    drawing.font_ink=ink
    drawing.font_color='#25364a'
    drawing.font_boxes=tuple(boxes)
    drawing.font_time_cache=None
    return drawing


def _natural(drawing):
    return getattr(drawing,'pen_ease','off')=='natural'


def _signature(drawing):
    return tuple(id(stroke) for stroke in drawing.strokes)+(_natural(drawing),)


_EASE_X=np.linspace(0.,1.,1025)
_EASE_Y=None


def _uneased(share):
    """Inverse of the Natural pen ease: when the pen reaches `share` of a line."""
    global _EASE_Y
    if _EASE_Y is None:
        _EASE_Y=np.array([ease(float(x)) for x in _EASE_X])
    return float(np.interp(share,_EASE_Y,_EASE_X))


def _stroke_schedule(drawing):
    """The one clock used by ink appearance AND the hand.

    Events never overlap. A pen-lift event carries no ink and is inserted
    between disconnected paths. Stroke order remains editable in the UI.
    """
    signature=_signature(drawing)
    cached=getattr(drawing,'font_schedule_cache',None)
    if cached is not None and cached[0]==signature:
        return cached[1],cached[2]
    events=[]
    t=0.
    previous=None
    # Pixel sizes follow the letter size, so the rhythm is the same at any Letter detail.
    scale=max(.3,float(getattr(drawing,'font_point',68) or 68)/68.)*float(getattr(drawing,'font_scale',1.) or 1.)
    small_gap=5.*scale
    natural=_natural(drawing)
    for index,stroke in enumerate(drawing.strokes):
        if len(stroke.points)<2:continue
        first=stroke.points[0]
        if previous is not None:
            distance=math.dist(previous,first)
            if distance>small_gap:
                # Pen-up travel is visible in time, but reveals no ink.
                # Limit long trips so the viewer doesn't wait excessively.
                lift_duration=min(12.*scale,max(2.5*scale,distance*.24))
                if natural:
                    lift_duration*=2.2               # a real hand takes its time between lines
                events.append(('lift',None,t,t+lift_duration,previous,first))
                t+=lift_duration
            elif distance>0:
                # A tiny gap inside a letter: the pen just carries on (no lift, no stop).
                events.append(('lift',None,t,t+distance,previous,first))
                t+=distance
        duration=max(1.,stroke.length)
        if natural:
            # Long lines go a little faster than short ones, like a real hand.
            duration=max(1.,(stroke.length/scale)**NATURAL_LENGTH*scale)
        events.append(('draw',index,t,t+duration,first,stroke.points[-1]))
        t+=duration
        previous=stroke.points[-1]
    if not events:
        raise ValueError('The font has no drawable strokes.')
    drawing.font_schedule_cache=(signature,tuple(events),t)
    return tuple(events),t


def _ink_ownership(drawing):
    """Assign EVERY visible glyph pixel one pen stroke and one reveal time.

    A single nearest-seed transform transfers both the owner and its precise
    stroke-relative time; this prevents independent clocks from painting
    unrelated fragments. Later stroke pixels cannot reveal before the owning
    stroke starts, and no ink changes during pen lifts.
    """
    events,total=_stroke_schedule(drawing)
    signature=_signature(drawing)
    natural=_natural(drawing)
    cache=getattr(drawing,'font_time_cache',None)
    if cache is not None and cache[0]==signature:
        return cache[1],cache[2],cache[3]
    w,h=drawing.font_ink.size
    seed=np.full((h,w),np.inf,dtype=np.float32)
    seed_owner=np.full((h,w),-1,dtype=np.int32)
    intervals={}
    for kind,index,start,end,_,_ in events:
        if kind!='draw':continue
        intervals[index]=(start,end)
        stroke=drawing.strokes[index]
        for seg_index,(a,b) in enumerate(zip(stroke.points,stroke.points[1:])):
            distance=math.dist(a,b)
            samples=max(1,math.ceil(distance*2))
            for step in range(samples+1):
                progress=step/samples
                x=round(a[0]+(b[0]-a[0])*progress)
                y=round(a[1]+(b[1]-a[1])*progress)
                if not (0<=x<w and 0<=y<h):continue
                passed=stroke.distances[seg_index]+distance*progress
                share=min(1.,passed/max(.001,stroke.length))
                if natural:
                    share=_uneased(share)          # the time the eased pen reaches this point
                when=(start+(end-start)*share)/total
                if when<seed[y,x]:
                    seed[y,x]=when
                    seed_owner[y,x]=index

    if not np.any(seed_owner>=0):
        raise ValueError('No valid pen path positions were found in this font.')
    source=(seed_owner<0).astype(np.uint8)
    # OpenCV labels each path sample and all pixels nearest that sample.
    # Both the ink's owner and its reveal time come from THAT SAME sample.
    _,labels=cv2.distanceTransformWithLabels(
        source,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
    count=int(labels.max())+1
    nearest_time=np.ones(count,dtype=np.float32)
    nearest_owner=np.full(count,-1,dtype=np.int32)
    ys,xs=np.nonzero(seed_owner>=0)
    for y,x in zip(ys,xs):
        key=int(labels[y,x])
        value=float(seed[y,x])
        if value<nearest_time[key]:
            nearest_time[key]=value
            nearest_owner[key]=seed_owner[y,x]
    owner=nearest_owner[labels]
    timing=nearest_time[labels]
    # Bound all ownership times in one vectorized pass, rather than scanning
    # the entire glyph bitmap once PER stroke (too slow for long sentences).
    lower=np.zeros(len(drawing.strokes),dtype=np.float32)
    upper=np.ones(len(drawing.strokes),dtype=np.float32)
    for index,(start,end) in intervals.items():
        lower[index]=start/total
        upper[index]=end/total
    safe=np.maximum(owner,0)
    timing=np.where(owner>=0,
                    np.minimum(upper[safe],np.maximum(lower[safe],timing)),
                    1.).astype(np.float32)
    drawing.font_time_cache=(signature,timing,owner,total)
    return timing,owner,total


def _timing_field(drawing):
    """Compatibility API used by existing handwriting tests."""
    timing,_,total=_ink_ownership(drawing)
    return timing,total


def _pen_state(drawing,progress):
    """Single drawing/pen-lift event for the animation playhead.

    Returns (position, pen_down, stroke_index). During a lift the hand
    travels smoothly from the previous stroke endpoint to the next start.
    No glyph pixels become visible during this event.
    """
    events,total=_stroke_schedule(drawing)
    progress=min(1.,max(0.,float(progress)))
    if _natural(drawing):
        from stroke_timing import natural_tempo
        progress=natural_tempo(progress)
    moment=progress*total
    if moment>=total:
        event=events[-1]
        return event[5],False,None
    for kind,index,start,end,a,b in events:
        if moment>=end:continue
        fraction=max(0.,min(1.,(moment-start)/max(.001,end-start)))
        if kind=='lift':
            return (a[0]+(b[0]-a[0])*fraction,
                    a[1]+(b[1]-a[1])*fraction),False,None
        stroke=drawing.strokes[index]
        if _natural(drawing):
            fraction=ease(fraction)
        points=stroke.portion(stroke.length*fraction)
        return points[-1],True,index
    return events[-1][5],False,None


def render_traced_font(drawing,progress,width,height,thickness=1.,
                       hand=None,hand_scale=.18,anchor=(.1,.1)):
    fraction=max(0.,min(1.,float(progress)))
    output=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    if fraction<=0:return output
    rgba=np.asarray(drawing.font_ink.convert('RGBA'))
    pixels=rgba.copy()
    # Color affects only RGB, never alpha/timing/pen ownership.
    from PySide6.QtGui import QColor
    ink_color=QColor(getattr(drawing,'font_color','#25364a'))
    if not ink_color.isValid():ink_color=QColor('#25364a')
    pixels[:,:,:3]=(ink_color.red(),ink_color.green(),ink_color.blue())
    if fraction<1.:
        timing,owner,_=_ink_ownership(drawing)
        eligible=(owner>=0)&(timing<=fraction+1e-7)
        pixels[:,:,3]=(pixels[:,:,3].astype(np.float32)*
                        eligible).astype(np.uint8)
    ih,iw=pixels.shape[:2]
    buffer=pixels.tobytes()
    glyph_image=QImage(buffer,iw,ih,iw*4,QImage.Format.Format_RGBA8888).copy()
    scale=min(width*.82/max(1,iw),height*.78/max(1,ih))
    ox=(width-iw*scale)/2
    oy=(height-ih*scale)/2
    painter=QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF(ox,oy,iw*scale,ih*scale),glyph_image)
    if hand is not None and not hand.isNull() and fraction<1.:
        tip,pen_down,_=_pen_state(drawing,fraction)
        tx=ox+tip[0]*scale
        ty=oy+tip[1]*scale
        # Slightly raise the hand during moves; there is no drawing then.
        if not pen_down:
            ty-=min(12.,width*.015)
        hw=width*hand_scale
        hh=hw*hand.height()/hand.width()
        from hand_layer import paint
        paint(painter,QRectF(tx-anchor[0]*hw,ty-anchor[1]*hh,hw,hh),hand)
    painter.end()
    return output
