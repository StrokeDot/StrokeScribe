"""Offline CI tests for optional semantic AI redraw.

All model replies are fake/test data: no Ollama download, running model, external
API, or GPU is required in CI. Actual model quality needs user visual review.
"""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from semantic_redraw import (Analysis,Part,parse_analysis,local_vision_analysis,
                             semantic_masks,ai_guided_drawing,OLLAMA_ENDPOINT)
from image_reconstruct import reconstruct
from adaptive_hand import plan_for
from test_image_source import artwork

APP=QApplication.instance() or QApplication([])

class FakeHTTPReply:
    def __init__(self,answer): self.answer=answer
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,*args): return json.dumps(self.answer).encode('utf-8')

class LocalAIRedrawTests(unittest.TestCase):
    def example(self):
        return parse_analysis({'description':'A stylized illustration of a colored face',
                'parts':[
                    {'name':'large illustrated body','box':[30,30,720,930],'order':1},
                    {'name':'blue round detail','box':[150,155,485,635],'order':2},
                    {'name':'small green accent','box':[720,730,950,985],'order':3},
                ]})
    def test_model_output_and_strict_local_api(self):
        analysis=self.example()
        self.assertEqual(analysis.parts[0].name,'large illustrated body')
        self.assertEqual(len(analysis.parts),3)
        with self.assertRaises(ValueError): parse_analysis({'parts':[]})
        for item in ('http://some-server.invalid/model','bad model',''):
            with self.assertRaises(ValueError):
                local_vision_analysis(artwork(),model=item)
        response={'message':{'content':json.dumps({
            'description':'A small illustrated house',
            'parts':[{'name':'house','box':[10,10,900,930],'order':1}]})}}
        requests=[]
        def receive(request,timeout=None):
            requests.append((request,timeout))
            return FakeHTTPReply(response)
        with patch('semantic_redraw.urlopen',side_effect=receive):
            output=local_vision_analysis(artwork(),model='qwen3-vl:4b')
        self.assertEqual(output.parts[0].name,'house')
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0][0].full_url,OLLAMA_ENDPOINT)
        sent=json.loads(requests[0][0].data)
        self.assertTrue(sent['messages'][0]['images'][0])
        self.assertEqual(sent['model'],'qwen3-vl:4b')
        self.assertEqual(sent['stream'],False)
        self.assertIn('format',sent)

    def test_semantic_parts_are_named_and_pixels_remain_original(self):
        image=artwork()
        analysis=self.example()
        regions,masks,valid=semantic_masks(image,analysis,'low')
        self.assertEqual(regions.size[0]>0,True)
        self.assertGreaterEqual(len(valid),1)
        drawing,qi=ai_guided_drawing(image,analysis,'low')
        self.assertEqual(drawing.source_mode,'ai_redraw')
        self.assertTrue(drawing.image_semantic_order)
        self.assertTrue(any(s.name.startswith('AI ') for s in drawing.strokes))
        self.assertTrue(any(s.name.startswith('Fine detail') for s in drawing.strokes)
                        or len(drawing.strokes)>0)
        self.assertEqual(qi.width(),image.width)
        self.assertEqual(qi.height(),image.height)
        self.assertTrue(all(rid==0 for rid,alpha in zip(
            regions.labels,image.resize(regions.size).getchannel('A').tobytes())
            if alpha==0))

    def test_raster_integration_and_brush_route(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'colored-cowboy-demo.png'
            artwork().save(source)
            analysis=self.example()
            result=reconstruct(source,'ai_redraw','low',ai_analysis=analysis)
            self.assertEqual(result.mode,'ai_redraw')
            self.assertTrue(result.drawing.image_semantic_order)
            plan=plan_for(result.drawing,result.image,.12,.55)
            self.assertTrue(plan.segments)
            self.assertTrue(any(not s.painting for s in plan.segments))
            self.assertTrue(any(s.painting for s in plan.segments))
            self.assertEqual(plan.mask(.98).tobytes(),plan.mask(1).tobytes())

    def test_working_ui_selection_and_clear_missing_ai_error(self):
        from app import Window,ImageBuilder
        w=Window()
        w.source_type.setCurrentIndex(1)
        w.image_mode.setCurrentIndex(2)
        APP.processEvents()
        self.assertEqual(w.rebuild_button.text(),'Analyze with local AI')
        self.assertFalse(w.image_source_form.isRowVisible(w.ai_model)==False)
        self.assertIn('qwen3-vl:',w.ai_model.currentText())
        w.image_mode.setCurrentIndex(0)
        self.assertFalse(w.image_source_form.isRowVisible(w.ai_model))
        w.close()
        with tempfile.TemporaryDirectory() as temp:
            filename=Path(temp)/'art.png'
            artwork().save(filename)
            worker=ImageBuilder(str(filename),'ai_redraw','low',.14,.55)
            emitted=[]; errors=[]
            worker.ready.connect(emitted.append)
            worker.failed.connect(errors.append)
            with patch('semantic_redraw.local_vision_analysis',return_value=self.example()):
                worker.run()
            self.assertFalse(errors,str(errors))
            self.assertEqual(emitted[0].mode,'ai_redraw')
            worker2=ImageBuilder(str(filename),'ai_redraw','low',.14,.55)
            worker2.failed.connect(errors.append)
            with patch('semantic_redraw.local_vision_analysis',side_effect=RuntimeError(
                    'Local AI is not running. Install Ollama.')):
                worker2.run()
            self.assertTrue(any('Local AI' in v for v in errors))


if __name__=='__main__':
    unittest.main(verbosity=2)
