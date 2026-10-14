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


def _paths_from_binary(binary):
    """Return left-to-right ordered pen passes over a thinned glyph."""
    pts={(int(x),int(y)) for y,x in zip(*np.nonzero(binary))}
    if not pts:return []
    def adjacent(p):
        x,y=p
        return sorted(((x+dx,y+dy) for dy in (-1,0,1) for dx in (-1,0,1)
                       if (dx or dy) and (x+dx,y+dy) in pts))
    graph={p:adjacent(p) for p in pts}
    used=set()
    paths=[]
    def edge(a,b):return (a,b) if a<b else (b,a)
    def walk(a,b):
        route=[a,b]
        used.add(edge(a,b))
        previous,current=a,b
        while len(route)<8000 and len(graph[current])==2:
            opts=[p for p in graph[current]
                  if p!=previous and edge(current,p) not in used]
            if not opts:break
            nxt=opts[0]
            used.add(edge(current,nxt))
            route.append(nxt)
            previous,current=current,nxt
        return route
    starts=sorted(graph,key=lambda p:(p[0],p[1]))
    for p in starts:
        if len(graph[p])==2:continue
        for q in graph[p]:
            if edge(p,q) not in used:
                paths.append(walk(p,q))
    for p in starts:
        for q in graph[p]:
            if edge(p,q) not in used:
                paths.append(walk(p,q))
    # A 1-pixel mark still needs a stroke and paint coverage.
    if not paths:
        paths=[[(x,y),(x+.01,y)] for x,y in sorted(pts)]
    ordered=[]
    for path in paths:
        if len(path)<2:continue
        if (path[-1][0],path[-1][1])<(path[0][0],path[0][1]):
            path.reverse()
        ordered.append(path)
    ordered.sort(key=lambda p:(min(x for x,y in p),min(y for x,y in p),
                               -len(p)))
    return ordered


def create_font_drawing(text,fontfile,point_size=68):
    if not text.strip():raise ValueError('Enter some lettering to animate.')
    if len(text)>240:raise ValueError('Font lettering supports at most 240 characters.')
    point_size=int(point_size)
    if not 24<=point_size<=128:raise ValueError('Choose a font detail size from 24 to 128.')
    font=ImageFont.truetype(str(fontfile),point_size)
    lines=text.split('\n')
    ascent,descent=font.getmetrics()
    line_height=ascent+descent+12
    w=max(20,math.ceil(max(font.getlength(line) for line in lines)+40))
    h=max(20,len(lines)*line_height+32)
    if w*h>2_600_000:
        raise ValueError('Text is too large for tracing. Shorten it or lower the font size.')
    ink=Image.new('RGBA',(w,h),(0,0,0,0))
    painter=ImageDraw.Draw(ink)
    strokes=[]
    boxes=[]
    for row,line in enumerate(lines):
        y=10+row*line_height
        painter.text((18,y),line,font=font,fill=(37,54,74,255))
        for index,char in enumerate(line):
            if char.isspace():continue
            x=18+font.getlength(line[:index])
            left,top,right,bottom=painter.textbbox((x,y),char,font=font)
            left=max(0,math.floor(left)-2); top=max(0,math.floor(top)-2)
            right=min(w,math.ceil(right)+2);bottom=min(h,math.ceil(bottom)+2)
            if right-left<2 or bottom-top<2:continue
            # Render the individual original glyph for centerline inference.
            cell=Image.new('L',(right-left,bottom-top))
            ImageDraw.Draw(cell).text((x-left,y-top),char,font=font,fill=255)
            skeleton=_thin(np.asarray(cell)>90)
            paths=_paths_from_binary(skeleton)
            if not paths:
                paths=[[(0,(bottom-top)/2),(right-left,(bottom-top)/2)]]
            piece=len(boxes)
            boxes.append((left,top,right,bottom))
            for route in paths[:150]:
                points=[(float(left+px),float(top+py)) for px,py in route]
                if len(points)<2:continue
                s=Stroke(f'Pen {char} / {len(strokes)+1}',points,'#25364a',1.)
                s.font_piece=piece
                strokes.append(s)
            if len(strokes)>3000:
                raise ValueError('Font has too many detail paths. Reduce the text length.')
    if not strokes:raise ValueError('No drawable glyph strokes were found.')
    drawing=Drawing(strokes,(0.,0.,float(w),float(h)),[
        'Estimated pen strokes trace real typeface shapes, with complete original glyph ink.',
        'A regular font does not record its human writing order; pen paths are approximations.',
    ])
    drawing.source_kind='font'
    drawing.font_ink=ink
    drawing.font_boxes=tuple(boxes)
    drawing.font_time_cache=None
    return drawing


