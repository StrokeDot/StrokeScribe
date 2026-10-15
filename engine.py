"""Local vector-stroke renderer. All raster output starts with transparent pixels."""
from __future__ import annotations
import bisect, math, json, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor
from svgelements import SVG, Shape, Path as SVGPath, Move

@dataclass
class Stroke:
    name: str
    points: list[tuple[float, float]]
    color: str = '#153c54'
    width: float = 3
    # Drawing speed factor: >1 draws this stroke more slowly (careful detail),
    # <1 faster (quick guide lines). Used by image-source timing.
    pace: float = 1.0
    def __post_init__(self):
        self.distances = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.distances.append(self.distances[-1] + math.dist(a, b))
        self.length = self.distances[-1]
    def portion(self, distance):
        if distance >= self.length: return self.points
        i = bisect.bisect_right(self.distances, max(0, distance))
        if i >= len(self.points): return self.points
        a, b = self.points[i-1], self.points[i]
        span = self.distances[i] - self.distances[i-1]
        f = (distance-self.distances[i-1])/span if span else 0
        return self.points[:i] + [(a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f)]

@dataclass
class Drawing:
    strokes: list[Stroke]
    bounds: tuple[float, float, float, float]
    warnings: list[str]

def import_svg(filename):
    raw = Path(filename).read_text(encoding='utf-8-sig')
    if len(raw) > 5_000_000: raise ValueError('SVG is too large for this prototype (5 MB limit).')
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper(): raise ValueError('SVG document entities are unsupported.')
    root = ET.fromstring(raw)
    warnings = set()
    for e in root.iter():
        tag = e.tag.split('}')[-1]
        if tag in {'text','image','clipPath','mask','filter','linearGradient','radialGradient','style','foreignObject','svg'} and e is not root:
            warnings.add(f'{tag}: unsupported; convert to plain stroked paths for predictable results.')
        if any(k in e.attrib for k in ('clip-path','mask','filter')):
            warnings.add('Clipping, masks and filters are ignored.')
    svg = SVG.parse(filename, reify=True)
    strokes = []
    for el in svg.elements():
        if not isinstance(el, Shape): continue
        if el.values.get('visibility') == 'hidden' or el.values.get('display') == 'none': continue
        p = SVGPath(el)
        p.reify()
        if not len(p): continue
        color = str(el.stroke) if el.stroke is not None else 'None'
        if color in ('None', 'none'):
            color = str(el.fill) if el.fill is not None else '#153c54'
            if color in ('None','none'): continue
            warnings.add('Filled shapes are drawn as outlines; fills are not reconstructed as pen strokes.')
        for sub_index, sub in enumerate(p.as_subpaths()):
            points=[]
            for seg in sub:
                if isinstance(seg, Move): continue
                # Dense curve sampling, then arc-length timing along the resulting geometry.
                n = max(1, min(20000, math.ceil(seg.length(error=1e-5)/0.4)))
                for j in range(n+1):
                    pt=seg.point(j/n)
                    xy=(float(pt.x),float(pt.y))
                    if not all(math.isfinite(v) for v in xy): raise ValueError('Non-finite SVG coordinates.')
                    if not points or math.dist(points[-1],xy)>1e-9: points.append(xy)
            if len(points)>1:
                strokes.append(Stroke(f'{el.id or "shape"} / {sub_index+1}',points,color,float(el.stroke_width or 3)))
            if sum(len(s.points) for s in strokes)>500000: raise ValueError('Drawing is too complex (500,000 sampled points maximum).')
    if not strokes: raise ValueError('No drawable vector strokes found. Convert text or images to SVG paths first.')
    allpts=[pt for s in strokes for pt in s.points]
    xs,ys=zip(*allpts)
    bounds=(min(xs),min(ys),max(xs),max(ys))
    # SVGs exported by StrokeScribe record their exact image frame so the
    # matching colour PNG lines up even when lines don't reach the edges.
    frame=root.attrib.get('data-strokescribe-frame')
    if frame:
        try:
            fx,fy,fw,fh=(float(v) for v in frame.replace(',',' ').split())
            if fw>0 and fh>0 and all(math.isfinite(v) for v in (fx,fy,fw,fh)):
                bounds=(fx,fy,fx+fw,fy+fh)
        except ValueError:
            pass
    return Drawing(strokes,bounds,sorted(warnings))

