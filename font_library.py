"""Google Fonts downloads and approximate pen-centerline lettering.

Google Fonts are openly licensed rather than "copyright-free." We save each
font's unmodified license with its original font file and install fonts only
on explicit user request. The original bundled single-line alphabet remains
available offline. Raster skeleton tracing is APPROXIMATE handwriting,
not original glyph stroke data.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
import shutil
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from engine import Drawing, Stroke

STARTER_FONTS=(
    'Caveat','Kalam','Patrick Hand','Indie Flower','Dancing Script',
    'Sacramento','Gochi Hand','Architects Daughter',
    'Shadows Into Light','Reenie Beanie',
)
MAX_FONT_BYTES=12_000_000
API_ROOT='https://api.github.com/repos/google/fonts/contents'
BINARY_HOST='https://raw.githubusercontent.com/google/fonts/'
FONT_SUFFIXES={'.ttf','.otf'}


def font_dir():
    # Shared between StrokeScribe release folders. Deleting the app does not
    # delete user-chosen fonts from LOCALAPPDATA.
    appdata=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.strokescribe')))
    return appdata/'StrokeScribe'/'fonts'


def font_slug(family):
    slug=re.sub(r'[^a-z0-9]','',family.lower())
    if not 2<=len(slug)<=60:
        raise ValueError('Choose a Google Fonts family name such as Caveat or Kalam.')
    return slug


def installed_font(family):
    dest=font_dir()/font_slug(family)
    if not dest.is_dir(): return None
    for path in sorted(dest.glob('*')):
        if path.suffix.lower() in FONT_SUFFIXES and path.stat().st_size>1000:
            return path
    return None


def _read_url(url,binary=False):
    req=Request(url,headers={
        'User-Agent':'StrokeScribe-font-installer/0.5.3',
        'Accept':'application/vnd.github+json' if not binary else 'application/octet-stream',
    })
    with urlopen(req,timeout=30) as response:
        data=response.read(MAX_FONT_BYTES+1)
    if len(data)>MAX_FONT_BYTES:
        raise ValueError('This font is too large to download automatically.')
    return data


def download_google_font(family):
    """Fetch one genuine Google Fonts family (font and original license).

    Supports open font licenses as organized in Google's public repository.
    Does not download a font without its accompanying upstream license.
    """
    slug=font_slug(family)
    existing=installed_font(family)
    if existing: return existing
    items=None
    for collection in ('ofl','apache','ufl'):
        url=f'{API_ROOT}/{collection}/{slug}?ref=main'
        try:
            items=json.loads(_read_url(url))
            if isinstance(items,list): break
        except HTTPError as exc:
            if exc.code==404: continue
            raise RuntimeError(f'Google Fonts returned HTTP {exc.code}; please retry.') from exc
        except (URLError,TimeoutError,OSError) as exc:
            raise RuntimeError('Cannot reach Google Fonts. Check internet access and retry.') from exc
    if not isinstance(items,list):
        raise ValueError(f'No downloadable Google Fonts family named {family!r} was found.')
    licenses=[a for a in items if isinstance(a,dict)
              and a.get('name','').lower() in ('ofl.txt','license.txt','ufl.txt')]
    files=[a for a in items if isinstance(a,dict)
           and Path(a.get('name','')).suffix.lower() in FONT_SUFFIXES]
    if not files or not licenses:
        raise ValueError('Google Fonts did not provide a font file and license for this family.')
    files.sort(key=lambda a:(
        not ('-regular' in a['name'].lower() or 'variablefont' in a['name'].lower()),
        len(a['name'])))
    selected=files[0]
    def trusted_url(item):
        link=item.get('download_url','')
        if not isinstance(link,str) or not link.startswith(BINARY_HOST):
            raise ValueError('Unexpected font download host; aborted for safety.')
        return link
    license_data=_read_url(trusted_url(licenses[0]),binary=True)
    font_data=_read_url(trusted_url(selected),binary=True)
    if not font_data.startswith((b'\x00\x01\x00\x00',b'OTTO',b'true')):
        raise ValueError('Downloaded data is not a valid TrueType/OpenType font.')
    if len(font_data)<1000 or not license_data:
        raise ValueError('Font file or license was incomplete.')
    dest=font_dir()/slug
    dest.mkdir(parents=True,exist_ok=True)
    fontfile=dest/Path(selected['name']).name
    licensefile=dest/Path(licenses[0]['name']).name
    try:
        licensefile.write_bytes(license_data)
        fontfile.write_bytes(font_data)
    except Exception:
        fontfile.unlink(missing_ok=True)
        raise
    return fontfile


def import_font(source):
    """Import an existing local TTF/OTF for users with additional fonts."""
    path=Path(source)
    if path.suffix.lower() not in FONT_SUFFIXES or not path.is_file():
        raise ValueError('Choose a local TTF or OTF font file.')
    if path.stat().st_size>MAX_FONT_BYTES:
        raise ValueError('Selected font exceeds the supported 12 MB limit.')
    data=path.read_bytes()
    if not data.startswith((b'\x00\x01\x00\x00',b'OTTO',b'true')):
        raise ValueError('The selected file is not a valid font.')
    name=re.sub(r'[^a-z0-9._-]','',path.stem.lower())[:65]
    dest=font_dir()/'imported'
    dest.mkdir(parents=True,exist_ok=True)
    target=dest/(name+path.suffix.lower())
    if path.resolve()!=target.resolve():
        shutil.copy2(path,target)
    return target


def installed_font_names():
    root=font_dir()
    if not root.exists(): return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def _medial_skeleton(binary):
    # OpenCV's cross erosion creates thin centerline approximations without
    # requiring opencv-contrib. Thickness is limited for responsive UI.
    remaining=(binary.astype(np.uint8)*255)
    skeleton=np.zeros_like(remaining)
    kernel=cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3))
    for _ in range(45):
        if not np.any(remaining): break
        eroded=cv2.erode(remaining,kernel)
        opened=cv2.dilate(eroded,kernel)
        skeleton=cv2.bitwise_or(skeleton,cv2.subtract(remaining,opened))
        remaining=eroded
    skeleton=cv2.bitwise_or(skeleton,remaining)
    return skeleton>0


def _trace_skeleton(image):
    ys,xs=np.nonzero(image)
    active={(int(x),int(y)) for x,y in zip(xs,ys)}
    if not active: return []
    def neighbors(p):
        x,y=p
        return sorted(((x+dx,y+dy) for dy in (-1,0,1) for dx in (-1,0,1)
                       if (dx or dy) and (x+dx,y+dy) in active),
                      key=lambda pt:(pt[1],pt[0]))
    graph={p:neighbors(p) for p in active}
    used=set(); paths=[]
    def edge(a,b): return tuple(sorted((a,b)))
    def follow(start,second):
        points=[start,second]
        used.add(edge(start,second))
        prev,cur=start,second
        while len(points)<6000:
            choices=[n for n in graph[cur] if n!=prev and edge(cur,n) not in used]
            if len(graph[cur])!=2 or not choices: break
            nxt=choices[0]
            used.add(edge(cur,nxt))
            points.append(nxt)
            prev,cur=cur,nxt
        if len(points)>3:
            paths.append([(float(x),float(y)) for x,y in points])
    for p in sorted(graph,key=lambda pt:(pt[1],pt[0])):
        if len(graph[p])==2: continue
        for q in graph[p]:
            if edge(p,q) not in used: follow(p,q)
    # Include loops where every pixel has degree two.
    for p in sorted(graph,key=lambda pt:(pt[1],pt[0])):
        for q in graph[p]:
            if edge(p,q) not in used: follow(p,q)
    return paths


def make_font_text(text,fontfile,point_size=68):
    """Prepare real font ink with a per-character progressive reveal route.

    TTF and OTF fonts store filled contours, NOT the author's handwriting
    movements. Rendering entire glyphs progressively preserves legibility,
    unlike the earlier sparse medial-skeleton fragments.
    """
    from PIL import ImageFont, ImageDraw, Image
    if not text.strip():
        raise ValueError('Enter some lettering to animate.')
    if len(text)>240:
        raise ValueError('Font lettering currently supports up to 240 characters.')
    point_size=int(point_size)
    if not 24<=point_size<=128:
        raise ValueError('Choose a font detail size from 24 to 128.')
    font=ImageFont.truetype(str(fontfile),point_size)
    lines=text.split('\n')
    ascent,descent=font.getmetrics()
    line_height=ascent+descent+12
    width=round(max(font.getlength(line) for line in lines)+40)
    height=round(len(lines)*line_height+32)
    if width*height>2_600_000:
        raise ValueError('Text is too large. Reduce detail size or shorten the lettering.')
    ink=Image.new('RGBA',(max(20,width),max(20,height)),(0,0,0,0))
    painter=ImageDraw.Draw(ink)
    strokes=[]
    boxes=[]
    for row,line in enumerate(lines):
        y=10+row*line_height
        # Render the TRUE font glyphs; using a letter mask is much better than
        # tracing noisy branch junctions of a raster skeleton.
        painter.text((18,y),line,font=font,fill=(37,54,74,255))
        for i,char in enumerate(line):
            if char.isspace(): continue
            x=18+font.getlength(line[:i])
            left,top,right,bottom=painter.textbbox((x,y),char,font=font)
            left=max(0,int(left)-1)
            right=min(ink.width,int(math.ceil(right))+1)
            top=max(0,int(top)-1)
            bottom=min(ink.height,int(math.ceil(bottom))+1)
            if right-left<1 or bottom-top<1:continue
            points=[(float(left),float((top+bottom)/2)),
                    (float(right),float((top+bottom)/2))]
            stroke=Stroke(f'Letter {char} / {len(strokes)+1}',points,
                          '#25364a',1.0)
            stroke.font_piece=len(boxes)
            strokes.append(stroke)
            boxes.append((left,top,right,bottom))
    if not strokes:
        raise ValueError('There are no drawable glyphs in this text.')
    drawing=Drawing(strokes,(0.,0.,float(ink.width),float(ink.height)),[
        'Google Fonts lettering: complete glyphs reveal progressively, one character at a time.',
        'Typefaces do not contain pen movement paths. Use Built-in single-line pen for true traced handwriting.',
    ])
    drawing.source_kind='font'
    drawing.font_ink=ink
    drawing.font_boxes=tuple(boxes)
    return drawing


def render_font_lettering(drawing,progress,width,height,thickness=1.,
                          hand=None,hand_scale=.18,anchor=(.1,.1)):
    """Reveal the genuine, fully rendered typeface at the writing playhead."""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt, QRectF
    image=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    fraction=max(0.,min(1.,float(progress)))
    if fraction<=0:return image
    ink=drawing.font_ink.convert('RGBA')
    font_image=QImage(ink.tobytes(),ink.width,ink.height,
                      ink.width*4,QImage.Format.Format_RGBA8888).copy()
    iw,ih=ink.size
    scale=min(width*.82/max(1,iw),height*.78/max(1,ih))
    ox=(width-iw*scale)/2
    oy=(height-ih*scale)/2
    frame=QRectF(ox,oy,iw*scale,ih*scale)
    painter=QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    strokes=drawing.strokes
    # Each letter is allocated a time slice proportional to its width.
    weights=[max(6.,drawing.font_boxes[s.font_piece][2]-
                        drawing.font_boxes[s.font_piece][0]) for s in strokes]
    total=sum(weights)
    remaining=fraction*total
    tip=None
    for s,weight in zip(strokes,weights):
        if remaining<=0:break
        left,top,right,bottom=drawing.font_boxes[s.font_piece]
        portion=min(1.,remaining/weight)
        if portion<=0:break
        painter.save()
        painter.setClipRect(QRectF(ox+left*scale,oy+top*scale,
            max(0.1,(right-left)*portion*scale),(bottom-top)*scale))
        painter.drawImage(frame,font_image)
        painter.restore()
        # Follow the visible ink near the current writing x-column.
        ink_x=max(0,min(iw-1,int(left+(right-left)*portion)-1))
        a=ink.getchannel('A').crop((ink_x,max(0,top),ink_x+1,min(ih,bottom)))
        bbox=a.getbbox()
        cursor_y=float(top+(bbox[1]+bbox[3])/2) if bbox else (top+bottom)/2
        tip=(ox+(left+(right-left)*portion)*scale,oy+cursor_y*scale)
        remaining-=weight
    if tip and hand is not None and not hand.isNull() and 0<fraction<1:
        hw=width*hand_scale
        hh=hw*hand.height()/hand.width()
        painter.drawImage(QRectF(tip[0]-anchor[0]*hw,
                  tip[1]-anchor[1]*hh,hw,hh),hand)
    painter.end()
    return image
