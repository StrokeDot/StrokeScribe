import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile, unittest, math, copy, json, shutil, subprocess
from pathlib import Path
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from engine import render, export_frames, encode_mov, import_svg
from adaptive_hand import plan_for, pil_image, qimage
from image_reconstruct import reconstruct, load_raster
from image_drawing import drawing_state
from color_reveal import render_color_timeline
APP=QApplication.instance() or QApplication([])

def artwork():
    im=Image.new('RGBA',(112,96))
    p=ImageDraw.Draw(im)
    p.rounded_rectangle((4,4,76,86),radius=16,fill=(240,130,40,255))
    p.ellipse((19,20,52,59),fill=(30,140,190,255))
    p.ellipse((28,29,43,48),fill=(0,0,0,0))
    p.line([(85,5),(101,25),(86,45),(103,67)],fill=(160,45,100,255),width=5)
    p.rectangle((84,80,103,89),fill=(40,190,80,128))
    return im

class ImageSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.path=self.root/'source.png'; artwork().save(self.path)
    def tearDown(self): self.tmp.cleanup()
    def result(self,mode='line_art'): return reconstruct(self.path,mode,'low')
    def test_formats_and_original_pixels(self):
        original=artwork(); cropped=original.crop(original.getbbox())
        self.assertEqual(load_raster(self.path).tobytes(),cropped.tobytes())
        for ext in ('jpg','webp','bmp'):
            path=self.root/('source.'+ext)
            im=original.convert('RGB') if ext in ('jpg','bmp') else original
            im.save(path)
            self.assertGreater(len(reconstruct(path,detail='low').drawing.strokes),0)
        blank=self.root/'blank.png'; Image.new('RGBA',(10,10)).save(blank)
        with self.assertRaisesRegex(ValueError,'transparent'): load_raster(blank)
    def test_modes_contours_and_regions(self):
        r=self.result()
        self.assertTrue(r.drawing.strokes)
        self.assertGreater(r.regions.count,2)
        self.assertTrue(all(s.length>0 for s in r.drawing.strokes))
        self.assertEqual(r.drawing.source_mode,'line_art')
        # Line art is the only image method now.
        for removed in ('auto_trace','stroke_reconstruction','ai_redraw','unknown_mode'):
            with self.assertRaises(ValueError): reconstruct(self.path,removed)
    def test_coverage_reordering_and_travel(self):
        r=self.result(); d=r.drawing
        plan=plan_for(d,r.image)
        self.assertTrue(all(not label or math.isfinite(plan.arrival[i]) for i,label in enumerate(plan.labels)))
        self.assertEqual(plan.mask(.98).tobytes(),plan.mask(1).tobytes())
        self.assertTrue(any(not s.painting for s in plan.segments))
        d.strokes.reverse(); other=plan_for(d,r.image)
        self.assertNotEqual(plan.origin,other.origin)
        self.assertIsNot(plan,other)
        for seg in other.segments[::max(1,len(other.segments)//40)]:
            progress=.98*(seg.start+seg.end)/2/other.total
            active,tip=other.state(progress)
            # The hand stays visible on painting and pen-up travel alike.
            self.assertIsNotNone(tip)
    def test_drawing_hand_lifts(self):
        r=self.result(); states=[drawing_state(r.drawing,i/2000) for i in range(2001)]
        self.assertTrue(any(not s.painting and 0<s.stroke_progress<1 for s in states))
        self.assertEqual(states[-1].stroke_progress,1)
        hand=qimage(Image.new('RGBA',(8,8),(255,0,255,255)))
        index=next(i for i,s in enumerate(states) if not s.painting and 0<s.stroke_progress<1)
        no=render(r.drawing,index/2000,160,90)
        yes=render(r.drawing,index/2000,160,90,hand=hand)
        # During a pen lift the hand stays visible (no blinking) ...
        self.assertNotEqual(pil_image(no).tobytes(),pil_image(yes).tobytes())
        self.assertIsNotNone(states[index].lift_point)
        # ... but no ink is added while the pen is lifted.
        before=pil_image(render(r.drawing,(index-1)/2000,160,90)).tobytes()
        if not states[index-1].painting:
            self.assertEqual(before,pil_image(no).tobytes())
        # Every frame of the drawing phase has a hand position.
        self.assertTrue(all(s.painting or s.lift_point is not None
                            for s in states[1:-1]))
    def test_export_preview_and_alpha(self):
        r=self.result()
        options=dict(duration=.3,fps=10,width=160,height=90,final_image=r.image,
                     fade_duration=.7,hold_duration=0,reveal_mode='adaptive')
        folder=self.root/'frames'; count=export_frames(r.drawing,folder,**options)
        for i in (0,count//2,count-1):
            frame=Image.open(folder/f'frame_{i:06d}.png').convert('RGBA')
            kwargs={k:v for k,v in options.items() if k!='fps'}
            expected=pil_image(render_color_timeline(copy.deepcopy(r.drawing),i/(count-1),**kwargs))
            self.assertEqual(frame.tobytes(),expected.tobytes())
            self.assertEqual(frame.getpixel((0,0))[3],0)
        self.assertEqual(Image.open(folder/'frame_000000.png').getchannel('A').getextrema(),(0,0))
        if shutil.which('ffmpeg'):
            mov=encode_mov(folder,10)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-show_streams','-of','json',str(mov)]))
            self.assertEqual(probe['streams'][0]['codec_name'],'prores')
            self.assertIn('a',probe['streams'][0]['pix_fmt'])
    def test_background_builder_prepares_route(self):
        from app import ImageBuilder
        ready=[]; errors=[]
        worker=ImageBuilder(str(self.path),'low',.14,.55)
        worker.ready.connect(ready.append); worker.failed.connect(errors.append)
        worker.run()
        self.assertFalse(errors)
        self.assertEqual(len(ready),1)
        self.assertTrue(plan_for(ready[0].drawing,ready[0].image).segments)
    def test_ui_source_switch_preserves_svg(self):
        from app import Window
        w=Window(); old=w.drawing
        w.source_type.setCurrentIndex(1); self.assertIsNone(w.drawing)
        w.image_ready(self.result())
        self.assertEqual(w.options()['reveal_mode'],'adaptive')
        self.assertIsNotNone(w.options()['final_image'])
        w.preserve_colors.setChecked(False); self.assertIsNone(w.options()['final_image'])
        w.source_type.setCurrentIndex(0); self.assertIs(w.drawing,old)
        self.assertEqual(w.options()['reveal_mode'],'fade')
        w.close()

if __name__=='__main__': unittest.main()
