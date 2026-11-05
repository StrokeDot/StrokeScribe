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
    stem_turn=math.cos(math.radians(35))
    def walk(a,b):
        route=[a,b]
        used.add(edge(a,b))
        while len(route)<8000:
            options=free(route[-1])
            if not options:break
            if len(route)>10:
                # exp.208: a long down stroke that bends away without a join (the stem of a
                # "d" rounding into its bowl) ends at the bend too.
                whole=_direction(route,len(route)-1); local=_direction(route,4)
                if whole[1]>.9 and local[1]<.45:break
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
                # exp.208: a straight down stroke (the stem of b, d, h, p…) ends at a join
                # where the line turns away, instead of rounding the corner into the bowl
                # (the bowl is then written on its own, from the top, like a hand does).
                whole=_direction(route,len(route)-1)
                limit=stem_turn if len(route)>6 and whole[1]>.9 else turn
                if d!=(0.,0.) and score(best)<limit and len(route)>3:
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
        # exp.208 (the user: a "b" looked like an "L" while it was written): a bowl or arch
        # whose two ends both sit on what is already written (the bowl of b, p, d) is written
        # like a hand does it: from its upper end, round, and back down to the line.
        reach=2.5*max(1.,scale)
        def on_ink(q):
            return any(math.dist(q,r)<=reach for done in chain for r in done[::2])
        bridge=len(chosen)>6 and on_ink(chosen[0]) and on_ink(chosen[-1])
        if bridge and chosen[-1][1]<chosen[0][1]-reach:
            chosen=list(reversed(chosen))
        # Pieces that touch (skeleton joins) are one pen movement, not a new stroke.
        if math.dist(chain[-1][-1],chosen[0])<=1.5:
            chain[-1]=chain[-1]+chosen[1:]
        else:
            chain.append(chosen)
    return chain


def _ring_from(ring,start,leftwards):
    """The closed ring starting at index `start`, going first to the left (anticlockwise
    from the top) or to the right, back to its start."""
    ring=ring[start:]+ring[:start]
    look=min(4,len(ring)-1)
    first_left=ring[look][0]<ring[-look][0]
    if first_left!=leftwards:
        ring=[ring[0]]+ring[1:][::-1]
    return ring+[ring[0]]


def _bowl_and_stem(pieces,gid,scale):
    """exp.208: a glyph that is one closed loop and one line meeting at one join (a, b, d,
    p, q, g in many handwriting fonts), written like a hand does: with the stem on the right
    the bowl comes first, anticlockwise from its top, then the stem down; with the stem on
    the left the stem is written down first, then the bowl clockwise."""
    loops=[r for r in pieces if len(r)>8 and (r[0]==r[-1] or (r[0] in gid and r[-1] in gid and gid[r[0]]==gid[r[-1]]))]
    lines=[r for r in pieces if r not in loops]
    if len(loops)!=1 or len(lines)!=1:return None
    loop,line=loops[0],lines[0]
    join=loop[0]
    if not (math.dist(line[0],join)<=3*max(1.,scale) or math.dist(line[-1],join)<=3*max(1.,scale)):return None
    if math.dist(line[-1],join)<math.dist(line[0],join):line=line[::-1]      # line starts at the join
    if abs(line[-1][1]-line[0][1])<1.3*abs(line[-1][0]-line[0][0]):return None   # not a stem (e's tail)
    ring=loop[:-1] if loop[0]==loop[-1] else loop
    cx=sum(p[0] for p in ring)/len(ring)
    right=join[0]>cx
    top=min(range(len(ring)),key=lambda j:(ring[j][1],-ring[j][0] if right else ring[j][0]))
    j=min(range(len(ring)),key=lambda i:math.dist(ring[i],join))
    tail_down=line[-1][1]>join[1]
    def f(path):return [(float(x),float(y)) for x,y in path]
    if right:
        # a, d, q, g: the bowl anticlockwise from its top, then the stem
        bowl=_ring_from(ring,top,True)
        if tail_down:
            # down the right side again to the join, then on down the stem (one movement)
            back=_ring_from(ring,top,False)
            k=next((i for i,p in enumerate(back) if math.dist(p,join)<=1.5),None)
            down=back[:k+1] if k is not None else [join]
            return [f(bowl+down[1:]+line[1:])]
        return [f(bowl),f(line[::-1])]            # d: then the stem from its top down
    # b, p: the stem first
    if tail_down:
        # p: from the top of the bowl's left side down to the join and the descender,
        # then the bowl clockwise from its top
        side=_ring_from(ring,top,False)[::-1]      # leftwards = down the left side first? choose by y
        a=_ring_from(ring,top,True);b=_ring_from(ring,top,False)
        down_side=a if a[min(3,len(a)-1)][1]>=b[min(3,len(b)-1)][1] else b
        k=next((i for i,p in enumerate(down_side) if math.dist(p,join)<=1.5),None)
        stem=(down_side[:k+1] if k is not None else [ring[top]])+line[1:]
        return [f(stem),f(_ring_from(ring,top,False))]
    # b: the stem down to the join, then round the bowl and back
    j_ring=_ring_from(ring,j,True);k_ring=_ring_from(ring,j,False)
    bowl=j_ring if j_ring[min(3,len(j_ring)-1)][1]>k_ring[min(3,len(k_ring)-1)][1] else k_ring
    return [f(line[::-1]+bowl[1:])]


