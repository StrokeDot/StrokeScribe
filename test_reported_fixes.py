"""Regression checks for reported broken lettering and the Studio toolbar."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from app import Window
from engine import render
from font_library import make_font_text
from test_image_source import artwork

APP=QApplication.instance() or QApplication([])


def find_font():
    for path in (Path('C:/Windows/Fonts/segoeui.ttf'),
                 Path('C:/Windows/Fonts/arial.ttf'),
                 Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')):
        if path.is_file():return path
    return None


class FakeResponse:
    def __init__(self,contents):
        self.contents=contents
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):return json.dumps(
        {'message':{'content':self.contents},'done_reason':'stop'}).encode()


class ReportedBugTests(unittest.TestCase):
    def test_full_glyphs_are_opaque_and_legible_not_broken_fragments(self):
        font=find_font()
        if not font:self.skipTest('No local TTF in CI environment')
        drawing=make_font_text('Hello world!',font,72)
        self.assertEqual(drawing.source_kind,'font')
        self.assertGreaterEqual(len(drawing.strokes),10)
        first=render(drawing,0,1500,600)
        mid=render(drawing,.5,1500,600)
        last=render(drawing,1,1500,600)
        def coverage(image):
            alpha=image.convertToFormat(QImage.Format.Format_RGBA8888)
            return sum(bytes(alpha.constBits())[3::4][::1])//255
        c0,c5,c10=map(coverage,(first,mid,last))
        self.assertEqual(c0,0)
        self.assertGreater(c5,500)
        self.assertGreater(c10,c5)
        self.assertGreater(c10,1300,
            'Complete lettering should contain real filled glyph pixels')
        # The final font bitmap must be unchanged by the stroke animation.
        self.assertGreater(drawing.font_ink.getchannel('A').getextrema()[1],240)
        # The reveal timing must be based on the actual pen centerlines, not
        # a uniformly progressing vertical clipping rectangle.
        from font_stroke_reveal import _timing_field
        import numpy as np
        times,total=_timing_field(drawing)
        visible=np.asarray(drawing.font_ink.getchannel('A'))>100
        self.assertGreater(total,20)
        self.assertGreater(np.ptp(times[visible]),.6)
        max_vertical_variation=max((
            float(np.ptp(times[:,x][visible[:,x]]))
            for x in range(times.shape[1])
            if np.count_nonzero(visible[:,x])>=4
        ),default=0.)
        self.assertGreater(max_vertical_variation,.025,
            'A horizontal wipe has identical timing for all pixels in each column.')
        self.assertGreater(sum(s.length for s in drawing.strokes),50)
        self.assertTrue(any(len(s.points)>4 for s in drawing.strokes),
                        'Letter paths should follow curves, not rectangle midlines.')

    def test_single_active_stroke_and_no_ink_during_pen_lift(self):
        from PIL import Image, ImageDraw
        import numpy as np
        from engine import Drawing, Stroke
        from font_stroke_reveal import (_stroke_schedule, _pen_state,
                                        _ink_ownership, render_traced_font)
        ink=Image.new('RGBA',(120,60),(0,0,0,0))
        p=ImageDraw.Draw(ink)
        p.line((10,15,48,15),fill=(37,54,74,255),width=5)
        p.line((72,42,109,42),fill=(37,54,74,255),width=5)
        a=Stroke('first',[(10.,15.),(48.,15.)])
        b=Stroke('second',[(72.,42.),(109.,42.)])
        d=Drawing([a,b],(0.,0.,120.,60.),[])
        d.font_ink=ink
        d.source_kind='font'
        events,total=_stroke_schedule(d)
        self.assertEqual([e[0] for e in events],['draw','lift','draw'])
        self.assertEqual([e[1] for e in events],[0,None,1])
        self.assertLessEqual(events[0][3],events[1][2])
        self.assertLessEqual(events[1][3],events[2][2])
        timing,owner,_=_ink_ownership(d)
        self.assertTrue(np.any(owner==0))
        self.assertTrue(np.any(owner==1))
        self.assertGreaterEqual(float(timing[owner==1].min()),events[2][2]/total-1e-6)
        self.assertLessEqual(float(timing[owner==0].max()),events[0][3]/total+1e-6)
        lift_start=events[1][2]/total
        lift_middle=(events[1][2]+events[1][3])/(2*total)
        lift_end=(events[1][3]-1e-4)/total
        def alpha(f):
            frame=render_traced_font(d,f,480,240)
            frame=frame.convertToFormat(QImage.Format.Format_RGBA8888)
            return bytes(frame.constBits())[3::4]
        self.assertEqual(alpha(lift_start),alpha(lift_middle))
        self.assertEqual(alpha(lift_middle),alpha(lift_end))
        self.assertNotEqual(alpha(events[0][2]/total+.01),alpha(lift_start))
        self.assertNotEqual(alpha(lift_end),alpha(.95))
        for t in (lift_start,lift_middle,lift_end):
            point,painting,active=_pen_state(d,t)
            self.assertFalse(painting)
            self.assertIsNone(active)
        start=_pen_state(d,lift_start)[0]
        middle=_pen_state(d,lift_middle)[0]
        end=_pen_state(d,lift_end)[0]
        self.assertLess(start[0],middle[0])
        self.assertLess(middle[0],end[0])
        for first,second in zip(events,events[1:]):
            self.assertGreaterEqual(second[2],first[3])
        last=render_traced_font(d,1.,480,240)
        self.assertFalse(last.isNull())
        self.assertTrue(d.font_ink.getpixel((109,42))[3]>0)

    def test_pen_lifts_keep_model_and_built_in_pen_unchanged(self):
        from lettering import make_text
        original=make_text('G')
        self.assertNotEqual(getattr(original,'source_kind',None),'font')
        frame=render(original,.6,640,360)
        self.assertFalse(frame.isNull())

    def test_workspace_project_header_and_history(self):
        w=Window()
        try:
            self.assertIn('Sample drawing',w.project_menu.text())
            self.assertIn('Stroke',w.brand_wordmark.text())
            self.assertIn('Scribe',w.brand_wordmark.text())
            self.assertIn('#58A7FF',w.brand_wordmark.text())
            self.assertEqual(w.brand_version.text().startswith('Prototype v'),True)
            self.assertFalse(w.undo_button.isEnabled())
            self.assertFalse(w.redo_button.isEnabled())
            w.order.setCurrentRow(0)
            names=[s.name for s in w.drawing.strokes]
            self.assertGreater(len(names),1)
            w.move(1)
            self.assertNotEqual(names,[s.name for s in w.drawing.strokes])
            self.assertTrue(w.undo_button.isEnabled())
            w.undo_stroke_order()
            self.assertEqual(names,[s.name for s in w.drawing.strokes])
            self.assertTrue(w.redo_button.isEnabled())
            w.redo_stroke_order()
            self.assertNotEqual(names,[s.name for s in w.drawing.strokes])
            w.update_project_title('Speaker artwork.png')
            self.assertIn('Speaker artwork.png',w.project_menu.text())
        finally:
            w.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
