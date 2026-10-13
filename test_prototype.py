import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json, tempfile, unittest, subprocess, shutil, time
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from engine import import_svg, render, export_frames, encode_mov
from lettering import make_text
from color_reveal import load_color_image, render_color_timeline, brush_route, paint_mask, artwork_rect

APP=QApplication.instance() or QApplication([])
HERE=Path(__file__).parent

def rgba(image):
    image=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA',(image.width(),image.height()),bytes(image.bits()))

class PrototypeTests(unittest.TestCase):
    def test_geometry_direction_and_pen_lift(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'test.svg'
            file.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(20 30)" stroke="black" fill="none"><path d="M100 0 L0 0 M0 100 L100 100"/></g></svg>')
            d=import_svg(file)
            self.assertEqual(len(d.strokes),2)
            self.assertEqual(d.strokes[0].points[0],(120,30))
            self.assertEqual(d.strokes[0].points[-1],(20,30))
            frame=rgba(render(d,.25,400,400)); a=frame.getchannel('A')
            self.assertGreater(a.getpixel((330,44)),0) # right-hand start
            self.assertEqual(a.getpixel((60,44)),0) # left-hand end still absent
            self.assertEqual(a.getpixel((200,200)),0) # no connecting stroke
            end=rgba(render(d,1,400,400))
            self.assertEqual(end.getchannel('A').getpixel((200,200)),0)
    def test_sample_alpha_and_progress(self):
        d=import_svg(HERE/'samples/drawing.svg'); counts=[]
        for p in (0,.25,.5,1):
            a=rgba(render(d,p)).getchannel('A'); counts.append(sum(v>0 for v in a.getdata()))
            self.assertEqual(a.getpixel((0,0)),0)
        self.assertEqual(counts[0],0)
        self.assertTrue(all(a<b for a,b in zip(counts,counts[1:])))
    def test_text_and_hand(self):
        d=make_text('Hello 123!'); self.assertGreater(len(d.strokes),10)
        hand=QImage(20,20,QImage.Format.Format_ARGB32); hand.fill(0xffff0000)
        clean=rgba(render(d,.5,400,200)); over=rgba(render(d,.5,400,200,hand=hand))
        self.assertNotEqual(clean.tobytes(),over.tobytes())
        self.assertEqual(rgba(render(d,1,400,200,hand=hand)).tobytes(),rgba(render(d,1,400,200)).tobytes())
    def test_exports_and_cancel(self):
        d=import_svg(HERE/'samples/drawing.svg')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'frames'; n=export_frames(d,folder,.5,10,2048,1080)
            self.assertEqual(n,5)
            first=Image.open(folder/'frame_000000.png'); last=Image.open(folder/'frame_000004.png')
            self.assertEqual(first.size,(2048,1080)); self.assertEqual(first.getchannel('A').getextrema(),(0,0)); self.assertEqual(last.getchannel('A').getextrema(),(0,255))
            with self.assertRaises(FileExistsError): export_frames(d,folder)
            with self.assertRaises(InterruptedError): export_frames(d,Path(tmp)/'cancel',callback=lambda i,n:False)
    def test_color_reveal_png_and_export(self):
        d=import_svg(HERE/'samples/drawing.svg')
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp)/'art.png'
            colored=Image.new('RGBA',(72,60),(0,0,0,0))
            from PIL import ImageDraw
            ImageDraw.Draw(colored).rectangle((10,10,61,49),fill=(247,61,23,255))
            colored.save(original)
            artwork=load_color_image(original)
            self.assertEqual((artwork.width(),artwork.height()),(52,40))
            first=rgba(render_color_timeline(d,0,400,300,duration=.4,fade_duration=.2,hold_duration=.4,final_image=artwork))
            self.assertEqual(first.getchannel('A').getextrema(),(0,0))
            end=rgba(render_color_timeline(d,1,400,300,duration=.4,fade_duration=.2,hold_duration=.4,final_image=artwork))
            self.assertEqual(end.getpixel((0,0))[3],0)
            center=end.getpixel((200,150))
            self.assertGreater(center[0],240)
            self.assertLess(center[1],65)
            self.assertEqual(center[3],255)
            folder=Path(tmp)/'color_sequence'
            count=export_frames(d,folder,duration=.4,fps=10,width=400,height=300,
                                final_image=artwork,fade_duration=.2,hold_duration=.4)
            self.assertEqual(count,10)
            self.assertEqual(Image.open(folder/'frame_000000.png').getchannel('A').getextrema(),(0,0))
            self.assertEqual(Image.open(folder/'frame_000009.png').getpixel((200,150)),center)
            metadata=json.loads((folder/'sequence.json').read_text())
            self.assertTrue(metadata['color_reveal'])
            self.assertEqual(metadata['last_frame'],'original_color_png')
    def test_brush_paint_reveal_optional_hand_and_export(self):
        d=import_svg(HERE/'samples/drawing.svg')
        with tempfile.TemporaryDirectory() as tmp:
            picture=Path(tmp)/'original.png'
            colored=Image.new('RGBA',(80,64),(0,0,0,0))
            from PIL import ImageDraw
            ImageDraw.Draw(colored).rectangle((4,4,75,59),fill=(245,64,32,255))
            colored.save(picture)
            artwork=load_color_image(picture)
            params=dict(duration=.4,fade_duration=.4,hold_duration=.2,
                        final_image=artwork,reveal_mode='brush',brush_width=.15)
            first=rgba(render_color_timeline(d,0,400,300,**params))
            partial=rgba(render_color_timeline(d,.6,400,300,**params))
            finished=rgba(render_color_timeline(d,1,400,300,**params))
            self.assertEqual(first.getchannel('A').getextrema(),(0,0))
            self.assertEqual(finished.getpixel((0,0))[3],0)
            self.assertEqual(finished.getpixel((200,150)),(245,64,32,255))
            def reds(frame):
                return sum(1 for r,g,b,a in frame.getdata() if r>220 and g<100 and a>200)
            self.assertGreater(reds(partial),0)
            self.assertLess(reds(partial),reds(finished))
            hand=QImage(20,20,QImage.Format.Format_ARGB32)
            hand.fill(0xff00ff00)
            with_hand=rgba(render_color_timeline(d,.6,400,300,painting_hand=hand,**params))
            self.assertNotEqual(partial.tobytes(),with_hand.tobytes())
            self.assertEqual(finished.tobytes(),
                             rgba(render_color_timeline(d,1,400,300,painting_hand=hand,**params)).tobytes())
            for f in (.01,.2,.5,.8,1.):
                rect=artwork_rect(d,artwork,400,300)
                mask,tip=paint_mask(400,300,rect,f,.15)
                self.assertFalse(mask.isNull())
                if f<1: self.assertIsNotNone(tip)
            folder=Path(tmp)/'brush_frames'
            count=export_frames(d,folder,duration=.4,fps=10,width=400,height=300,
                                final_image=artwork,fade_duration=.4,hold_duration=.2,
                                reveal_mode='brush',brush_width=.15,painting_hand=None)
            self.assertEqual(count,10)
            self.assertEqual(Image.open(folder/'frame_000009.png').getpixel((200,150)),(245,64,32,255))
            info=json.loads((folder/'sequence.json').read_text())
            self.assertEqual(info['reveal_mode'],'brush')
            self.assertFalse(info['painting_hand'])
    def test_ui(self):
        from app import Window
        w=Window(); w.show(); APP.processEvents(); w.slider.setValue(500); APP.processEvents()
        self.assertAlmostEqual(w.position,.5); self.assertIsNotNone(w.canvas.frame)
        old=w.drawing.strokes[0]; w.order.setCurrentRow(0); w.move(1); self.assertIs(w.drawing.strokes[1],old)
        w.restart(); time.sleep(.04); w.tick(); self.assertGreater(w.position,0)
        w.playing=False; w.slider.setValue(600); APP.processEvents()
        (HERE/'test-output').mkdir(exist_ok=True)
        w.grab().save(str(HERE/'test-output/app-preview.png')); w.close()

if __name__=='__main__': unittest.main(verbosity=2)