def _timing_field(drawing):
    """Allocate genuine glyph pixels by nearest traced pen point."""
    signature=tuple(id(s) for s in drawing.strokes)
    cache=getattr(drawing,'font_time_cache',None)
    if cache is not None and cache[0]==signature:return cache[1],cache[2]
    w,h=drawing.font_ink.size
    seed=np.full((h,w),-1.,dtype=np.float32)
    lengths=[max(1.,s.length) for s in drawing.strokes]
    total=sum(lengths)
    elapsed=0.
    for stroke,weight in zip(drawing.strokes,lengths):
        for k,(a,b) in enumerate(zip(stroke.points,stroke.points[1:])):
            distance=math.dist(a,b)
            n=max(1,math.ceil(distance))
            for j in range(n+1):
                f=j/n
                x=round(a[0]+(b[0]-a[0])*f)
                y=round(a[1]+(b[1]-a[1])*f)
                if 0<=x<w and 0<=y<h:
                    traversed=stroke.distances[k]+distance*f
                    moment=(elapsed+weight*traversed/max(.001,stroke.length))/total
                    if seed[y,x]<0 or moment<seed[y,x]:
                        seed[y,x]=moment
        elapsed+=weight
    if not (seed>=0).any():
        raise ValueError('No valid pen positions for font tracing.')
    source=np.ones((h,w),dtype=np.uint8)
    source[seed>=0]=0
    _,labels=cv2.distanceTransformWithLabels(
        source,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
    maxlabel=int(labels.max())
    nearest=np.ones(maxlabel+1,dtype=np.float32)
    ys,xs=np.nonzero(seed>=0)
    for y,x in zip(ys,xs):
        label=int(labels[y,x])
        nearest[label]=min(nearest[label],seed[y,x])
    timing=nearest[labels]
    drawing.font_time_cache=(signature,timing,total)
    return timing,total


def render_traced_font(drawing,progress,width,height,thickness=1.,
                       hand=None,hand_scale=.18,anchor=(.1,.1)):
    fraction=max(0.,min(1.,float(progress)))
    output=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    if fraction<=0:return output
    rgba=np.asarray(drawing.font_ink.convert('RGBA'))
    if fraction>=1.:
        pixels=rgba
    else:
        times,total=_timing_field(drawing)
        pixels=rgba.copy()
        pixels[:,:,3]=(pixels[:,:,3].astype(np.float32)*
                        (times<=fraction+1e-5)).astype(np.uint8)
    ih,iw=pixels.shape[:2]
    buffer=pixels.tobytes()
    glyph_image=QImage(buffer,iw,ih,iw*4,QImage.Format.Format_RGBA8888).copy()
    scale=min(width*.82/max(1,iw),height*.78/max(1,ih))
    ox=(width-iw*scale)/2
    oy=(height-ih*scale)/2
    p=QPainter(output)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(ox,oy,iw*scale,ih*scale),glyph_image)
    if hand is not None and not hand.isNull() and fraction<1.:
        # Follow the estimated centerline geometry, not a horizontal wipe.
        _,total=_timing_field(drawing)
        left=fraction*total
        tip=None
        for stroke in drawing.strokes:
            length=max(1.,stroke.length)
            if left<=length:
                tip=stroke.portion(min(left,stroke.length))[-1]
                break
            left-=length
        if tip:
            tx=ox+tip[0]*scale;ty=oy+tip[1]*scale
            hw=width*hand_scale;hh=hw*hand.height()/hand.width()
            p.drawImage(QRectF(tx-anchor[0]*hw,ty-anchor[1]*hh,hw,hh),hand)
    p.end()
    return output
