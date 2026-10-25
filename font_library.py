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
# urllib is imported when a font is downloaded (exp.120: faster start).

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from engine import Drawing, Stroke

# Open-licensed Google Fonts (OFL or Apache 2.0: free, also for commercial use),
# downloaded on request with their license. Grouped in the font list.
FONT_GROUPS={
    'Handwriting':('Caveat','Kalam','Patrick Hand','Indie Flower','Gochi Hand','Architects Daughter',
                   'Shadows Into Light','Reenie Beanie','Amatic SC','Permanent Marker','Rock Salt',
                   'Covered By Your Grace','Gloria Hallelujah','Handlee','Nothing You Could Do','Homemade Apple',
                   'Just Another Hand','Schoolbell','Coming Soon','Neucha','Over the Rainbow',
                   'Annie Use Your Telescope','La Belle Aurore','Zeyada','Delius','Mali','Sriracha','Caveat Brush',
                   'Pangolin','Delicious Handrawn','Sue Ellen Francisco','Short Stack'),
    'Script':('Dancing Script','Sacramento','Satisfy','Great Vibes','Pacifico','Courgette','Kaushan Script',
              'Allura'),
    'Clean titles':('Nunito','Poppins','Montserrat','Lato','Quicksand','Comfortaa','Fredoka','Bebas Neue',
                    'Oswald','Bangers','Luckiest Guy','Chewy'),
    'Serif':('Merriweather','Playfair Display','Lora'),
}
STARTER_FONTS=tuple(f for group in FONT_GROUPS.values() for f in group)
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
    from urllib.request import Request, urlopen
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
    from urllib.error import HTTPError, URLError
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
    """Build authentic font ink with estimated centerline pen trajectories."""
    from font_stroke_reveal import create_font_drawing
    return create_font_drawing(text,fontfile,point_size)


def render_font_lettering(drawing,progress,width,height,thickness=1.,
                          hand=None,hand_scale=.18,anchor=(.1,.1)):
    """Show glyph pixels only when their nearest inferred pen path is reached."""
    from font_stroke_reveal import render_traced_font
    return render_traced_font(drawing,progress,width,height,thickness,
                              hand,hand_scale,anchor)
