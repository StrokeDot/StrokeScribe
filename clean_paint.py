"""Experimental clean contour color reveal.

Unlike the original guided effect, this groups labeled SVG paths where possible,
hides the painting hand during pen-up transfers, and fills colors outward from
the contours. The first painting point remains the final drawing-stroke endpoint.
"""
from __future__ import annotations

import heapq
import math
from collections import OrderedDict

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from stroke_guided import project

_CACHE = OrderedDict()
_NEIGHBORS = ((1, 0, 1.), (-1, 0, 1.), (0, 1, 1.), (0, -1, 1.),
              (1, 1, 1.4142), (1, -1, 1.4142),
              (-1, 1, 1.4142), (-1, -1, 1.4142))


def _group(stroke):
    """Use descriptive SVG IDs when available; otherwise spatial proximity."""
    name = stroke.name.lower().split(' / ')[0]
    for label in ('microphone', 'headband', 'left', 'right'):
        if label in name:
            return label
    return None


def clean_route(drawing, width, height):
    """(x, y, painting) waypoints, grouped into deliberate contour passes.

    The last stroke is traversed backwards first; the rest are grouped by
    descriptive SVG IDs when available, or visited by nearest endpoint.
    Long transfers are pen-up segments, never painting strokes.
    """
    if not drawing.strokes:
        raise ValueError('The SVG needs at least one stroke.')
    strokes = drawing.strokes
    last = strokes[-1]
    paths = [(last, list(reversed(last.points)))]
    cursor = last.points[0]
    active_group = _group(last)
    remaining = list(strokes[:-1])

    while remaining:
        candidates = [(index, stroke) for index, stroke in enumerate(remaining)
                      if active_group is not None and _group(stroke)==active_group]
        if not candidates:
            candidates = list(enumerate(remaining))
        distance, chosen_index, reverse = min(
            (math.dist(cursor, s.points[-1] if backwards else s.points[0]),
             idx, backwards)
            for idx, s in candidates for backwards in (False, True))
        chosen = remaining.pop(chosen_index)
        points = list(reversed(chosen.points)) if reverse else chosen.points
        paths.append((chosen, points))
        cursor = points[-1]
        active_group = _group(chosen)

    waypoints = []
    for stroke, points in paths:
        projected = [project(drawing,width,height,p) for p in points]
        reduced = [projected[0]]
        # Sample complex Bezier contours smoothly without a huge path cache.
        for p in projected[1:-1]:
            if math.dist(reduced[-1],p)>=2.5:
                reduced.append(p)
        if reduced[-1] != projected[-1]:
            reduced.append(projected[-1])
        if not waypoints:
            waypoints.append((*reduced[0], False))
        elif math.dist(waypoints[-1][:2],reduced[0])>0.01:
            waypoints.append((*reduced[0], False))
        for p in reduced[1:]:
            if math.dist(waypoints[-1][:2],p)>0.01:
                waypoints.append((*p, True))
    return waypoints


def _lengths(route):
    # Pen-lift transfers take a short portion of the timeline but do not paint.
    result=[]
    for a,b in zip(route,route[1:]):
        distance=math.dist(a[:2],b[:2])
        result.append(distance if b[2] else min(distance*.22,30.))
    return result


def clean_hand_tip(route, progress):
    """Hide the hand on all repositioning moves; show it only on contours."""
    if not route:
        return None
    progress=max(0.,min(1.,float(progress)))
    lengths=_lengths(route)
    remaining=progress*sum(lengths)
    if not lengths:
        return route[0][:2]
    for i,duration in enumerate(lengths,1):
        if remaining<=duration:
            if not route[i][2]:
                return None
            a,b=route[i-1],route[i]
            fraction=remaining/duration if duration else 1.
            return (a[0]+(b[0]-a[0])*fraction,
                    a[1]+(b[1]-a[1])*fraction)
        remaining-=duration
    return route[-1][:2]


