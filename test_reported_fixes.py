"""Regression checks for reported broken lettering, invalid Ollama JSON and Studio toolbar."""
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
from semantic_redraw import extract_structured_parts,local_vision_analysis
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

    def test_qwen_json_fenced_preamble_and_retry(self):
        raw={'description':'Wooden audio speakers',
             'parts':[{'name':'left speaker','box':[10,10,400,900],'order':1}]}
        self.assertEqual(extract_structured_parts('\\x60\\x60\\x60json\\n'+
            json.dumps(raw)+'\\n\\x60\\x60\\x60') if False else
            extract_structured_parts('```json\n'+json.dumps(raw)+'\n```'),raw)
        self.assertEqual(extract_structured_parts(
            'The detected parts are:\n'+json.dumps(raw)),raw)
        requests=[]
        replies=iter(['', '```json\n'+json.dumps(raw)+'\n```'])
        def local_call(req,timeout=None):
            requests.append(json.loads(req.data))
            return FakeResponse(next(replies))
        with patch('semantic_redraw.urlopen',side_effect=local_call):
            result=local_vision_analysis(artwork(),model='qwen3-vl:4b')
        self.assertEqual(result.parts[0].name,'left speaker')
        self.assertEqual(len(requests),2)
        self.assertFalse(requests[0]['think'])
        self.assertEqual(requests[1]['format'],'json')
        with patch('semantic_redraw.urlopen',return_value=FakeResponse('')):
            with self.assertRaisesRegex(ValueError,'second attempt'):
                local_vision_analysis(artwork())

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