_PLAN_DEBUG=None


def _pen_plan(binary,scale=1.):
    """exp.208 (the user: real fonts should be written like a real hand): the pen strokes of
    one thinned glyph, planned on its shape as a whole.

    The skeleton is cut into pieces between its ends and joins. At every join the pieces that
    go on smoothly through it are joined into one stroke (an "o" is one loop, the stem of a
    "b" one line). Then each stroke is written the way a hand writes it: down strokes go
    down, loops start at their top and go round anticlockwise, a bowl or arch that hangs
    between two written lines starts from its upper end; a bowl with a stem on its right
    (a, d, g, q) comes before that stem; otherwise from the top left."""
    pts={(int(x),int(y)) for y,x in zip(*np.nonzero(binary))}
    if not pts:return []
    def adjacent(p):
        x,y=p;out=[]
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                q=(x+dx,y+dy)
                if not (dx or dy) or q not in pts:continue
                if dx and dy and ((x+dx,y) in pts or (x,y+dy) in pts):continue
                out.append(q)
        return out
    graph={p:adjacent(p) for p in pts}
    node={p for p,n in graph.items() if len(n)!=2}
    # Pieces between nodes (ends and joins); loops with no node at all on their own.
    used=set()
    def edge(a,b):return (a,b) if a<b else (b,a)
    pieces=[]
    def trace(a,b):
        route=[a,b];used.add(edge(a,b))
        while route[-1] not in node:
            nxt=[q for q in graph[route[-1]] if edge(route[-1],q) not in used]
            if not nxt:break
            used.add(edge(route[-1],nxt[0]));route.append(nxt[0])
            if len(route)>20000:break
        return route
    for p in sorted(node):
        for q in graph[p]:
            if edge(p,q) not in used:pieces.append(trace(p,q))
    for p in sorted(pts):
        for q in graph[p]:
            if edge(p,q) not in used:
                loop=trace(p,q)
                pieces.append(loop)
    def length(path):return sum(math.dist(a,b) for a,b in zip(path,path[1:]))
    # Joins a few pixels apart are one join (a thinned crossing is often 2-3 pixels).
    near=2.5*max(1.,scale)
    groups=[]
    for p in sorted(node):
        if len(graph[p])==1:continue
        for g in groups:
            if any(math.dist(p,q)<=near for q in g):g.append(p);break
        else:groups.append([p])
    gid={}
    for i,g in enumerate(groups):
        for p in g:gid[p]=i
    def end_key(p):
        return ('j',gid[p]) if p in gid else ('e',p)
    # Tiny pieces between two pixels of the same join are part of the join.
    pieces=[r for r in pieces if not (len(r)<=int(near)+3 and r[0] in gid and r[-1] in gid and gid[r[0]]==gid[r[-1]])]
    # Short spurs (an end hanging off a join) are artefacts of the thinning.
    spur=4.*max(1.,scale)
    def is_spur(r):
        return length(r)<spur and ((r[0] in gid and len(graph[r[-1]])==1) or (r[-1] in gid and len(graph[r[0]])==1))
    if len(pieces)>1:
        pieces=[r for r in pieces if not is_spur(r)] or pieces
    if not pieces:return []
    special=_bowl_and_stem(pieces,gid,scale)
    if special:
        return special
    # Directions leaving each join.
    def leave(r,at_start):
        seq=r if at_start else r[::-1]
        a=seq[0];b=seq[min(len(seq)-1,max(3,int(6*max(1.,scale))))]
        dx,dy=b[0]-a[0],b[1]-a[1];n=math.hypot(dx,dy)
        return (dx/n,dy/n) if n else (0.,0.)
    ends={}
    for i,r in enumerate(pieces):
        for at_start,p in ((True,r[0]),(False,r[-1])):
            k=end_key(p)
            if k[0]=='j':ends.setdefault(k,[]).append((i,at_start,leave(r,at_start)))
    # At each join, pair the pieces that go straight on (most opposite directions).
    partner={}
    for k,items in ends.items():
        pairs=[]
        for x in range(len(items)):
            for y in range(x+1,len(items)):
                a,b=items[x],items[y]
                if a[0]==b[0] and a[1]!=b[1] and len(items)>2:continue
                dot=a[2][0]*b[2][0]+a[2][1]*b[2][1]
                pairs.append((dot,x,y))
        taken=set()
        for dot,x,y in sorted(pairs):
            if dot>-.5:break                        # turns more than 60 degrees: a new stroke
            if x in taken or y in taken:continue
            taken|={x,y}
            a,b=items[x],items[y]
            partner[(a[0],a[1])]=(b[0],b[1]);partner[(b[0],b[1])]=(a[0],a[1])
    # Chain the pieces into strokes.
    seen=set();strokes=[]
    def oriented(i,from_start):
        return pieces[i] if from_start else pieces[i][::-1]
    for i in range(len(pieces)):
        if i in seen:continue
        # walk back to an end of the chain
        cur,at=i,True
        for _ in range(len(pieces)):
            back=partner.get((cur,at))
            if back is None or back[0]==i:break
            cur,at=back[0],not back[1]
        if (cur,at) in partner and partner[(cur,at)][0]==i and cur!=i:
            cur,at=i,True                           # a closed chain: start anywhere
        path=[];closed=False
        c,a=cur,at
        while c not in seen:
            seen.add(c)
            seg=oriented(c,a)
            path+=seg if not path else seg[1:]
            nxt=partner.get((c,not a))
            if nxt is None:break
            if nxt[0] in seen:closed=nxt[0]==cur;break
            c,a=nxt[0],nxt[1]
        if len(path)>=2:
            strokes.append(dict(path=path,closed=closed or (len(path)>8 and math.dist(path[0],path[-1])<=1.5)))
    for st in strokes:
        path=st['path']
        if st['closed']:
            # A loop starts at its top and goes round anticlockwise (to the left first).
            ring=path[:-1] if path[0]==path[-1] else path
            top=min(range(len(ring)),key=lambda j:(ring[j][1],-ring[j][0]))
            ring=ring[top:]+ring[:top]
            if len(ring)>4 and ring[min(4,len(ring)-1)][0]>ring[-min(4,len(ring)-1)][0]:
                ring=[ring[0]]+ring[1:][::-1]
            st['path']=ring+[ring[0]]
        else:
            st['path']=_orient(path)
    drawn=[]
    def on_ink(q,skip):
        reach=2.5*max(1.,scale)
        return any(math.dist(q,r)<=reach for o in strokes if o is not skip for r in o['path'][::2])
    for st in strokes:
        path=st['path']
        if not st['closed'] and len(path)>6 and on_ink(path[0],st) and on_ink(path[-1],st):
            (x0,y0),(x1,y1)=path[0],path[-1]
            if abs(y1-y0)<=abs(x1-x0)*1.2 or True:
                if y1<y0-2:st['path']=path[::-1]     # a bowl or arch between lines: from its upper end
    # Order: a bowl with a stem on its right first (a, d, g, q), then top-left first.
    def box(path):
        xs=[p[0] for p in path];ys=[p[1] for p in path]
        return min(xs),min(ys),max(xs),max(ys)
    def vertical(st):
        (x0,y0),(x1,y1)=st['path'][0],st['path'][-1]
        return not st['closed'] and abs(y1-y0)>abs(x1-x0)*2.5
    def top_left(p):return (p[1]+p[0]*.35,p[0])
    order=sorted(strokes,key=lambda st:top_left(st['path'][0]))
    for st in list(order):
        if not vertical(st):continue
        sx=sum(p[0] for p in st['path'])/len(st['path'])
        for other in order:
            if other is st or vertical(other):continue
            l,t,r,b=box(other['path'])
            if r<=sx+2.5*max(1.,scale) and l<sx-4 and (r-l)>4 and \
                    t<max(p[1] for p in st['path']) and b>min(p[1] for p in st['path']):
                if order.index(other)>order.index(st):
                    order.remove(other);order.insert(order.index(st),other)
    if _PLAN_DEBUG is not None:
        _PLAN_DEBUG.append(([(len(r),r[0],r[-1]) for r in pieces],[(st['closed'],st['path'][0],st['path'][-1],len(st['path'])) for st in order],dict(partner)))
    out=[]
    for st in order:
        path=[(float(x),float(y)) for x,y in st['path']]
        if out and math.dist(out[-1][-1],path[0])<=1.5:
            out[-1]=out[-1]+path[1:]
        else:
            out.append(path)
    return out


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
            try:
                paths=_pen_plan(skeleton,point_size/68.)            # exp.208
            except Exception:
                paths=[]
            if not paths:
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


