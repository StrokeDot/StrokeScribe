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
import socket
import time
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
                            },
                    'order': {'type':'integer'},
                },
                'required':['name','box','order'],
            },
        },
    },
    'required':['description','parts'],
}

PROMPT = (
    'Describe this image in one short phrase. List 1 to 8 visible objects or parts, '
    'large shapes first, then details. Use short names. Boxes are integer '
    '[left,top,right,bottom] in 0..1000 image coordinates. Order starts at 1. '
    'Return only this JSON shape: '
    '{"description":"brief","parts":[{"name":"part","box":[10,20,500,900],"order":1}]}. '
    'No explanation, Markdown, or reasoning. /no_think'
)
INITIAL_TOKENS = 3072
RETRY_TOKENS = 6144
CONTEXT_TOKENS = 8192
MAX_REPLY_BYTES = 1_000_000


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


def extract_structured_parts(text):
    """Read a JSON result despite markdown fences or short model preambles.

    The decoded object is still validated by parse_analysis; do not trust
    unconstrained model text as instructions or permit arbitrary eval.
    """
    if isinstance(text,dict):
        return text
    if not isinstance(text,str) or not text.strip():
        raise ValueError('Ollama returned an empty text answer.')
    # Never treat JSON inside hidden reasoning as the final model answer.
    result=re.sub(r'<think\\b[^>]*>.*?</think\\s*>','',text,flags=re.S|re.I)
    result=re.sub(r'<think\\b[^>]*>.*
    if result.startswith('```'):
        result=result[3:]
        if result.lower().startswith('json'):
            result=result[4:]
        if result.rstrip().endswith('```'):
            result=result.rstrip()[:-3]
        result=result.strip()
    try:
        data=json.loads(result)
        if isinstance(data,dict):
            return data
    except (ValueError,TypeError):
        pass
    # Some local vision models prepend a sentence to their JSON.
    decoder=json.JSONDecoder()
    for pos,char in enumerate(result[:16000]):
        if char!='{':continue
        try:
            data,_=decoder.raw_decode(result[pos:])
            if isinstance(data,dict) and isinstance(data.get('parts'),list):
                return data
        except (ValueError,TypeError):
            pass
    raise ValueError('Ollama did not return a complete JSON object with parts.')


def _reply_summary(answer, attempt, budget):
    message=answer.get('message',{}) if isinstance(answer,dict) else {}
    if not isinstance(message,dict):message={}
    content=message.get('content','')
    thinking=message.get('thinking','')
    finish=answer.get('done_reason','unknown') if isinstance(answer,dict) else 'unknown'
    count=answer.get('eval_count','unknown') if isinstance(answer,dict) else 'unknown'
    # Counts only: do not include private image content or reasoning in errors.
    return (f'attempt {attempt}: finish={finish}; generated={count}; limit={budget}; '
            f'answer_chars={len(content) if isinstance(content,str) else 0}; '
            f'thinking_chars={len(thinking) if isinstance(thinking,str) else 0}')


def local_vision_analysis(image, model=DEFAULT_MODEL, timeout=180):
    """Two bounded local attempts; retry exhaustion differently from bad JSON."""
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}(?::[A-Za-z0-9._-]{1,30})?',model):
        raise ValueError('Choose a valid local Ollama model name.')
    timeout=float(timeout)
    if not math.isfinite(timeout) or timeout<=0:raise ValueError('Timeout must be positive.')
    timeout=min(timeout,180.)
    thumbnail=image.convert('RGBA')
    thumbnail.thumbnail((768,768),Image.Resampling.LANCZOS)
    background=Image.new('RGBA',thumbnail.size,'white')
    background.alpha_composite(thumbnail)
    buffer=io.BytesIO();background.convert('RGB').save(buffer,format='PNG')
    encoded=base64.b64encode(buffer.getvalue()).decode('ascii')
    errors=[]; budget=INITIAL_TOKENS; format_value=PART_SCHEMA; retry_kind=''
    deadline=time.monotonic()+timeout*2
    for attempt in range(2):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise RuntimeError('Local AI time budget expired; no further retry was started.')
        prompt=PROMPT
        if attempt:
            prompt+=' Use only 1 to 4 major parts. Keep the complete answer below 400 tokens.'
            if retry_kind=='length':
                prompt+=' Output the final JSON now; do not recheck or explain the image.'
            else:
                prompt+=' The previous answer was unusable. Return one complete JSON object.'
        body={'model':model,'stream':False,'think':False,'format':format_value,
              'keep_alive':'1m',
              'options':{'temperature':0,'num_predict':budget,'num_ctx':CONTEXT_TOKENS},
              'messages':[{'role':'user','content':prompt,'images':[encoded]}]}
        request=Request(OLLAMA_ENDPOINT,data=json.dumps(body).encode('utf-8'),
                        headers={'Content-Type':'application/json'},method='POST')
        try:
            with urlopen(request,timeout=min(timeout,remaining)) as response:
                raw=response.read(MAX_REPLY_BYTES+1)
            if len(raw)>MAX_REPLY_BYTES:
                raise RuntimeError('Ollama response exceeded the 1 MB safety limit; analysis stopped.')
            try:answer=json.loads(raw)
            except (ValueError,UnicodeError):
                errors.append(f'attempt {attempt+1}: malformed Ollama HTTP JSON')
                retry_kind='json';format_value='json'
                continue
        except HTTPError as exc:
            detail=exc.read(500).decode('utf-8','replace')
            if exc.code==404:
                raise RuntimeError(f'Ollama could not find local model {model!r}. Check "ollama list" and the selected model name.') from exc
            schema_error=exc.code in (400,422) and any(
                word in detail.lower() for word in ('schema','format','grammar'))
            if schema_error and attempt==0:
                errors.append(f'attempt 1: schema rejected (HTTP {exc.code}); retrying JSON mode')
                retry_kind='schema';format_value='json'
                continue
            raise RuntimeError(f'Local Ollama HTTP {exc.code}: {detail}. No automatic retry.') from exc
        except (TimeoutError,socket.timeout) as exc:
            raise RuntimeError(f'Local Ollama timed out after up to {timeout:g}s. No automatic retry, to avoid overlapping inference. Wait for Ollama to become idle before retrying.') from exc
        except URLError as exc:
            if isinstance(exc.reason,(TimeoutError,socket.timeout)):
                raise RuntimeError('Local Ollama timed out. No automatic retry; wait for the model to become idle.') from exc
            raise RuntimeError(f'Cannot reach local Ollama at 127.0.0.1:11434. Start Ollama and check "ollama list" for {model}. No cloud request was made.') from exc
        except OSError as exc:
            raise RuntimeError('Local Ollama connection failed. Check the Ollama server; no automatic retry.') from exc
        if not isinstance(answer,dict):
            errors.append(f'attempt {attempt+1}: invalid Ollama response envelope')
            retry_kind='json';format_value='json';continue
        if answer.get('error'):
            raise RuntimeError('Local Ollama reported: '+str(answer['error'])[:400])
        summary=_reply_summary(answer,attempt+1,budget)
        message=answer.get('message',{})
        if not isinstance(message,dict):message={}
        finish=answer.get('done_reason')
        # A length stop is incomplete even if a valid-looking prefix exists.
        if finish=='length':
            has_thinking=bool(message.get('thinking')) or '<think' in str(message.get('content','')).lower()
            reason='generation limit exhausted'
            if has_thinking:reason+=' while reasoning was present despite think:false'
            errors.append(summary+'; '+reason)
            retry_kind='length';budget=RETRY_TOKENS;format_value='json'
            continue
        try:
            if answer.get('done') is False:raise ValueError('Ollama marked the answer incomplete.')
            result=parse_analysis(extract_structured_parts(message.get('content','')),model)
            return result
        except (ValueError,KeyError,AttributeError,TypeError) as exc:
            errors.append(summary+'; '+str(exc))
            retry_kind='json';format_value='json'
    raise ValueError(
        'Local AI could not produce usable image-part JSON after a second attempt. '
        +' | '.join(errors)+
        '. No Auto Trace fallback was used. If thinking_chars is nonzero with an empty '
        'answer, the installed model may not honor think:false. Check Ollama model '
        'details/logs; this build will not download or switch models automatically.')


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
    if not strokes:
        raise ValueError('AI returned parts, but none produced usable semantic contours. No Auto Trace fallback was used.')
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
,'',result,flags=re.S|re.I).strip()
    if result.startswith('```'):
        result=result[3:]
        if result.lower().startswith('json'):
            result=result[4:]
        if result.rstrip().endswith('```'):
            result=result.rstrip()[:-3]
        result=result.strip()
    try:
        data=json.loads(result)
        if isinstance(data,dict):
            return data
    except (ValueError,TypeError):
        pass
    # Some local vision models prepend a sentence to their JSON.
    decoder=json.JSONDecoder()
    for pos,char in enumerate(result[:800]):
        if char!='{':continue
        try:
            data,_=decoder.raw_decode(result[pos:])
            if isinstance(data,dict) and isinstance(data.get('parts'),list):
                return data
        except (ValueError,TypeError):
            pass
    raise ValueError('Ollama did not return a complete JSON object with parts.')


