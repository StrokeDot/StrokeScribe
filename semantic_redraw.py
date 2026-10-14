"""Optional local vision-model guidance for raster image reconstruction.

A local Ollama vision model proposes semantic parts and a logical drawing
order. OpenCV refines its coarse boxes to pixel regions. The original raster
pixels remain untouched; the AI never generates or replaces the artwork.

Ollama is strictly opt-in. This module sends the provided raster image only
to the fixed local endpoint 127.0.0.1:11434 (not to an online service).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import io
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np
from PIL import Image

from image_regions import RegionMap, segment_regions
from image_trace import trace_image
from engine import Drawing, Stroke

OLLAMA_ENDPOINT = 'http://127.0.0.1:11434/api/chat'
DEFAULT_MODEL = 'qwen3-vl:4b'
MAX_PARTS = 14

PART_SCHEMA = {
    'type': 'object',
    'properties': {
        'description': {'type':'string'},
        'parts': {
            'type':'array',
            'items': {
                'type':'object',
                'properties': {
                    'name': {'type':'string'},
                    'box': {'type':'array','items': {'type':'integer'},
                            'minItems':4,'maxItems':4},
                    'order': {'type':'integer'},
                },
                'required':['name','box','order'],
                'additionalProperties':False,
            },
        },
    },
    'required':['description','parts'],
    'additionalProperties':False,
}

PROMPT = (
    'You are a professional illustrator planning how to CONSTRUCT the exact '
    'provided image, not inventing another picture. Return JSON matching the '
    'schema. Identify up to 12 meaningful VISIBLE parts (for example: cowboy '
    'hat, face, hair, jacket, arm, belt). Each box is [left,top,right,bottom] '
    'in integer coordinates from 0 to 1000, relative to this image. '
    'Avoid one huge box for the entire image and do not invent unseen parts. '
    'Assign order starting at 1 for sensible construction, usually large '
    'major shapes before details and small accents. Include just parts that '
    'can be reasonably distinguished in the pixels. Do not mention image '
    'generation or return markdown.'
)

@dataclass(frozen=True)
class Part:
    name: str
    box: tuple[int,int,int,int]
    order: int

@dataclass(frozen=True)
class Analysis:
    description: str
    parts: tuple[Part, ...]
    model: str


def parse_analysis(data, model=DEFAULT_MODEL):
    """Parse and validate potentially unreliable vision-model coordinates."""
    if not isinstance(data,dict) or not isinstance(data.get('parts'),list):
        raise ValueError('Local AI returned invalid parts JSON. Retry or choose another vision model.')
    clean=[]
    for record in data['parts'][:32]:
        if not isinstance(record,dict):
            continue
        name=record.get('name')
        box=record.get('box')
        order=record.get('order')
        if not isinstance(name,str) or not name.strip() or not isinstance(box,list) or len(box)!=4:
            continue
        if not isinstance(order,int) or isinstance(order,bool):
            continue
        try:
            coords=[max(0,min(1000,int(v))) for v in box]
        except (TypeError,ValueError,OverflowError):
            continue
        left,top,right,bottom=coords
        if right-left<18 or bottom-top<18:
            continue
        clean.append(Part(re.sub(r'[^\w\- /]', '', name, flags=re.UNICODE).strip()[:55],
                          (left,top,right,bottom),max(1,min(99,order))))
    clean=[p for p in clean if p.name]
    clean.sort(key=lambda x:(x.order,(x.box[2]-x.box[0])*(x.box[3]-x.box[1])))
    if not clean:
        raise ValueError('The local AI did not identify usable image parts. Try a clearer illustration.')
    return Analysis(str(data.get('description',''))[:320],tuple(clean[:MAX_PARTS]),model)


def local_vision_analysis(image, model=DEFAULT_MODEL, timeout=180):
    """Ask the user's locally running Ollama vision model for scene structure."""
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}(?::[A-Za-z0-9._-]{1,30})?',model):
        raise ValueError('Choose a valid local Ollama model name.')
    thumbnail=image.convert('RGBA')
    thumbnail.thumbnail((1024,1024),Image.Resampling.LANCZOS)
    # The model sees the background as white, matching the preview of an
    # image with alpha; alpha itself is retained by StrokeScribe for output.
    background=Image.new('RGBA',thumbnail.size,'white')
    background.alpha_composite(thumbnail)
    buffer=io.BytesIO()
    background.convert('RGB').save(buffer,format='PNG')
    request_body=json.dumps({
        'model':model,
        'stream':False,
        'format':PART_SCHEMA,
        'options':{'temperature':0},
        'messages':[{
            'role':'user','content':PROMPT,
            'images':[base64.b64encode(buffer.getvalue()).decode('ascii')],
        }],
    }).encode('utf-8')
    request=Request(OLLAMA_ENDPOINT,data=request_body,
                    headers={'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(request,timeout=timeout) as response:
            answer=json.load(response)
    except HTTPError as exc:
        detail=exc.read(400).decode('utf-8','replace')
        if exc.code==404:
            raise RuntimeError(
                f'Local Ollama model {model!r} was not found. In a terminal run: '
                f'ollama pull {model}') from exc
        raise RuntimeError(f'Local Ollama error HTTP {exc.code}: {detail}') from exc
    except (URLError,TimeoutError,OSError) as exc:
        raise RuntimeError(
            'Local AI is not running. Install/start Ollama and run '
            f'\"ollama pull {model}\" once. AI Redraw uses a local model; '
            'your artwork is not sent to a cloud service.') from exc
    try:
        raw=json.loads(answer['message']['content'])
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('Local Ollama returned invalid JSON. Retry the analysis.') from exc
    return parse_analysis(raw,model)


def _part_rect(part,w,h):
    x1,y1,x2,y2=part.box
    left=max(0,min(w-2,round(x1*w/1000)))
    top=max(0,min(h-2,round(y1*h/1000)))
    right=max(left+2,min(w,round(x2*w/1000)))
    bottom=max(top+2,min(h,round(y2*h/1000)))
    return left,top,right-left,bottom-top


def semantic_masks(image, analysis, detail='medium'):
    """Refine AI semantic boxes against pixels; never use raw boxes as fills.

    GrabCut may fail on flat colored drawings or heavily overlapping boxes;
    fall back to image-color components within the box, never a painted
    rectangle. The output label map preserves every original alpha pixel.
    """
    regions=segment_regions(image,detail)
    gw,gh=regions.size
    original=np.asarray(image.convert('RGBA').resize((gw,gh),Image.Resampling.NEAREST))
    alpha=original[:,:,3]>0
    white=np.full((gh,gw,3),255,np.uint8)
    white[alpha]=original[alpha,:3]
    rgb=cv2.cvtColor(white,cv2.COLOR_RGB2BGR)
    original_labels=np.asarray(regions.labels,dtype=np.int32).reshape(gh,gw)
    assignments=np.zeros((gh,gw),dtype=np.int32)
    extracted=[]
    parts=analysis.parts[:MAX_PARTS]
    for n,part in enumerate(parts,1):
        x,y,w,h=_part_rect(part,gw,gh)
        candidates=np.zeros((gh,gw),np.uint8)
        if w>=5 and h>=5 and w*h>=100:
            mask=np.zeros((gh,gw),np.uint8)
            try:
                cv2.grabCut(rgb,mask,(x,y,w,h),None,None,3,cv2.GC_INIT_WITH_RECT)
                foreground=np.isin(mask,(cv2.GC_FGD,cv2.GC_PR_FGD)) & alpha
                foreground[:y,:]=False
                foreground[y+h:,:]=False
                foreground[:,:x]=False
                foreground[:,x+w:]=False
                area=int(np.count_nonzero(foreground))
                if 5<=area<=w*h*.96:
                    candidates=foreground.astype(np.uint8)
            except cv2.error:
                pass
        if not candidates.any():
            # Reuse actual image color-region boundaries as a conservative
            # fallback, filtered by the requested semantic box.
            local=original_labels[y:y+h,x:x+w]
            mid=local[max(0,h//2-2):min(h,h//2+3),
                      max(0,w//2-2):min(w,w//2+3)]
            ids,counts=np.unique(mid[mid>0],return_counts=True)
            if len(ids):
                chosen=int(ids[np.argmax(counts)])
                patch=(local==chosen)&alpha[y:y+h,x:x+w]
                candidates[y:y+h,x:x+w]=patch.astype(np.uint8)
        extracted.append(candidates)
    # Broad objects first, then smaller detected details override their
    # pixels. The masks never paint outside actual source-image alpha.
    indices=sorted(range(len(parts)),key=lambda i:(
        -((parts[i].box[2]-parts[i].box[0])*
          (parts[i].box[3]-parts[i].box[1])),i))
    for index in indices:
        assignments[(extracted[index]>0)&alpha]=index+1
    # Preserve ALL remaining source pixels as standard color-regions.
    remaining=(assignments==0)&alpha
    assignments[remaining]=len(parts)+original_labels[remaining]
    map_object=RegionMap((gw,gh),tuple(map(int,assignments.ravel())),
                         int(assignments.max()),regions.simplified)
    # A model box may have no matching pixels. Don't claim to have drawn it.
    valid=[i for i,part in enumerate(parts,1) if np.any(assignments==i)]
    return map_object,extracted,valid


def ai_guided_drawing(image,analysis,detail='medium'):
    """Create semantically named paths plus unchanged full-color painting data."""
    from adaptive_hand import qimage
    region_map,masks,valid=semantic_masks(image,analysis,detail)
    w,h=image.size
    gw,gh=region_map.size
    strokes=[]
    # Semantic parts are intentionally first, not generic edge contours:
    # this visibly changes the order and lets the user reorder parts.
    for index in valid:
        part=analysis.parts[index-1]
        mask=(masks[index-1]*255).astype(np.uint8)
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        contours=sorted(contours,key=lambda c:-cv2.contourArea(c))[:3]
        for contour in contours:
            if len(contour)<3 or cv2.arcLength(contour,True)<8:
                continue
            eps={'low':1.8,'medium':1.0,'high':.6}[detail]
            points=cv2.approxPolyDP(contour,eps,True).reshape(-1,2)
            if len(points)<3: continue
            coords=[(float(px)*w/gw,float(py)*h/gh) for px,py in points]
            coords.append(coords[0])
            strokes.append(Stroke(f'AI {index:02d} / {part.name}',
                coords,'#303946',max(w,h)*.0025))
    # Include fine image detail after semantic major forms, not duplicate
    # whole-image silhouettes or anonymous colored-region boundaries.
    detail_drawing=trace_image(image,detail=detail,mode='auto_trace')
    limit={'low':30,'medium':65,'high':110}[detail]
    for stroke in detail_drawing.strokes:
        if not stroke.name.startswith('detail'):
            continue
        strokes.append(Stroke(f'Fine detail {len(strokes)+1}',stroke.points,
                              stroke.color,stroke.width))
        if sum(s.name.startswith('Fine detail') for s in strokes)>=limit:
            break
    if not strokes:
        raise ValueError('AI found parts, but no usable contours. Try Auto Trace for this image.')
    d=Drawing(strokes,(0.,0.,float(w),float(h)),[
        f'AI-guided redraw: {len(valid)} visible semantic parts identified by local {analysis.model}.',
        'Pixel contours and fills are estimates, not original artist strokes.',
    ])
    d.image_regions=region_map
    d.image_region_priority=True
    d.image_semantic_order=tuple(valid)
    d.image_semantic_names=tuple((i,analysis.parts[i-1].name) for i in valid)
    d.source_kind='image'
    d.source_mode='ai_redraw'
    return d,qimage(image)