def _pen_radius(drawing):
    """Half the width of the font's strokes, in ink pixels (the pen tip's size)."""
    cached=getattr(drawing,'font_pen_radius',None)
    if cached is not None:return cached
    alpha=np.asarray(drawing.font_ink.getchannel('A'))>128
    radius=2.
    if alpha.any():
        inside=cv2.distanceTransform(alpha.astype(np.uint8),cv2.DIST_L2,3)
        ridge=inside[_thin(alpha)] if alpha.sum()<4_000_000 else inside[alpha]
        if ridge.size:radius=float(np.median(ridge))
    drawing.font_pen_radius=max(1.,radius)
    return drawing.font_pen_radius


def _written(drawing,fraction):
    """exp.208 (the user: the letters of a real font looked broken while they were written):
    how much of each ink pixel is written at `fraction` (0..1). The written part ends in a
    round pen tip where the pen is, and its edge is smooth, instead of a jagged straight
    cut through the letter."""
    timing,owner,_=_ink_ownership(drawing)
    done=((owner>=0)&(timing<=fraction+1e-7)).astype(np.float32)
    tip,pen_down,index=_pen_state(drawing,fraction)
    radius=_pen_radius(drawing)
    if pen_down and index is not None:
        h,w=done.shape
        r=int(math.ceil(radius*1.15))
        x0,x1=max(0,int(tip[0])-r-1),min(w,int(tip[0])+r+2)
        y0,y1=max(0,int(tip[1])-r-1),min(h,int(tip[1])+r+2)
        if x1>x0 and y1>y0:
            yy,xx=np.mgrid[y0:y1,x0:x1]
            disk=((xx-tip[0])**2+(yy-tip[1])**2<=(radius*1.1)**2)&(owner[y0:y1,x0:x1]==index)
            done[y0:y1,x0:x1]=np.maximum(done[y0:y1,x0:x1],disk.astype(np.float32))
    sigma=max(.6,min(2.5,radius*.28))
    return np.clip(cv2.GaussianBlur(done,(0,0),sigma)*1.15,0.,1.)


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
        pixels[:,:,3]=(pixels[:,:,3].astype(np.float32)*_written(drawing,fraction)).astype(np.uint8)
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
