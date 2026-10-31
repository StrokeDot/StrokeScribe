"""Local vector-stroke renderer. All raster output starts with transparent pixels."""
from __future__ import annotations
import bisect, math, json, os, shutil, subprocess, io, re
from dataclasses import dataclass
from itertools import accumulate as _accumulate
from pathlib import Path
import xml.etree.ElementTree as ET
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor
from svgelements import SVG, Shape, Path as SVGPath, Move, Line

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
        # exp.130: the same sums in C (accumulate/map) instead of a Python loop: opening a
        # project builds every stroke of every element.
        points = self.points
        self.distances = list(_accumulate(map(math.dist, points, points[1:]), initial=0.0))
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

    def __bool__(self):
        return bool(self.strokes)

def _sample_svg_segment(seg, *, tolerance=0.35, max_chord=10.0, budget=500_000):
    """Adaptively flatten curves instead of sampling every 0.4 SVG units.

    Lines need only endpoints because the animation interpolates movement.
    Curves are subdivided based on deviation from their chord; the point
    budget and recursion depth still bound hostile or pathological inputs.
    """
    def point(t):
        p = seg.point(t)
        xy = (float(p.x), float(p.y))
        if not all(math.isfinite(v) for v in xy):
            raise ValueError('Non-finite SVG coordinates.')
        return xy

    def chord_distance(point, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return math.dist(point, a)
        return abs(dx * (a[1] - point[1]) - dy * (a[0] - point[0])) / length

    a, b = point(0.0), point(1.0)
    if isinstance(seg, Line) or type(seg).__name__ == 'Close':
        return [a, b]
    points = [a]
    stack = [(0.0, 1.0, a, b, 0)]
    while stack:
        lo, hi, first, last, depth = stack.pop()
        mid = (lo + hi) / 2
        middle = point(mid)
        flat = (math.dist(first, last) <= max_chord and
                all(chord_distance(point(t), first, last) <= tolerance
                    for t in ((3*lo+hi)/4, mid, (lo+3*hi)/4)))
        if flat or depth >= 16:
            points.append(last)
            if len(points) > budget:
                raise ValueError('Drawing is too complex (500,000 sampled points maximum).')
        else:
            stack.append((mid, hi, middle, last, depth+1))
            stack.append((lo, mid, first, middle, depth+1))
    return points


def import_svg(filename):
    raw = Path(filename).read_text(encoding='utf-8-sig')
    if len(raw) > 5_000_000: raise ValueError('SVG is too large for this prototype (5 MB limit).')
    # Many valid SVG exports include the standard SVG 1.1 PUBLIC doctype.
    # Strip only a simple declaration, without loading its external DTD.
    # Never allow custom/internal entity definitions or DTD subsets.
    safe_doctype = False
    if '<!ENTITY' in raw.upper():
        raise ValueError('SVG document entities are unsupported.')
    if '<!DOCTYPE' in raw.upper():
        allowed = re.search(
            r'''<!DOCTYPE\s+svg\s+PUBLIC\s+"[^"]+"\s+"[^"]+"\s*>''',
            raw, re.IGNORECASE)
        if allowed is None or raw.upper().count('<!DOCTYPE') != 1:
            raise ValueError('SVG document entities are unsupported.')
        raw = raw[:allowed.start()] + raw[allowed.end():]
        safe_doctype = True
    root = ET.fromstring(raw)
    from svg_appearance import validate_source
    validate_source(root)
    warnings = set()
    for e in root.iter():
        tag = e.tag.split('}')[-1]
        if tag in {'text','image','clipPath','mask','filter','linearGradient','radialGradient','style','foreignObject','svg'} and e is not root:
            warnings.add(f'{tag}: unsupported; convert to plain stroked paths for predictable results.')
        if any(k in e.attrib for k in ('clip-path','mask','filter')):
            warnings.add('Clipping, masks and filters are ignored.')
    svg = SVG.parse(io.StringIO(raw) if safe_doctype else filename, reify=True)
    viewport=(float(svg.width or 1000),float(svg.height or 1000))
    if not all(math.isfinite(v) and 0<v<=10_000_000 for v in viewport):
        raise ValueError('SVG dimensions exceed the safe coordinate limit.')
    has_fill=False
    visual_boxes=[]
    strokes = []
    shapes = []
    total_points = 0
    for el in svg.elements():
        if not isinstance(el, Shape): continue
        if el.values.get('visibility') == 'hidden' or el.values.get('display') == 'none': continue
        fill=str(el.fill) if el.fill is not None else 'none'
        has_fill=has_fill or fill.lower() not in ('none','transparent')
        p = SVGPath(el)
        p.reify()
        if not len(p): continue
        box=el.bbox(with_stroke=True)
        if box is not None:visual_boxes.append(tuple(float(v) for v in box))
        color = str(el.stroke) if el.stroke is not None else 'None'
        if color in ('None', 'none'):
            color = str(el.fill) if el.fill is not None else '#153c54'
            if color in ('None','none'): continue
            warnings.add('Filled shapes are drawn as outlines; fills are not reconstructed as pen strokes.')
        shapes.append((el, color, list(p.as_subpaths())))
    # Sampling. Dense sampling (a point every 0.4 SVG units) is the original
    # method: Adaptive Hand Painting plans its brush route from these points,
    # so it is kept whenever the drawing fits the point budget (exact .58
    # behaviour). Only drawings that would exceed 500,000 points switch to
    # curvature-adaptive sampling (added in .63 for complex vector imports).
    def dense_count(seg):
        return max(1, min(20000, math.ceil(seg.length(error=1e-5)/0.4))) + 1
    dense = sum(dense_count(seg) for _, _, subs in shapes for sub in subs
                for seg in sub if not isinstance(seg, Move)) <= 500_000
    for el, color, subs in shapes:
        for sub_index, sub in enumerate(subs):
            points=[]
            for seg in sub:
                if isinstance(seg, Move): continue
                if dense:
                    # Dense curve sampling, then arc-length timing along the resulting geometry.
                    n = max(1, min(20000, math.ceil(seg.length(error=1e-5)/0.4)))
                    for j in range(n+1):
                        pt=seg.point(j/n)
                        xy=(float(pt.x),float(pt.y))
                        if not all(math.isfinite(v) for v in xy): raise ValueError('Non-finite SVG coordinates.')
                        if not points or math.dist(points[-1],xy)>1e-9: points.append(xy)
                    continue
                # Keep exact straight edges; subdivide curved edges only
                # where the artwork would visibly differ from the chord.
                for xy in _sample_svg_segment(seg, budget=500_000-total_points-len(points)):
                    if not points or math.dist(points[-1],xy)>1e-9:
                        points.append(xy)
                        if total_points + len(points) > 500_000:
                            raise ValueError('Drawing is too complex (500,000 sampled points maximum).')
            if len(points)>1:
                strokes.append(Stroke(f'{el.id or "shape"} / {sub_index+1}',points,color,float(el.stroke_width or 3)))
                total_points += len(points)
            if total_points>500000: raise ValueError('Drawing is too complex (500,000 sampled points maximum).')
    if not strokes: raise ValueError('No drawable vector strokes found. Convert text or images to SVG paths first.')
    allpts=[pt for s in strokes for pt in s.points]
    xs,ys=zip(*allpts)
    bounds=(min(xs),min(ys),max(xs),max(ys))
    if has_fill and visual_boxes:
        bounds=(min(bounds[0],min(b[0] for b in visual_boxes)),min(bounds[1],min(b[1] for b in visual_boxes)),
                max(bounds[2],max(b[2] for b in visual_boxes)),max(bounds[3],max(b[3] for b in visual_boxes)))
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
    if not all(math.isfinite(v) and abs(v)<=10_000_000 for v in bounds):
        raise ValueError('SVG dimensions exceed the safe coordinate limit.')
    drawing=Drawing(strokes,bounds,sorted(warnings))
    drawing.svg_source=raw
    drawing.svg_viewport=viewport
    drawing.svg_has_fill=has_fill
    return drawing

def render(drawing, progress, width=1920, height=1080, thickness=1.0, hand=None, hand_scale=0.18, anchor=(0.1,0.1),image_timing=True):
    if getattr(drawing,'source_kind',None)=='font':
        from font_library import render_font_lettering
        return render_font_lettering(drawing,progress,width,height,thickness,
                                    hand,hand_scale,anchor)
    if image_timing and getattr(drawing,'source_kind',None)=='image':
        from image_drawing import render_image_lines
        return render_image_lines(drawing,progress,width,height,thickness,hand,hand_scale,anchor)
    if image_timing:
        # Per-line pace, pauses and pen ease (no change without custom timing).
        from stroke_timing import ink_progress
        progress=ink_progress(drawing,progress)
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


def export_frames(drawing, folder, duration=4, fps=30, width=1920, height=1080, thickness=1, hand=None, hand_scale=.18, anchor=(.1,.1), callback=None, final_image=None, fade_duration=.4, hold_duration=.6, reveal_mode='fade', brush_width=.14, painting_hand=None, stroke_spacing=.55, artwork_scale=1.0, camera_zoom=1.0, erase=None, workers=None, sound_files=None, layers='all', offset=(0., 0.), background=True, overlays=None, entrance='draw', pause=0., blend_mode='Normal', artwork_opacity=100, paper_cleanup=False, paper_tolerance=22, paper_softness=8, entrance_part='all', move_hand=None, move_hand_grip=None, move_hand_size=.35, cam_plan=None, video_camera=None, hand_travel=0., hand_rest_corner=None, hand_rest_here=True, hand_away=None, hand_video_start=0., hand_under=False):
    """Write the PNG frames. workers: None/0 = automatic (several CPU cores for
    longer exports), 1 = one core, n = n worker processes."""
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    use_color = final_image is not None and not final_image.isNull()
    # Artwork scaling transforms the completed frame. Counter-scale the hand
    # first so the final hand width is governed ONLY by Hand Size, not artwork
    # magnification. This applies to preview and all export formats equally.
    if not .25<=float(artwork_scale)<=2.0 or not math.isfinite(float(artwork_scale)):
        raise ValueError('Artwork size must be between 25% and 200%.')
    preview_hand_scale=hand_scale/float(artwork_scale)
    from frame_render import compose_frame, camera_for
    options=dict(width=width,height=height,duration=duration,fade_duration=fade_duration,
                 hold_duration=hold_duration,final_image=final_image if use_color else None,
                 thickness=thickness,hand=hand,hand_scale=preview_hand_scale,anchor=anchor,
                 reveal_mode=reveal_mode,brush_width=brush_width,painting_hand=painting_hand,
                 stroke_spacing=stroke_spacing,artwork_scale=artwork_scale,erase=erase,layers=layers,
                 offset=tuple(offset or (0.,0.)),background=background,overlays=list(overlays or ()),
                 entrance=entrance or 'draw',pause=float(pause or 0),entrance_part=entrance_part or 'all',
                 move_hand=move_hand,move_hand_grip=move_hand_grip,move_hand_size=float(move_hand_size),
                 blend_mode=blend_mode,artwork_opacity=artwork_opacity,
                 paper_cleanup=paper_cleanup,paper_tolerance=paper_tolerance,
                 paper_softness=paper_softness)
    if cam_plan: options['cam_plan']=tuple(cam_plan)            # exp.115/119: the cameras
    if video_camera: options['video_camera']=video_camera
    if hand_under: options['hand_under']=True        # exp.155: the cameras move the hand
    if hand_travel:                       # exp.143: the hand waits in a corner
        options.update(hand_travel=float(hand_travel),hand_rest_corner=hand_rest_corner,hand_rest_here=bool(hand_rest_here),
                       hand_away=hand_away,hand_video_start=float(hand_video_start or 0))
    from frame_render import timeline_seconds
    total=timeline_seconds(drawing,options)
    count=max(2,round(total*fps))
    camera_path=camera_for(drawing,options,float(camera_zoom))
    from parallel_export import worker_count, export_parallel, NotStarted
    cores=worker_count(count,workers)
    rendered=False
    if cores>1:
        try:
            export_parallel(drawing,folder,options,camera_path,count,cores,callback)
            rendered=True
        except NotStarted:
            rendered=False            # render on one core below
    previous=None
    for i in (() if rendered else range(count)):
        fraction=i/(count-1)
        img=compose_frame(drawing,fraction,options,camera_path)
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
        brush_width=brush_width if use_color and reveal_mode in ('brush','continue','guided','clean','adaptive','zigzag','rows','columns','short_zigzag','painter') else None,
        painting_hand=bool(use_color and reveal_mode in ('brush','continue','guided','clean','adaptive','zigzag','rows','columns','short_zigzag','painter') and painting_hand is not None and not painting_hand.isNull()),
        stroke_spacing=stroke_spacing if reveal_mode in ('adaptive','zigzag','rows','columns','short_zigzag','painter') else None,
        artwork_scale=artwork_scale,
        camera_zoom=float(camera_zoom),
        cpu_workers=cores if rendered else 1,
        layers=layers,
        erase=({k:v for k,v in erase.items() if k in ('mode','seconds','size')} if erase and erase.get('mode') else None),
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

def _audio_args(audio, codec):
    """FFmpeg arguments that add a soundtrack WAV as the second input."""
    if not audio:
        return [], ['-an']
    return ['-i', str(audio)], ['-map', '0:v', '-map', '1:a', '-c:a', *codec, '-shortest']


def _backdrop(folder, fps, background, audio, audio_codec):
    """Inputs / filter / maps that put the frames on the video Background (None: keep transparency)."""
    if not background or background=='transparent':
        extra_in,audio_out=_audio_args(audio,audio_codec)
        return extra_in,[],audio_out if audio else ['-an']
    folder=Path(folder)
    info=json.loads((folder/'sequence.json').read_text())
    from backgrounds import picture_png
    png=picture_png(background,int(info['width']),int(info['height']),folder/'background.png')
    inputs=['-loop','1','-framerate',str(fps),'-i',str(png)]+(['-i',str(audio)] if audio else [])
    maps=['-map','[v]']+(['-map','2:a','-c:a',*audio_codec,'-shortest'] if audio else ['-an'])
    return inputs,['-filter_complex','[1:v][0:v]overlay=shortest=1:format=auto[v]'],maps


def encode_mov(folder, fps=30, audio=None, background=None):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg: raise RuntimeError('FFmpeg was not found on PATH. PNG frames have still been exported.')
    output=Path(folder)/'animation_prores4444.mov'
    extra_in,filters,audio_out=_backdrop(folder,fps,background,audio,['pcm_s16le'])
    cmd=[ffmpeg,'-n','-hide_banner','-loglevel','error','-framerate',str(fps),'-i',str(Path(folder)/'frame_%06d.png'),*extra_in,*filters,*audio_out,'-c:v','prores_ks','-profile:v','4','-pix_fmt','yuva444p10le','-alpha_bits','16',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode: raise RuntimeError(result.stderr[-2000:])
    return output

def encode_webm(folder, fps=30, quality=28, audio=None, background=None):
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
    extra_in,filters,audio_out=_backdrop(folder,fps,background,audio,['libopus','-b:a','128k'])
    cmd=[ffmpeg,'-n','-hide_banner','-loglevel','error',
         '-framerate',str(fps),'-i',str(folder/'frame_%06d.png'),*extra_in,*filters,
         *audio_out,'-c:v','libvpx-vp9','-deadline','good','-cpu-used','4',
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


def encode_mp4(folder, fps=30, background='white', audio=None):
    """Standard H.264 MP4 of the animation on a solid background color.

    MP4 has no transparency, so frames are composited over the chosen color
    (the same White/Dark colors as the preview). Plays everywhere and needs no
    WebM or ProRes. Source PNG frames are never removed here.
    """
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('FFmpeg was not found on PATH. PNG frames have still been exported.')
    from backgrounds import TEXTURES
    textures={t.lower():t for t in TEXTURES}
    background=(background or 'white').lower()
    if background=='transparent':
        background='white'                      # MP4 cannot be transparent
    custom=background.startswith('#')
    if background not in MP4_BACKGROUNDS and background not in textures and not custom:
        raise ValueError('MP4 background must be white, dark, black, a texture or a colour.')
    folder=Path(folder)
    info=json.loads((folder/'sequence.json').read_text())
    width,height=int(info['width']),int(info['height'])
    output=folder/f'animation_{"custom" if custom else background}_background.mp4'
    if background in textures or custom:
        from backgrounds import picture_png
        texture=picture_png(background,width,height,folder/'background.png')
        background_input=['-loop','1','-framerate',str(fps),'-i',str(texture)]
    else:
        color=f"color=c=0x{MP4_BACKGROUNDS[background]}:s={width}x{height}:r={fps}"
        background_input=['-f','lavfi','-i',color]
    audio_in=['-i',str(audio)] if audio else []
    audio_out=(['-map','[v]','-map','2:a','-c:a','aac','-b:a','192k','-shortest'] if audio
               else ['-map','[v]','-an'])
    cmd=[ffmpeg,'-n','-hide_banner','-loglevel','error',
         '-framerate',str(fps),'-i',str(folder/'frame_%06d.png'),
         *background_input,*audio_in,
         '-filter_complex','[1:v][0:v]overlay=shortest=1:format=auto,format=yuv420p[v]',
         *audio_out,'-c:v','libx264','-preset','medium','-crf','16',
         '-movflags','+faststart',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        output.unlink(missing_ok=True)
        raise RuntimeError('MP4 encoding failed: '+result.stderr[-2000:])
    if not output.is_file() or output.stat().st_size<=0:
        raise RuntimeError('MP4 encoder did not produce a nonempty video.')
    return output


def import_svg_cached(filename):
    """import_svg, kept ready on disk (exp.130): the sample drawing every start opens took
    about a third of a second to read again each time. The copy is used only while the file,
    its size and the app version are unchanged."""
    import pickle
    path = Path(filename)
    try:
        from preview_cache import default_folder, digest
        from version import APP_VERSION
        st = path.stat()
        folder = default_folder().parent / 'svg-cache'
        kept = folder / (digest((str(path.resolve()), st.st_mtime_ns, st.st_size, APP_VERSION)) + '.pickle')
    except Exception:
        return import_svg(path)
    try:
        return pickle.loads(kept.read_bytes())
    except Exception:
        pass
    drawing = import_svg(path)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        part = kept.with_suffix('.part')
        part.write_bytes(pickle.dumps(drawing, protocol=pickle.HIGHEST_PROTOCOL))
        os.replace(part, kept)
    except Exception:
        pass
    return drawing