def render(drawing, progress, width=1920, height=1080, thickness=1.0, hand=None, hand_scale=0.18, anchor=(0.1,0.1),image_timing=True):
    if getattr(drawing,'source_kind',None)=='font':
        from font_library import render_font_lettering
        return render_font_lettering(drawing,progress,width,height,thickness,
                                    hand,hand_scale,anchor)
    if image_timing and getattr(drawing,'source_kind',None)=='image':
        from image_drawing import render_image_lines
        return render_image_lines(drawing,progress,width,height,thickness,hand,hand_scale,anchor)
    image=QImage(width,height,QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    x0,y0,x1,y1=drawing.bounds
    scale=min(width*0.82/max(1,x1-x0),height*0.78/max(1,y1-y0))
    ox=(width-(x1-x0)*scale)/2-x0*scale
    oy=(height-(y1-y0)*scale)/2-y0*scale
    remaining=sum(s.length for s in drawing.strokes)*max(0,min(1,progress))
    tip=None
    for stroke in drawing.strokes:
        if remaining<=0: break
        points=stroke.portion(min(remaining,stroke.length))
        path=QPainterPath(QPointF(points[0][0]*scale+ox,points[0][1]*scale+oy))
        for x,y in points[1:]: path.lineTo(x*scale+ox,y*scale+oy)
        pen=QPen(QColor(stroke.color),max(0.1,stroke.width*thickness*scale),Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        tip=(points[-1][0]*scale+ox,points[-1][1]*scale+oy)
        remaining-=stroke.length
    if hand is not None and not hand.isNull() and tip and 0<progress<1:
        hw=width*hand_scale
        hh=hw*hand.height()/hand.width()
        from hand_layer import paint
        paint(painter,QRectF(tip[0]-anchor[0]*hw,tip[1]-anchor[1]*hh,hw,hh),hand)
    painter.end()
    return image

def scale_animation_frame(frame, artwork_scale=1.0, hands=None):
    """Scale the complete drawing+color+hand layer inside its output frame.

    This is independent from output resolution and is applied identically in
    preview and export. Keeps SVG and raster PNG perfectly aligned, including
    their hand overlay. Can crop at >100% by design.
    """
    factor=float(artwork_scale)
    if not .25<=factor<=2.0 or not math.isfinite(factor):
        raise ValueError('Artwork size must be between 25% and 200%.')
    from hand_layer import draw_captured
    if abs(factor-1.0)<1e-9:
        return draw_captured(frame,hands,1.0)
    output=QImage(frame.size(),QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter=QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    w,h=frame.width(),frame.height()
    painter.drawImage(QRectF((w-w*factor)/2,(h-h*factor)/2,
                             w*factor,h*factor),frame)
    painter.end()
    # The hand goes on AFTER scaling, so it is never cut at the old frame edge.
    return draw_captured(output,hands,factor)


def apply_lettering_background(frame,drawing):
    """Composite an optional lettering background AFTER artwork scaling.

    This covers the full output video canvas; default None keeps genuine
    alpha. SVG/image reconstruction frames are unaffected.
    """
    color=getattr(drawing,'lettering_background',None)
    if color is None or getattr(drawing,'source_kind',None) not in ('font','lettering'):
        return frame
    background=QColor(str(color))
    if not background.isValid():
        raise ValueError('Invalid lettering background color.')
    result=QImage(frame.size(),QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(background)
    painter=QPainter(result)
    painter.drawImage(0,0,frame)
    painter.end()
    return result


# PNG is lossless at every compression level. Qt maps PNG "quality" inversely
# onto zlib levels; 80 selects fast level-1 compression instead of the slow
# default. Frames are temporary encoder input, so speed matters more than size.
PNG_FAST_QUALITY=80


def _frame_bytes(image):
    """Raw pixel bytes of a frame, used to detect exact repeats."""
    if image.format()!=QImage.Format.Format_ARGB32_Premultiplied:
        image=image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return bytes(image.constBits())


def _reuse_frame(source,target):
    """Copy an identical frame file; far cheaper than re-encoding it.

    A plain copy (not a hard link) keeps every kept PNG independently editable.
    """
    shutil.copyfile(source,target)


def export_frames(drawing, folder, duration=4, fps=30, width=1920, height=1080, thickness=1, hand=None, hand_scale=.18, anchor=(.1,.1), callback=None, final_image=None, fade_duration=.4, hold_duration=.6, reveal_mode='fade', brush_width=.14, painting_hand=None, stroke_spacing=.55, artwork_scale=1.0):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    use_color = final_image is not None and not final_image.isNull()
    if use_color:
        from color_reveal import timeline_duration, render_color_timeline
        total=timeline_duration(duration,final_image,fade_duration,hold_duration)
    else:
        total=duration
    count=max(2,round(total*fps))
    # Artwork scaling transforms the completed frame. Counter-scale the hand
    # first so the final hand width is governed ONLY by Hand Size, not artwork
    # magnification. This applies to preview and all export formats equally.
    if not .25<=float(artwork_scale)<=2.0 or not math.isfinite(float(artwork_scale)):
        raise ValueError('Artwork size must be between 25% and 200%.')
    preview_hand_scale=hand_scale/float(artwork_scale)
    previous=None
    for i in range(count):
        fraction=i/(count-1)
        from hand_layer import capture
        with capture() as hands:
            if use_color:
                img=render_color_timeline(drawing,fraction,width,height,duration,fade_duration,hold_duration,
                                          final_image,thickness,hand,preview_hand_scale,anchor,
                                          reveal_mode,brush_width,painting_hand,stroke_spacing)
            else:
                img=render(drawing,fraction,width,height,thickness,hand,preview_hand_scale,anchor)
        img=scale_animation_frame(img,artwork_scale,hands)
        img=apply_lettering_background(img,drawing)
        path=folder/f'frame_{i:06d}.png'
        pixels=_frame_bytes(img)
        if previous is not None and pixels==previous[0]:
            # Identical to the previous frame (settled painting, hold): reuse
            # that file instead of compressing the same image again.
            _reuse_frame(previous[1],path)
        else:
            if not img.save(str(path),'PNG',PNG_FAST_QUALITY): raise OSError('Unable to save PNG frame.')
            previous=(pixels,path)
        if callback and callback(i+1,count) is False: raise InterruptedError('Export cancelled; partial frames remain in the export folder.')
    (folder/'sequence.json').write_text(json.dumps(dict(width=width,height=height,fps=fps,frames=count,
        duration=count/fps,draw_duration=duration,color_reveal=use_color,
        color_fade_seconds=fade_duration if use_color else 0,
        color_hold_seconds=hold_duration if use_color else 0,
        reveal_mode=reveal_mode if use_color else 'none',
        brush_width=brush_width if use_color and reveal_mode in ('brush','continue','guided','clean','adaptive','zigzag') else None,
        painting_hand=bool(use_color and reveal_mode in ('brush','continue','guided','clean','adaptive','zigzag') and painting_hand is not None and not painting_hand.isNull()),
        stroke_spacing=stroke_spacing if reveal_mode in ('adaptive','zigzag') else None,
        artwork_scale=artwork_scale,
        drawing_visibility=getattr(drawing,'drawing_visibility','progressive'),
        contour_transition=getattr(drawing,'contour_transition','legacy'),
        retirement_direction=getattr(drawing,'retirement_direction','forward'),
        lettering_background=getattr(drawing,'lettering_background',None)
          if getattr(drawing,'source_kind',None) in ('font','lettering') else None,
        alpha=not (getattr(drawing,'lettering_background',None) is not None
                   and getattr(drawing,'source_kind',None) in ('font','lettering')),
        first_frame='transparent' if getattr(drawing,'lettering_background',None) is None else 'colored_background',
        last_frame='original_color_png' if use_color else 'complete'),indent=2))
    return count

def encode_mov(folder, fps=30):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg: raise RuntimeError('FFmpeg was not found on PATH. PNG frames have still been exported.')
    output=Path(folder)/'animation_prores4444.mov'
    cmd=[ffmpeg,'-n','-hide_banner','-loglevel','error','-framerate',str(fps),'-i',str(Path(folder)/'frame_%06d.png'),'-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le','-alpha_bits','16',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise RuntimeError(result.stderr[-2000:])
    return output

def encode_webm(folder, fps=30, quality=28):
    """Create a smaller, genuinely alpha-bearing VP9 WebM from PNG frames.

    Filmora import of external VP9 alpha files must still be visually tested.
    The source frames are never removed here; callers delete them only after
    successful encoding and when the user explicitly chose that behavior.
    """
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('FFmpeg was not found on PATH. PNG frames have still been exported.')
    quality=int(quality)
    if not 18<=quality<=42:
        raise ValueError('WebM quality must be in the range 18–42.')
    folder=Path(folder)
    output=folder/'animation_vp9_alpha.webm'
    cmd=[ffmpeg,'-n','-hide_banner','-loglevel','error',
         '-framerate',str(fps),'-i',str(folder/'frame_%06d.png'),
         '-an','-c:v','libvpx-vp9','-deadline','good','-cpu-used','4',
         '-row-mt','1','-b:v','0','-crf',str(quality),
         '-auto-alt-ref','0','-pix_fmt','yuva420p',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        output.unlink(missing_ok=True)
        raise RuntimeError('WebM encoding failed: '+result.stderr[-2000:])
    if not output.is_file() or output.stat().st_size<=0:
        raise RuntimeError('WebM encoder did not produce a nonempty video.')
    # Make deletion-safe: require an encoded VP9 stream with an alpha tag.
    # Standard ffprobe decoding may report yuv420p because it uses the native
    # decoder, which does not expose VP9 alpha; alpha_mode=1 is the container
    # signal for VP9 alpha, verified in the CI tests via libvpx-vp9 decoding.
    ffprobe=shutil.which('ffprobe')
    if ffprobe:
        info=subprocess.run([ffprobe,'-v','error','-select_streams','v:0',
            '-show_entries','stream=codec_name:stream_tags=alpha_mode',
            '-of','json',str(output)],capture_output=True,text=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if info.returncode:
            raise RuntimeError('WebM created but could not verify its stream; PNG frames retained.')
        try:
            stream=json.loads(info.stdout)['streams'][0]
            valid=stream.get('codec_name')=='vp9' and str(stream.get('tags',{}).get('alpha_mode'))=='1'
        except (KeyError,IndexError,ValueError,TypeError):
            valid=False
        if not valid:
            raise RuntimeError('WebM was encoded without verified VP9 transparency; PNG frames retained.')
    return output


MP4_BACKGROUNDS={'white':'FFFFFF','dark':'242D3B','black':'000000'}


def encode_mp4(folder, fps=30, background='white'):
    """Standard H.264 MP4 of the animation on a solid background color.

    MP4 has no transparency, so frames are composited over the chosen color
    (the same White/Dark colors as the preview). Plays everywhere and needs no
    WebM or ProRes. Source PNG frames are never removed here.
    """
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('FFmpeg was not found on PATH. PNG frames have still been exported.')
    if background not in MP4_BACKGROUNDS:
        raise ValueError('MP4 background must be white, dark or black.')
    folder=Path(folder)
    info=json.loads((folder/'sequence.json').read_text())
    width,height=int(info['width']),int(info['height'])
    output=folder/f'animation_{background}_background.mp4'
    color=f"color=c=0x{MP4_BACKGROUNDS[background]}:s={width}x{height}:r={fps}"
    cmd=[ffmpeg,'-n','-hide_banner','-loglevel','error',
         '-framerate',str(fps),'-i',str(folder/'frame_%06d.png'),
         '-f','lavfi','-i',color,
         '-filter_complex','[1:v][0:v]overlay=shortest=1:format=auto,format=yuv420p',
         '-an','-c:v','libx264','-preset','medium','-crf','16',
         '-movflags','+faststart',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        output.unlink(missing_ok=True)
        raise RuntimeError('MP4 encoding failed: '+result.stderr[-2000:])
    if not output.is_file() or output.stat().st_size<=0:
        raise RuntimeError('MP4 encoder did not produce a nonempty video.')
    return output
