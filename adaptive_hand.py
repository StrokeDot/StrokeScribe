"""Experimental region-constrained brush infill, without opacity or diffusion.

A deterministic canonical grid is shared by preview and export. Every revealed
cell is rasterized by an actual brush stamp on the timed route. Travel does not
stamp. The planner audits coverage and adds real repair strokes before playback.
"""
from __future__ import annotations
import bisect
import hashlib
import math
from collections import OrderedDict, deque
from dataclasses import dataclass
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

_CACHE = OrderedDict()
GRID_LIMIT = 224
NEIGHBORS = ((1,0),(-1,0),(0,1),(0,-1))

def pil_image(image):
    q = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA', (q.width(), q.height()), bytes(q.constBits()),
                           'raw', 'RGBA', q.bytesPerLine())

def qimage(image):
    rgba = image.convert('RGBA')
    data = rgba.tobytes()
    return QImage(data, rgba.width, rgba.height, rgba.width*4,
                  QImage.Format.Format_RGBA8888).copy()

@dataclass(frozen=True)
class Segment:
    a: tuple
    b: tuple
    radius: float
    region: int
    painting: bool
    start: float
    end: float

@dataclass
class PaintPlan:
    size: tuple
    labels: list
    segments: list
    ends: list
    arrival: list
    origin: tuple
    total: float
    warnings: list
    region_count: int

    def state(self, progress):
        # Complete the actual route at 98%, leaving a short settled ending.
        clock = max(0., min(1., float(progress)))/.98*self.total
        if not self.segments or clock >= self.total:
            return None, None
        index = bisect.bisect_left(self.ends, clock)
        segment = self.segments[index]
        f = min(1., max(0., (clock-segment.start)/(segment.end-segment.start)))
        point = (segment.a[0]+(segment.b[0]-segment.a[0])*f,
                 segment.a[1]+(segment.b[1]-segment.a[1])*f)
        return segment, point if segment.painting else None

    def mask(self, progress):
        clock = max(0., min(1., float(progress)))/.98*self.total
        # No full-image shortcut, including at progress==1.
        return Image.frombytes('L', self.size, bytes(
            255 if t <= clock and progress > 0 else 0 for t in self.arrival))

def _components(labels, width, height):
    """Split disconnected pieces even if they share a closed-contour ID."""
    output = [0]*len(labels)
    groups = []
    for first, label in enumerate(labels):
        if not label or output[first]:
            continue
        rid = len(groups)+1
        queue = deque([first]); output[first] = rid; cells = []
        while queue:
            cell = queue.popleft(); cells.append(cell)
            x,y = cell%width, cell//width
            for dx,dy in NEIGHBORS:
                xx,yy=x+dx,y+dy
                if 0<=xx<width and 0<=yy<height:
                    n=yy*width+xx
                    if not output[n] and labels[n]==label:
                        output[n]=rid; queue.append(n)
        groups.append(cells)
    return output,groups

def _shortest(start, finish, region, labels, width, height):
    if start == finish:
        return []
    queue=deque([start]); previous={start:None}
    while queue:
        cell=queue.popleft()
        x,y=cell%width,cell//width
        for dx,dy in NEIGHBORS:
            xx,yy=x+dx,y+dy
            if 0<=xx<width and 0<=yy<height:
                n=yy*width+xx
                if labels[n]==region and n not in previous:
                    previous[n]=cell
                    if n==finish:
                        path=[n]
                        while previous[path[-1]] != start:
                            path.append(previous[path[-1]])
                        return list(reversed(path))
                    queue.append(n)
    raise ValueError('Region traversal failed; no safe brush connection.')

