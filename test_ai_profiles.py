"""Tests for bounded AI processing profiles and local reconstruction geometry.

All Ollama requests are mocked. Profile speed measurements require manual
GPU inference testing; the tests only benchmark actual local OpenCV work.
"""
import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from app import ImageBuilder, Window
from image_reconstruct import reconstruct
from semantic_redraw import AI_PROFILES, local_vision_analysis, parse_analysis, semantic_masks
from test_image_source import artwork

APP=QApplication.instance() or QApplication([])


def sample_analysis():
    return parse_analysis({
        'description':'stylized colorful illustration',
        'parts':[
            {'name':'main orange shape','box':[40,40,740,940],'order':1},
            {'name':'blue circle','box':[150,140,520,680],'order':2},
            {'name':'accent','box':[690,670,960,990],'order':3},
        ],
    })


class Reply:
    def __init__(self,answer):self.answer=answer
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):return json.dumps(self.answer).encode()


class ProfileTests(unittest.TestCase):
    def test_balanced_default_preserves_vision_resolution_and_density(self):
        self.assertEqual(AI_PROFILES['balanced']['max_side'],640)
        self.assertEqual(AI_PROFILES['balanced']['max_parts'],8)
        self.assertEqual(AI_PROFILES['balanced']['grabcut_iterations'],3)
        self.assertEqual(AI_PROFILES['balanced']['segmentation'],'roi')
        self.assertEqual(AI_PROFILES['balanced']['keep_alive'],'5m')
        window=Window()
        try:
            self.assertEqual(window.ai_profile.currentText(),'Balanced')
            self.assertEqual(window.image_detail.currentText(),'Medium')
            key=window.analysis_cache_key(__file__,'qwen3-vl:4b')
            self.assertEqual(key,window.analysis_cache_key(__file__,'qwen3-vl:4b','balanced'))
            self.assertNotEqual(key,window.analysis_cache_key(__file__,'qwen3-vl:4b','fast'))
            self.assertNotEqual(key,window.analysis_cache_key(__file__,'qwen3-vl:4b','quality'))
        finally:
            window.close()

    def test_model_input_and_keep_alive_settings_are_profile_specific(self):
        reply={'done':True,'done_reason':'stop',
            'message':{'content':json.dumps({
                'description':'illustration',
                'parts':[{'name':'large shape','box':[10,10,800,900],'order':1}]})}}
        image=Image.new('RGBA',(1600,1000),(205,120,55,255))
        for name,size,parts,keep in [
            ('fast',448,4,'2m'),
            ('balanced',640,8,'5m'),
            ('quality',896,12,'10m'),
        ]:
            received=[]
            def call(req,timeout=None):
                received.append(json.loads(req.data))
                return Reply(reply)
            with patch('semantic_redraw.urlopen',side_effect=call):
                parsed=local_vision_analysis(image,profile=name)
            self.assertEqual(len(parsed.parts),1)
            request=received[0]
            self.assertEqual(request['keep_alive'],keep)
            self.assertIn(f'1 to {parts} visible objects or parts',
                          request['messages'][0]['content'])
            self.assertEqual(request['think'],False)
            self.assertEqual(request['model'],'qwen3-vl:4b')
            raw=base64.b64decode(request['messages'][0]['images'][0])
            with Image.open(io.BytesIO(raw)) as sent:
                self.assertLessEqual(max(sent.size),size)
                self.assertEqual(max(sent.size),size)
        with self.assertRaises(ValueError):
            local_vision_analysis(image,profile='untrusted')

    def test_both_local_segmentation_methods_preserve_original_pixels(self):
        image=artwork()
        parts=sample_analysis()
        roi,masks,ids=semantic_masks(image,parts,'medium','balanced')
        full,_,_=semantic_masks(image,parts,'medium','quality')
        self.assertEqual(roi.size,full.size)
        self.assertGreater(roi.size[0],0)
        self.assertGreater(len(ids),0)
        self.assertGreater(np.count_nonzero(np.array(roi.labels)),0)
        self.assertGreater(np.count_nonzero(np.array(full.labels)),0)
        with tempfile.TemporaryDirectory() as tmp:
            filename=Path(tmp)/'color.png'
            image.save(filename)
            result=reconstruct(filename,'ai_redraw','medium',
                               ai_analysis=parts,ai_profile='balanced')
            self.assertEqual(result.drawing.source_mode,'ai_redraw')
            self.assertEqual(result.image.width(),image.getbbox()[2]-image.getbbox()[0])
            self.assertTrue(result.drawing.image_semantic_order)

    def test_switching_profile_keeps_existing_modes_and_skips_ai_when_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename=Path(tmp)/'image.png'
            artwork().save(filename)
            results=[]; errors=[]
            with patch('semantic_redraw.local_vision_analysis',return_value=sample_analysis()) as run_model:
                worker=ImageBuilder(str(filename),'ai_redraw','medium',.14,.55,
                                    ai_profile='balanced')
                worker.ready.connect(results.append)
                worker.failed.connect(errors.append)
                worker.run()
                self.assertFalse(errors,str(errors))
                self.assertEqual(run_model.call_count,1)
                self.assertEqual(run_model.call_args.kwargs.get('profile'),'balanced')
                same=ImageBuilder(str(filename),'ai_redraw','high',.14,.55,
                                  cached_analysis=worker.analysis,ai_profile='balanced')
                same.ready.connect(results.append)
                same.failed.connect(errors.append)
                same.run()
                self.assertFalse(errors,str(errors))
                self.assertEqual(run_model.call_count,1)
                self.assertTrue(same.cache_hit)
            for mode in ('auto_trace','stroke_reconstruction'):
                reconstruction=reconstruct(filename,mode,'medium',
                                            ai_profile='balanced')
                self.assertEqual(reconstruction.mode,mode)
            self.assertGreater(len(results),1)


if __name__=='__main__':
    unittest.main(verbosity=2)