def _build_field(drawing,width,height,rect,brush_width):
    gw=250
    gh=max(48,min(330,round(gw*rect.height()/max(1.,rect.width()))))
    route=clean_route(drawing,width,height)
    lengths=_lengths(route)
    total=max(1e-6,sum(lengths))
    field=[float('inf')]*(gw*gh)
    pending=[]

    def seed(x,y,arrival):
        ix=max(0,min(gw-1,round((x-rect.left())*gw/max(1.,rect.width())-.5)))
        iy=max(0,min(gh-1,round((y-rect.top())*gh/max(1.,rect.height())-.5)))
        cell=iy*gw+ix
        if arrival<field[cell]:
            field[cell]=arrival
            heapq.heappush(pending,(arrival,cell))

    seed(*route[0][:2],0.)
    elapsed=0.
    step=max(.8,rect.width()/gw)
    for i,length in enumerate(lengths,1):
        a,b=route[i-1],route[i]
        if b[2]:
            distance=math.dist(a[:2],b[:2])
            count=max(1,math.ceil(distance/step))
            for j in range(count+1):
                fraction=j/count
                seed(a[0]+(b[0]-a[0])*fraction,
                     a[1]+(b[1]-a[1])*fraction,
                     .75*(elapsed+length*fraction)/total)
        elapsed+=length

    # Propagate a region-growing reveal away from the SVG paths. Pen-up lines
    # never seed the field, so connecting unrelated parts does not paint.
    expansion=.25/max(2.,min(gw,gh)*max(.02,min(.5,brush_width)))
    while pending:
        t,cell=heapq.heappop(pending)
        if t>field[cell]+1e-10:
            continue
        x,y=cell%gw,cell//gw
        for dx,dy,distance in _NEIGHBORS:
            xx,yy=x+dx,y+dy
            if not(0<=xx<gw and 0<=yy<gh):
                continue
            neighbor=yy*gw+xx
            new=t+expansion*distance
            if new<field[neighbor]:
                field[neighbor]=new
                heapq.heappush(pending,(new,neighbor))
    maximum=max(field)
    if not math.isfinite(maximum) or maximum<=0:
        maximum=1.
    packed=bytes(max(0,min(254,round(254*t/maximum))) for t in field)
    return gw,gh,packed,route


def _plan(drawing,width,height,rect,brush_width):
    identity=tuple((id(s),len(s.points),s.points[0],s.points[-1],s.name)
                   for s in drawing.strokes)
    key=(identity,width,height,round(rect.x(),2),round(rect.y(),2),
         round(rect.width(),2),round(rect.height(),2),round(brush_width,3))
    if key not in _CACHE:
        _CACHE[key]=_build_field(drawing,width,height,rect,brush_width)
        if len(_CACHE)>3:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return _CACHE[key]


def clean_paint_mask(drawing,width,height,rect,progress,brush_width):
    """Return transparent canvas coverage mask and hand tip (or None on lifts)."""
    progress=max(0.,min(1.,float(progress)))
    mask=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    if progress>=1.:
        painter=QPainter(mask)
        painter.fillRect(rect,Qt.GlobalColor.white)
        painter.end()
        return mask,None
    gw,gh,data,route=_plan(drawing,width,height,rect,brush_width)
    tip=clean_hand_tip(route,progress)
    if progress<=0.:
        return mask,tip
    table=[max(0,min(255,round((progress*254-i+4)*255/8)))
           for i in range(256)]
    alpha=Image.frombytes('L',(gw,gh),data).point(table)
    rgba=Image.new('RGBA',(gw,gh),(255,255,255,0))
    rgba.putalpha(alpha)
    pixels=rgba.tobytes()
    small=QImage(pixels,gw,gh,gw*4,QImage.Format.Format_RGBA8888).copy()
    painter=QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(rect,small)
    painter.end()
    return mask,tip
