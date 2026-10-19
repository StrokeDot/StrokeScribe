"""Bounded native SVG appearance; vector paths remain the animation source."""
from collections import OrderedDict
import hashlib,math,re,threading
import xml.etree.ElementTree as ET
from PySide6.QtCore import QByteArray,QRectF,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer

MAX_PIXELS=8_000_000
CACHE_LIMIT=128*1024*1024
_cache=OrderedDict()
_lock=threading.RLock()

def validate_source(root):
    """Never load external resources; Qt and geometry parse the same safe source."""
    for node in root.iter():
        tag=node.tag.split('}')[-1]
        if tag in ('script','foreignObject','image'):
            raise ValueError('SVG embedded or external resources are unsupported.')
        for name,value in node.attrib.items():
            local=name.split('}')[-1]
            if local=='href' and not value.strip().startswith('#'):
                raise ValueError('SVG external resource references are unsupported.')
            if local.lower().startswith('on'):
                raise ValueError('SVG script resources are unsupported.')
            for target in re.findall(r'url\(\s*[\'"]?([^\)\'"]+)',value,re.I):
                if not target.strip().startswith('#'):
                    raise ValueError('SVG external resources are unsupported.')
        if tag=='style' and node.text:
            if '@import' in node.text.lower():
                raise ValueError('SVG external style resources are unsupported.')
            for target in re.findall(r'url\(\s*[\'"]?([^\)\'"]+)',node.text,re.I):
                if not target.strip().startswith('#'):
                    raise ValueError('SVG external style resources are unsupported.')

def clear_cache():
    with _lock:_cache.clear()

def cache_bytes():
    with _lock:return sum(image.sizeInBytes() for image in _cache.values())

def render_appearance(drawing,max_side=2048):
    """Render tight bounds in the viewport coordinates used by svgelements.

    No surface is allocated at the SVG's declared intrinsic dimensions.
    Each caller gets an implicitly shared Qt image; painting detaches it.
    """
    source=drawing.svg_source
    if not isinstance(source,str) or len(source)>5_000_000 or '<!DOCTYPE' in source.upper() or '<!ENTITY' in source.upper():
        raise ValueError('SVG source exceeds limits or contains unsupported document resources.')
    root=ET.fromstring(source)
    validate_source(root)
    bounds=tuple(float(v) for v in drawing.bounds)
    viewport=tuple(float(v) for v in drawing.svg_viewport)
    if len(bounds)!=4 or len(viewport)!=2 or not all(math.isfinite(v) and abs(v)<=10_000_000 for v in bounds+viewport) or min(viewport)<=0:
        raise ValueError('Invalid SVG dimensions.')
    x0,y0,x1,y1=bounds
    w,h=max(1.,x1-x0),max(1.,y1-y0)
    side=max(2,min(4096,int(max_side)))
    ratio=min(side/max(w,h),math.sqrt(MAX_PIXELS/(w*h)))
    iw,ih=max(1,int(w*ratio)),max(1,int(h*ratio))
    key=(hashlib.sha256(source.encode()).digest(),bounds,viewport,iw,ih)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return QImage(_cache[key])
    renderer=QSvgRenderer(QByteArray(source.encode('utf-8')))
    if not renderer.isValid():
        raise ValueError('The native SVG appearance could not be rendered.')
    image=QImage(iw,ih,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(iw/w,ih/h)
        painter.translate(-x0,-y0)
        painter.setClipRect(QRectF(0,0,*viewport))
        renderer.setAspectRatioMode(Qt.AspectRatioMode.IgnoreAspectRatio)
        target=QRectF(0,0,*viewport)
        box=renderer.viewBoxF()
        align=root.get('preserveAspectRatio','xMidYMid meet').split()
        if align and align[0]=='defer':align=align[1:]
        mode=align[0] if align else 'xMidYMid'
        if root.get('viewBox') and mode!='none' and box.width()>0 and box.height()>0:
            scales=(viewport[0]/box.width(),viewport[1]/box.height())
            factor=max(scales) if 'slice' in align else min(scales)
            tw,th=box.width()*factor,box.height()*factor
            dx=0. if 'xMin' in mode else viewport[0]-tw if 'xMax' in mode else (viewport[0]-tw)/2
            dy=0. if 'YMin' in mode else viewport[1]-th if 'YMax' in mode else (viewport[1]-th)/2
            target=QRectF(dx,dy,tw,th)
        renderer.render(painter,target)
    finally:painter.end()
    with _lock:
        while _cache and cache_bytes()+image.sizeInBytes()>CACHE_LIMIT:
            _cache.popitem(last=False)
        _cache[key]=QImage(image)
    return image
