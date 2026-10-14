import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import math
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt
from engine import Drawing, Stroke, import_svg, render, export_frames
from adaptive_hand import build_plan, plan_for, pil_image, qimage
from color_reveal import render_color_timeline, artwork_rect, last_stroke_canvas_endpoint

APP=QApplication.instance() or QApplication([])

def fixture(size=80):
    image=Image.new('RGBA',(size,size),(0,0,0,0))
    p=ImageDraw.Draw(image)
    p.ellipse((3,3,size*.68,size*.7),fill=(225,139,50,255))
    p.ellipse((size*.20,size*.20,size*.44,size*.45),fill=(0,0,0,0))
    p.line([(size*.64,size*.18),(size*.86,size*.35),(size*.68,size*.60),
            (size*.82,size*.78)],fill=(49,136,168,255),width=max(2,size//16))
    p.rectangle((size*.12,size*.78,size*.42,size*.91),fill=(187,64,99,128))
    p.rectangle((size-4,size-4,size-3,size-3),fill=(70,170,80,255))
    strokes=[Stroke('open contour',[(5,5),(30,8),(45,20)],width=2),
             Stroke('closed small region',[(10,62),(34,62),(34,73),(10,73),(10,62)],width=2),
             Stroke('last',[(10,10),(14,10)],width=2)]
    drawing=Drawing(strokes,(0,0,80,80),[])
    return drawing,qimage(image)

class AdaptiveTests(unittest.TestCase):
    def test_regions_infill_and_coverage(self):
        for size in (24,112):
            d,image=fixture(size)
            plan=build_plan(d,image,.12,.55)
            self.assertGreater(plan.region_count,2)
            self.assertTrue(any(not s.painting for s in plan.segments))
            self.assertTrue(any(s.painting for s in plan.segments))
            self.assertTrue(all(not rid or math.isfinite(plan.arrival[i])
                                for i,rid in enumerate(plan.labels)))
            self.assertEqual(plan.mask(.98).tobytes(),plan.mask(1).tobytes())
            self.assertEqual(plan.mask(0).getextrema(),(0,0))
            gw,gh=plan.size
            for seg in plan.segments:
                if not seg.painting: continue
                for f in (0,.25,.5,.75,1):
                    x=math.floor(seg.a[0]+(seg.b[0]-seg.a[0])*f)
                    y=math.floor(seg.a[1]+(seg.b[1]-seg.a[1])*f)
                    self.assertEqual(plan.labels[y*gw+x],seg.region)
            radii={round(s.radius,2) for s in plan.segments if s.painting}
            if size==112: self.assertGreater(len(radii),1)

    def test_brush_and_hand_share_clock_no_travel_paint(self):
        d,image=fixture(40); plan=build_plan(d,image)
        for seg in plan.segments[::max(1,len(plan.segments)//25)]:
            progress=.98*((seg.start+seg.end)/2)/plan.total
            active,tip=plan.state(progress)
            self.assertIs(active,seg)
            if seg.painting:
                self.assertAlmostEqual(tip[0],(seg.a[0]+seg.b[0])/2)
                self.assertAlmostEqual(tip[1],(seg.a[1]+seg.b[1])/2)
            else:
                self.assertIsNone(tip)
                a=.98*(seg.start+.00001)/plan.total
                b=.98*(seg.end-.00001)/plan.total
                self.assertEqual(plan.mask(a).tobytes(),plan.mask(b).tobytes())
        # Every arrival time belongs to a brush segment whose disk touches it.
        for cell,t in enumerate(plan.arrival):
            if not math.isfinite(t): continue
            x,y=cell%plan.size[0]+.5,cell//plan.size[0]+.5
            matching=[]
            for s in plan.segments:
                if s.painting and s.start-1e-8<=t<=s.end+1e-8:
                    f=(t-s.start)/(s.end-s.start)
                    p=(s.a[0]+(s.b[0]-s.a[0])*f,s.a[1]+(s.b[1]-s.a[1])*f)
                    matching.append(math.dist(p,(x,y))<=s.radius+1e-7)
            self.assertTrue(any(matching))

    def test_reordered_endpoint_and_cached_geometry(self):
        d,image=fixture()
        a=plan_for(d,image); rect=artwork_rect(d,image,1920,1080)
        end=last_stroke_canvas_endpoint(d,1920,1080)
        expected=((end[0]-rect.x())*a.size[0]/rect.width(),
                  (end[1]-rect.y())*a.size[1]/rect.height())
        self.assertEqual(a.origin,expected)
        self.assertEqual(a.segments[0].a,expected)
        d.strokes.reverse()
        b=plan_for(d,image)
        self.assertNotEqual(a.origin,b.origin)
        self.assertIsNot(a,b)

    def test_alpha_colors_hand_and_no_final_snap(self):
        d,image=fixture()
        kwargs=dict(width=320,height=240,duration=1,fade_duration=4,hold_duration=0,
                    final_image=image,reveal_mode='adaptive')
        end=render_color_timeline(d,1,**kwargs)
        almost=render_color_timeline(d,(1+4*.98)/5,**kwargs)
        self.assertEqual(pil_image(end).tobytes(),pil_image(almost).tobytes())
        expected=QImage(320,240,QImage.Format.Format_ARGB32_Premultiplied)
        expected.fill(Qt.GlobalColor.transparent)
        p=QPainter(expected); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(artwork_rect(d,image,320,240),image); p.end()
        self.assertEqual(pil_image(end).tobytes(),pil_image(expected).tobytes())
        # During painting, source PNG transparency must never erase SVG
        # contours that the brush has not replaced. Only the final settled
        # frame becomes the exact original PNG and its transparent background.
        for progress in (.25,.5,.75):
            frame=pil_image(render_color_timeline(d,(1+4*progress)/5,**kwargs))
            original=pil_image(expected)
            svg=pil_image(render(d,1,320,240))
            self.assertTrue(all(a==0 for a,b,c in zip(
                frame.getchannel('A').tobytes(),
                original.getchannel('A').tobytes(),
                svg.getchannel('A').tobytes()) if b==0 and c==0))
        plan=plan_for(d,image)
        seg=next(s for s in plan.segments if s.painting and s.end>plan.total*.1)
        progress=.98*(seg.start+seg.end)/2/plan.total
        fraction=(1+4*progress)/5
        hand=QImage(20,20,QImage.Format.Format_ARGB32); hand.fill(0xffff00ff)
        plain=render_color_timeline(d,fraction,**kwargs)
        visible=render_color_timeline(d,fraction,painting_hand=hand,**kwargs)
        self.assertNotEqual(pil_image(plain).tobytes(),pil_image(visible).tobytes())
        # Turning off the overlay does not change the plan or mask.
        self.assertIs(plan,plan_for(d,image))

    def test_unpainted_svg_contours_remain_in_clean_and_adaptive_modes(self):
        # Traced paths commonly extend beyond a color PNG's silhouette.
        # Their unpainted contours must remain visible during colorization.
        d,image=fixture(80)
        kwargs=dict(width=320,height=240,duration=1.,fade_duration=3.,
                    hold_duration=0,final_image=image)
        baseline=pil_image(render(d,1,320,240)).getchannel('A')
        settled=pil_image(render_color_timeline(
            d,1,reveal_mode='adaptive',**kwargs)).getchannel('A')
        # Deliberately examine lines that lie OUTSIDE final colored pixels:
        # old clean/adaptive code removed all these at painting onset.
        candidates=[(x,y) for y in range(240) for x in range(320)
                    if baseline.getpixel((x,y))>180
                    and settled.getpixel((x,y))==0]
        self.assertGreater(len(candidates),10)
        for mode in ('clean','adaptive','guided'):
            for progress in (.08,.4,.8):
                fraction=(1+3*progress)/4
                alpha=pil_image(render_color_timeline(
                    d,fraction,reveal_mode=mode,**kwargs)).getchannel('A')
                self.assertTrue(all(alpha.getpixel(p)>175 for p in candidates),
                                f'{mode} removed an unpainted SVG outline at {progress:.0%}')
        # Finished frame must always be the untouched original artwork.
        end=pil_image(render_color_timeline(d,1,reveal_mode='clean',**kwargs))
        self.assertEqual(end.getchannel('A').tobytes(),settled.tobytes())

    def test_preview_export_and_legacy_draw(self):
        d,image=fixture(40)
        options=dict(duration=.1,fade_duration=.3,hold_duration=.1,
                     final_image=image,reveal_mode='adaptive',stroke_spacing=.4)
        # Drawing stage is the original rendering engine byte for byte.
        early=render_color_timeline(d,.1,120,90,**options)
        self.assertEqual(pil_image(early).tobytes(),pil_image(render(d,.5,120,90)).tobytes())
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'frames'
            count=export_frames(d,folder,fps=20,width=120,height=90,**options)
            for i in (2,5,count-1):
                preview=render_color_timeline(d,i/(count-1),120,90,**options)
                saved=QImage(str(folder/f'frame_{i:06d}.png'))
                self.assertEqual(pil_image(preview).tobytes(),pil_image(saved).tobytes())

    def test_headset_trace_with_representative_alpha_only(self):
        # This is NOT the missing original colored headset PNG.
        d=import_svg(Path(__file__).parent/'samples/arthur-headset-traced.svg')
        image=QImage(48,64,QImage.Format.Format_ARGB32); image.fill(0xffd4b77a)
        plan=build_plan(d,image)
        self.assertTrue(plan.segments)
        self.assertTrue(all(math.isfinite(t) for t in plan.arrival))

if __name__=='__main__':
    unittest.main(verbosity=2)
