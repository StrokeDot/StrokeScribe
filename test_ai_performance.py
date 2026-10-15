"""Offline regression tests for faster AI Redraw iteration and honest progress.

Mocked vision responses isolate analysis caching and contour/detail rebuilds;
a real Ollama model is never claimed or required in GitHub CI.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from app import ImageBuilder, Window
from semantic_redraw import parse_analysis
from test_image_source import artwork

APP=QApplication.instance() or QApplication([])


def scene():
    return parse_analysis({
        'description':'Orange illustration with a blue circle',
        'parts':[{'name':'orange shape','box':[20,20,720,930],'order':1},
                 {'name':'blue inset','box':[180,170,540,650],'order':2}],
    })


class AIWorkloadTests(unittest.TestCase):
    def test_one_local_vision_call_reused_for_different_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.png'
            artwork().save(path)
            analyses=[]
            errors=[]
            results=[]
            with patch('semantic_redraw.local_vision_analysis',return_value=scene()) as model:
                first=ImageBuilder(str(path),'ai_redraw','medium',.14,.55)
                first.analysis_ready.connect(analyses.append)
                first.ready.connect(results.append)
                first.failed.connect(errors.append)
                first.run()
                self.assertFalse(errors,str(errors))
                self.assertEqual(model.call_count,1)
                self.assertEqual(len(analyses),1)
                self.assertEqual(first.analysis,analyses[0])
                self.assertGreaterEqual(first.timings['vision'],0)
                self.assertIn('contours',first.timings)
                self.assertIn('brush',first.timings)
                second=ImageBuilder(str(path),'ai_redraw','high',.14,.55,
                                    cached_analysis=analyses[0])
                second.ready.connect(results.append)
                second.failed.connect(errors.append)
                second.run()
                self.assertFalse(errors,str(errors))
                self.assertEqual(model.call_count,1,
                                 'High detail must not repeat Qwen inference')
                self.assertTrue(second.cache_hit)
                self.assertEqual(second.timings['vision'],0)
                self.assertTrue(second.success)
                self.assertEqual(results[-1].mode,'ai_redraw')
                self.assertEqual(results[-1].detail,'high')
                self.assertIsNot(results[0].regions,results[1].regions)

    def test_session_cache_file_revision_model_and_eviction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'artwork.png'
            artwork().save(path)
            w=Window()
            try:
                original=w.analysis_cache_key(str(path),'qwen3-vl:4b')
                self.assertEqual(original,w.analysis_cache_key(str(path),'qwen3-vl:4b'))
                self.assertNotEqual(original,w.analysis_cache_key(str(path),'qwen3-vl:2b'))
                w.cache_ai_analysis(original,scene())
                self.assertIsNotNone(w.ai_analysis_cache.get(original))
                w.image_detail.setCurrentIndex(2)
                self.assertEqual(original,w.analysis_cache_key(str(path),'qwen3-vl:4b'))
                stat=path.stat()
                os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns+1_000_000_000))
                self.assertNotEqual(original,w.analysis_cache_key(str(path),'qwen3-vl:4b'))
                for i in range(8):
                    w.cache_ai_analysis(('model',i),scene())
                self.assertEqual(len(w.ai_analysis_cache),4)
                self.assertNotIn(original,w.ai_analysis_cache)
            finally:
                w.close()

    def test_visible_stages_and_indeterminate_vision_progress(self):
        w=Window()
        try:
            w.analysis_started=time.perf_counter()-2
            w.image_stage('Asking Ollama to identify image objects',0,True)
            self.assertEqual((w.progress.minimum(),w.progress.maximum()),(0,0))
            self.assertIn('Asking Ollama',w.status.text())
            w.image_stage('Building image contours and color regions',65,False)
            self.assertEqual(w.progress.maximum(),100)
            self.assertEqual(w.progress.value(),65)
            self.assertIn('contours',w.status.text())
            w.image_stage('Preparing animation and brush routes',85,False)
            self.assertEqual(w.progress.value(),85)
            self.assertIn('brush',w.status.text())
        finally:
            w.close()

    def test_model_thumbnail_is_bounded_and_not_original_size(self):
        import json
        import io
        import base64
        from unittest.mock import MagicMock
        from semantic_redraw import local_vision_analysis
        big=Image.new('RGBA',(1400,1000),(255,255,255,255))
        fake={'done':True,'done_reason':'stop',
              'message':{'content':json.dumps({
                  'description':'shape','parts':[{'name':'rectangle',
                       'box':[50,50,950,950],'order':1}]})}}
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,*a):return json.dumps(fake).encode()
        captured=[]
        def receive(request,timeout=None):
            captured.append(json.loads(request.data))
            return Reply()
        with patch('semantic_redraw.urlopen',side_effect=receive):
            result=local_vision_analysis(big)
        pixels=base64.b64decode(captured[0]['messages'][0]['images'][0])
        with Image.open(io.BytesIO(pixels)) as input_image:
            self.assertLessEqual(max(input_image.size),640)
        self.assertEqual(result.parts[0].name,'rectangle')
        self.assertEqual(big.size,(1400,1000))


if __name__=='__main__':
    unittest.main(verbosity=2)
