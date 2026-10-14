"""Coarse color regions for path-constrained raster painting.

Quantization is used ONLY to plan strokes. Rendering retains original RGBA.
"""
from dataclasses import dataclass
import cv2
import numpy as np
from PIL import Image, ImageFilter
from adaptive_hand import GRID_LIMIT

@dataclass(frozen=True)
class RegionMap:
    size: tuple
    labels: tuple
    count: int
    simplified: bool

def segment_regions(image, detail='medium'):
    w,h=image.size
    ratio=min(1.,GRID_LIMIT/max(w,h))
    gw,gh=max(1,int(np.ceil(w*ratio))),max(1,int(np.ceil(h*ratio)))
    rgba=np.array(image.convert('RGBA'))
    ys,xs=np.nonzero(rgba[:,:,3])
    if not len(xs):
        raise ValueError('The image is fully transparent.')
    gx=np.minimum(gw-1,(2*xs+1)*gw//(2*w))
    gy=np.minimum(gh-1,(2*ys+1)*gh//(2*h))
    support=np.zeros((gh,gw),np.uint8); support[gy,gx]=1
    # Composite transparent margins only for color analysis, never for output.
    white=Image.new('RGBA',image.size,'white'); white.alpha_composite(image.convert('RGBA'))
    small=white.convert('RGB').resize((gw,gh),Image.Resampling.LANCZOS)
    small=small.filter(ImageFilter.MedianFilter(3))
    palette_count={'low':6,'medium':12,'high':20}[detail]
    quantized=small.quantize(colors=palette_count,method=Image.Quantize.MEDIANCUT,
                            dither=Image.Dither.NONE)
    colors=np.asarray(quantized)
    raw=np.zeros((gh,gw),np.int32); next_id=1
    regions=[]
    for color in np.unique(colors[support>0]):
        mask=((colors==color)&(support>0)).astype(np.uint8)
        n,labels,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=4)
        for component in range(1,n):
            cells=np.flatnonzero(labels.ravel()==component)
            regions.append((int(stats[component,cv2.CC_STAT_AREA]),cells))
    # Bound noise: small islands join nearest major regions within alpha.
    min_area={'low':22,'medium':12,'high':5}[detail]
    major=sorted((r for r in regions if r[0]>=min_area),key=lambda r:-r[0])[:64]
    if not major:
        major=[max(regions,key=lambda r:r[0])]
    for _,cells in major:
        raw.ravel()[cells]=next_id; next_id+=1
    # Multi-source BFS assigns leftover analysis pixels, respecting transparent
    # gaps. This is segmentation only; it never reveals pixels in playback.
    from collections import deque
    q=deque(map(int,np.flatnonzero(raw)))
    while q:
        cell=q.popleft(); x,y=cell%gw,cell//gw
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            xx,yy=x+dx,y+dy
            if 0<=xx<gw and 0<=yy<gh and support[yy,xx] and not raw[yy,xx]:
                raw[yy,xx]=raw[y,x]; q.append(yy*gw+xx)
    # Retain disconnected tiny alpha components rather than dropping accents.
    unseen=((support>0)&(raw==0)).astype(np.uint8)
    n,labels=cv2.connectedComponents(unseen,connectivity=4)
    for i in range(1,n):
        raw[labels==i]=next_id; next_id+=1
    return RegionMap((gw,gh),tuple(map(int,raw.ravel())),next_id-1,
                     len(regions)>len(major)+n-1)