def build_plan(drawing, image, brush_width=.14, stroke_spacing=.55):
    from color_reveal import artwork_rect, last_stroke_canvas_endpoint
    source=pil_image(image)
    iw,ih=source.size
    ratio=min(1.,GRID_LIMIT/max(iw,ih))
    gw,gh=max(1,math.ceil(iw*ratio)),max(1,math.ceil(ih*ratio))
    rect=artwork_rect(drawing,image,1920,1080)
    def grid_point(point):
        return ((point[0]-rect.x())*gw/rect.width(),
                (point[1]-rect.y())*gh/rect.height())
    origin=grid_point(last_stroke_canvas_endpoint(drawing,1920,1080))
    # Conservative support: retain even tiny disconnected alpha details.
    support=bytearray(gw*gh)
    for i,a in enumerate(source.getchannel('A').tobytes()):
        if a:
            support[min(gh-1,(2*(i//iw)+1)*gh//(2*ih))*gw+min(gw-1,(2*(i%iw)+1)*gw//(2*iw))]=1
    if not any(support):
        raise ValueError('The color image has no nontransparent pixels.')
    labels=[1 if a else 0 for a in support]
    polygons=[]
    x0,y0,x1,y1=drawing.bounds
    scale=min(1920*.82/max(1,x1-x0),1080*.78/max(1,y1-y0))
    ox=(1920-(x1-x0)*scale)/2-x0*scale
    oy=(1080-(y1-y0)*scale)/2-y0*scale
    for stroke in drawing.strokes:
        pts=[grid_point((x*scale+ox,y*scale+oy)) for x,y in stroke.points]
        if len(pts)<4 or math.dist(pts[0],pts[-1])>1.:
            continue
        mask=Image.new('L',(gw,gh))
        ImageDraw.Draw(mask).polygon(pts, fill=1)
        data=mask.tobytes()
        area=sum(a and b for a,b in zip(data,support))
        if area>=4:
            polygons.append((area,data))
    # Small closed interiors first. Open strokes are not imaginary boundaries.
    assigned=bytearray(gw*gh)
    for rid,(_,polygon) in enumerate(sorted(polygons,key=lambda item:item[0]),2):
        for i,inside in enumerate(polygon):
            if inside and support[i] and not assigned[i]:
                labels[i]=rid; assigned[i]=1
    image_regions=getattr(drawing,'image_regions',None)
    if image_regions is not None:
        # Image reconstruction supplies coarse color regions. Preserve the
        # existing SVG segmentation path when this metadata is absent.
        region_image=Image.new('I',image_regions.size)
        region_image.putdata(image_regions.labels)
        region_image=region_image.resize((gw,gh),Image.Resampling.NEAREST)
        ids=list(region_image.getdata())
        labels=[(rid+1 if rid else 1) if support[i] else 0
                for i,rid in enumerate(ids)]
    old_labels=labels[:]
    labels,groups=_components(labels,gw,gh)
    # Model-proposed semantic order applies to actual connected components,
    # not the raw coarse box coordinates. Disconnected fragments still receive
    # independent brush passes.
    semantic=getattr(drawing,'image_semantic_order',())
    ranks={int(region):i for i,region in enumerate(semantic)}
    component_priority={
        i: ranks.get(old_labels[cells[0]]-1,len(ranks)+1)
        for i,cells in enumerate(groups,1)}
    # Grid distance to a region boundary controls local brush size.
    clearance=[0]*len(labels); queue=deque()
    for cell,rid in enumerate(labels):
        if not rid: continue
        x,y=cell%gw,cell//gw
        if any(not(0<=x+dx<gw and 0<=y+dy<gh) or
               labels[(y+dy)*gw+x+dx]!=rid for dx,dy in NEIGHBORS):
            clearance[cell]=1; queue.append(cell)
    while queue:
        cell=queue.popleft(); x,y=cell%gw,cell//gw
        for dx,dy in NEIGHBORS:
            xx,yy=x+dx,y+dy
            if 0<=xx<gw and 0<=yy<gh:
                n=yy*gw+xx
                if labels[n]==labels[cell] and not clearance[n]:
                    clearance[n]=clearance[cell]+1; queue.append(n)
    maximum=max(.72,gw*max(.02,min(.5,float(brush_width)))/2)
    spacing=max(.2,min(.9,float(stroke_spacing)))
    gap=max(1,round(2*maximum*spacing))
    arrival=[float('inf')]*len(labels)
    segments=[]; clock=0.; cursor=origin
    def center(cell):
        return (cell%gw+.5,cell//gw+.5)
    def cell_at(point):
        x,y=math.floor(point[0]),math.floor(point[1])
        return y*gw+x if 0<=x<gw and 0<=y<gh else None
    def stamp(point,radius,rid,when):
        # Pixel-center disk footprints; region clip prevents boundary bleed.
        x,y=point
        for yy in range(max(0,math.floor(y-radius)),min(gh,math.ceil(y+radius))):
            for xx in range(max(0,math.floor(x-radius)),min(gw,math.ceil(x+radius))):
                cell=yy*gw+xx
                if labels[cell]==rid and (xx+.5-x)**2+(yy+.5-y)**2<=radius**2:
                    arrival[cell]=min(arrival[cell],when)
    def move(point,rid,painting,radius=.72):
        nonlocal cursor,clock
        distance=math.dist(cursor,point)
        duration=max(.05,distance) if painting else max(.5,min(12.,distance*.2))
        seg=Segment(cursor,point,radius,rid,painting,clock,clock+duration)
        segments.append(seg)
        if painting:
            steps=max(1,math.ceil(distance/.35))
            for j in range(steps+1):
                f=j/steps
                stamp((cursor[0]+(point[0]-cursor[0])*f,
                       cursor[1]+(point[1]-cursor[1])*f),radius,rid,clock+duration*f)
        clock+=duration; cursor=point
    def radius(cell):
        return min(maximum,max(.72,(clearance[cell]-.5)*.7))
    def paint_to(cell,rid):
        start=cell_at(cursor)
        if start is None or labels[start]!=rid:
            move(center(cell),rid,False)
            start=cell
        else:
            # Within-cell connection remains inside the selected raster region.
            move(center(start),rid,True,radius(start))
        for n in _shortest(start,cell,rid,labels,gw,gh):
            move(center(n),rid,True,min(radius(start),radius(n)))
            start=n
        if not math.isfinite(arrival[cell]):
            move(center(cell),rid,True,radius(cell))

    remaining=list(enumerate(groups,1))
    warnings=[]
    c=cell_at(origin)
    if c is None or labels[c]==0:
        warnings.append('Final SVG endpoint is outside PNG alpha: initial transfer is pen-up. Check alignment.')
    first_region=True
    largest_region=max(map(len,groups))
    while remaining:
        # For image reconstruction, block large regions before small accents.
        # The first region still follows the actual final drawing endpoint.
        pool=list(enumerate(remaining))
        if semantic and not first_region:
            # Draw named objects in the AI's deliberate sequence; background
            # and unclassified color fragments follow after named objects.
            best=min(component_priority.get(rid,len(ranks)+1)
                     for _,(rid,cells) in pool)
            pool=[entry for entry in pool
                  if component_priority.get(entry[1][0],len(ranks)+1)==best]
        elif getattr(drawing,'image_region_priority',False) and not first_region:
            def band(cells):
                return 0 if len(cells)>=largest_region*.15 else (1 if len(cells)>=largest_region*.025 else 2)
            best=min(band(cells) for _,(_,cells) in pool)
            pool=[item for item in pool if band(item[1][1])==best]
        first_region=False
        # Nearest region, preserving the actual final stroke as route origin.
        ri,entry=min(((i,min(cells,key=lambda c:math.dist(cursor,center(c))))
                      for i,(_,cells) in pool),
                     key=lambda pair:math.dist(cursor,center(pair[1])))
        rid,cells=remaining.pop(ri)
        paint_to(entry,rid)
        xs=[c%gw for c in cells]; ys=[c//gw for c in cells]
        vertical=max(ys)-min(ys) > 1.25*(max(xs)-min(xs))
        # One family's scanlines per region. Each run is clipped by that region.
        rows={}
        for cell in cells:
            x,y=cell%gw,cell//gw
            row,col=(x,y) if vertical else (y,x)
            rows.setdefault(row,[]).append(col)
        keys=sorted(rows)
        if abs(keys[-1]-(cursor[0] if vertical else cursor[1])) < abs(keys[0]-(cursor[0] if vertical else cursor[1])):
            keys.reverse()
        selected=keys[::gap]
        if keys[-1] not in selected: selected.append(keys[-1])
        for index,row in enumerate(selected):
            cols=sorted(rows[row],reverse=bool(index%2))
            runs=[]; run=[]
            for col in cols:
                if run and abs(col-run[-1])!=1:
                    runs.append(run); run=[]
                run.append(col)
            if run: runs.append(run)
            # Never directly join runs across a hole; route through the region.
            for run in runs:
                ids=[col*gw+row if vertical else row*gw+col for col in run]
                paint_to(ids[0],rid)
                prev=ids[0]
                for cell in ids[1:]:
                    move(center(cell),rid,True,min(radius(prev),radius(cell)))
                    prev=cell
        # Coverage repair is planned, timed physical painting, not a final fill.
        missing={cell for cell in cells if not math.isfinite(arrival[cell])}
        while missing:
            target=min(missing,key=lambda cell:math.dist(cursor,center(cell)))
            paint_to(target,rid)
            missing={cell for cell in missing if not math.isfinite(arrival[cell])}
    assert all(not rid or math.isfinite(arrival[i]) for i,rid in enumerate(labels))
    return PaintPlan((gw,gh),labels,segments,[s.end for s in segments],arrival,
                     origin,clock,warnings,len(groups))

def plan_for(drawing,image,brush_width=.14,stroke_spacing=.55):
    # Content-based keys survive deepcopy/export and include the full stroke order.
    geometry=tuple((s.name,tuple(s.points)) for s in drawing.strokes)
    raw=pil_image(image)
    region_map=getattr(drawing,'image_regions',None)
    key=(geometry,region_map,getattr(drawing,'image_region_priority',False),
         getattr(drawing,'image_semantic_order',()),tuple(drawing.bounds),raw.size,
         hashlib.sha256(raw.getchannel('A').tobytes()).digest(),
         float(brush_width),float(stroke_spacing))
    if key not in _CACHE:
        _CACHE[key]=build_plan(drawing,image,brush_width,stroke_spacing)
        if len(_CACHE)>3: _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return _CACHE[key]

def adaptive_paint_mask(drawing,image,width,height,rect,progress,brush_width,stroke_spacing=.55):
    plan=plan_for(drawing,image,brush_width,stroke_spacing)
    alpha=plan.mask(progress)
    alpha=alpha.resize((image.width(),image.height()),Image.Resampling.NEAREST)
    small=Image.new('RGBA',alpha.size,(255,255,255,0)); small.putalpha(alpha)
    mask=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    painter=QPainter(mask)
    # Nearest-neighbor keeps the exact discrete footprint at every resolution.
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(rect,qimage(small)); painter.end()
    segment,tip=plan.state(progress)
    if tip is not None:
        tip=(rect.x()+tip[0]*rect.width()/plan.size[0],
             rect.y()+tip[1]*rect.height()/plan.size[1])
    return mask,tip

def render_adaptive(drawing,image,width,height,progress,thickness,brush_width,
                    stroke_spacing,hand,hand_scale,anchor):
    from color_reveal import artwork_rect,draw_hand
    from engine import render
    rect=artwork_rect(drawing,image,width,height)
    # All cells were painted by the real stroke plan at 98%. Render the
    # settled original PNG directly rather than recompositing it over SVG
    # outlines; this preserves exact colors/alpha and avoids dark fringes.
    if progress>=.98:
        frame=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(Qt.GlobalColor.transparent)
        painter=QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        from source_render import draw_source
        draw_source(painter,rect,image)
        painter.end()
        return frame
    mask,tip=adaptive_paint_mask(drawing,image,width,height,rect,progress,
                                brush_width,stroke_spacing)
    # The brush mask governs BOTH colored pixels and temporary SVG ink.
    # Using only the PNG alpha to erase outlines would strand misregistered
    # guides in transparent areas until the final frame.
    painted=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    painted.fill(Qt.GlobalColor.transparent)
    p=QPainter(painted)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    from source_render import draw_source
    draw_source(p,rect,image)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawImage(0,0,mask)
    p.end()
    from svg_guide_cleanup import remove_svg_guides
    outline=remove_svg_guides(render(drawing,1,width,height,thickness),
                              mask,image,rect)
    # Assemble on a fresh premultiplied canvas, exactly like the settled
    # frame. Compositing onto the SVG layer's own image format rounded some
    # semi-transparent edge pixels, so a fully painted frame could differ
    # slightly from the final frame and flicker at the end.
    frame=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
    frame.fill(Qt.GlobalColor.transparent)
    p=QPainter(frame)
    p.drawImage(0,0,outline)
    p.drawImage(0,0,painted)
    draw_hand(p,tip,hand,width,hand_scale,anchor)
    p.end()
    return frame
