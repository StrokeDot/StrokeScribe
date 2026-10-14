"""Silhouette, region contour and image edge extraction; no external AI."""
import math
import cv2
import numpy as np
from engine import Drawing, Stroke

def _path(contour,sx,sy,epsilon):
    perimeter=cv2.arcLength(contour,True)
    if perimeter<3: return None
    reduced=cv2.approxPolyDP(contour,epsilon,True).reshape(-1,2)
    if len(reduced)<2: return None
    points=[(float(x)*sx,float(y)*sy) for x,y in reduced]
    if len(points)>2: points.append(points[0])
    return points

def trace_image(image,regions=None,detail='medium',mode='auto_trace'):
    width,height=image.size
    limit={'low':160,'medium':256,'high':384}[detail]
    ratio=min(1.,limit/max(width,height))
    w,h=max(2,round(width*ratio)),max(2,round(height*ratio))
    rgba=np.array(image.convert('RGBA'))
    support=(rgba[:,:,3]>0).astype(np.uint8)*255
    support=cv2.resize(support,(w,h),interpolation=cv2.INTER_AREA)
    support=(support>0).astype(np.uint8)*255
    rgb=rgba[:,:,:3].copy(); rgb[rgba[:,:,3]==0]=255
    rgb=cv2.resize(rgb,(w,h),interpolation=cv2.INTER_AREA)
    smooth=cv2.bilateralFilter(rgb,5,35,35)
    gray=cv2.cvtColor(smooth,cv2.COLOR_RGB2GRAY)
    epsilon={'low':1.8,'medium':1.1,'high':.65}[detail]
    sx,sy=width/w,height/h
    candidates=[]
    silhouettes,_=cv2.findContours(support,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(silhouettes,key=lambda c:-abs(cv2.contourArea(c))):
        if cv2.arcLength(c,True)>=6:
            candidates.append((0,c,sx,sy,'silhouette'))
    if mode=='stroke_reconstruction' and regions is not None:
        gw,gh=regions.size
        labels=np.array(regions.labels,np.int32).reshape(gh,gw)
        sizes=[(int((labels==rid).sum()),rid) for rid in range(1,regions.count+1)]
        for area,rid in sorted(sizes,reverse=True):
            if area<4: continue
            cs,_=cv2.findContours((labels==rid).astype(np.uint8),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
            for c in cs:
                if cv2.arcLength(c,True)>=6:
                    candidates.append((1,c,width/gw,height/gh,f'color region {rid}'))
    edges=cv2.Canny(gray,45 if detail=='high' else 70,140)
    # Remove alpha edge duplicates and transparent-area noise.
    interior=cv2.erode(support,np.ones((3,3),np.uint8))
    edges[interior==0]=0
    cs,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    minimum={'low':18,'medium':12,'high':7}[detail]
    for c in cs:
        if cv2.arcLength(c,True)>=minimum:
            candidates.append((2,c,sx,sy,'detail'))
    max_paths={'low':80,'medium':180,'high':320}[detail]
    candidates.sort(key=lambda item:(item[0],-cv2.arcLength(item[1],True)*item[2]))
    strokes=[]; seen=set()
    for _,contour,xscale,yscale,label in candidates:
        points=_path(contour,xscale,yscale,epsilon)
        if not points: continue
        bounds=(min(p[0] for p in points),min(p[1] for p in points),
                max(p[0] for p in points),max(p[1] for p in points))
        # Deduplicate nearly coincident contours, retaining the longer candidate.
        signature=tuple(round(v/max(1.,width/256)) for v in bounds)
        if signature in seen: continue
        seen.add(signature)
        strokes.append(Stroke(f'{label} {len(strokes)+1}',points,
                              '#303946',max(width,height)*.0025))
        if len(strokes)>=max_paths: break
    if not strokes:
        # Flat images still have a plausible perimeter stroke, not a crash.
        strokes=[Stroke('image perimeter',[(0,0),(width,0),(width,height),
                      (0,height),(0,0)],'#303946',max(width,height)*.0025)]
    # Keep major contours first. Within each phase, prefer nearby entry points
    # and reverse a path when that shortens the hidden pen lift.
    ordered=[]; cursor=(0.,0.)
    for category in ('silhouette','color region','detail','image perimeter'):
        pending=[s for s in strokes if s.name.startswith(category)]
        while pending:
            index,reverse=min(((i,r) for i in range(len(pending)) for r in (False,True)),
                key=lambda ir:math.dist(cursor,pending[ir[0]].points[-1 if ir[1] else 0]))
            s=pending.pop(index)
            if reverse: s=Stroke(s.name,list(reversed(s.points)),s.color,s.width)
            ordered.append(s); cursor=s.points[-1]
    warnings=['Reconstructed paths are an approximation, not the original drawing history.']
    if len(candidates)>max_paths:
        warnings.append('Dense/noisy input simplified; path count capped. Try Low detail.')
    if regions and regions.simplified:
        warnings.append('Small color patches merged for simpler painting; original output colors are preserved.')
    return Drawing(ordered,(0.,0.,float(width),float(height)),warnings)