def local_vision_analysis(image, model=DEFAULT_MODEL, timeout=180):
    """Local-only Ollama vision request with defensive JSON parsing/retry."""
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}(?::[A-Za-z0-9._-]{1,30})?',model):
        raise ValueError('Choose a valid local Ollama model name.')
    thumbnail=image.convert('RGBA')
    thumbnail.thumbnail((1024,1024),Image.Resampling.LANCZOS)
    background=Image.new('RGBA',thumbnail.size,'white')
    background.alpha_composite(thumbnail)
    buffer=io.BytesIO()
    background.convert('RGB').save(buffer,format='PNG')
    encoded=base64.b64encode(buffer.getvalue()).decode('ascii')

    errors=[]
    # Some Qwen vision/Ollama combinations ignore a schema or emit empty
    # message.content after extended thinking. The second attempt asks for
    # ordinary JSON, without thinking, if the schema attempt is unusable.
    for attempt in range(2):
        request_body=json.dumps({
            'model':model,
            'stream':False,
            'think':False,
            'format':PART_SCHEMA if attempt==0 else 'json',
            'options':{'temperature':0,'num_predict':2560},
            'messages':[{
                'role':'user',
                'content':PROMPT + (' Respond with a single JSON object ONLY: '
                    '{"description":"...","parts":[{"name":"...","box":[0,0,500,500],"order":1}]}'
                    if attempt else ''),
                'images':[encoded],
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
                    f'Local Ollama model {model!r} was not found. Run: '
                    f'ollama pull {model}') from exc
            if exc.code in (400,422) and attempt==0:
                errors.append('Schema request was unsupported by local Ollama.')
                continue
            raise RuntimeError(f'Local Ollama error HTTP {exc.code}: {detail}') from exc
        except (URLError,TimeoutError,OSError) as exc:
            raise RuntimeError(
                'Local AI is not running or timed out. Start Ollama and verify '
                f'the model with "ollama list" ({model}).') from exc
        try:
            content=answer.get('message',{}).get('content','')
            return parse_analysis(extract_structured_parts(content),model)
        except (ValueError,KeyError,AttributeError,TypeError) as exc:
            done=str(answer.get('done_reason','unknown')) if isinstance(answer,dict) else 'unknown'
            errors.append(f'{str(exc)} (finish: {done})')
    raise ValueError(
        'The local vision model did not produce usable image-part JSON, '
        'even after a second attempt. Please retry or update Ollama. '
        'Reason: '+errors[-1])


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
