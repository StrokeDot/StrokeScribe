"""Protocol regression tests with fake Ollama replies, NOT real-model validation."""
import io,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError,URLError
from PIL import Image
from semantic_redraw import (local_vision_analysis,extract_structured_parts,
    INITIAL_TOKENS,RETRY_TOKENS,CONTEXT_TOKENS,OLLAMA_ENDPOINT,ai_guided_drawing,parse_analysis)
from image_reconstruct import reconstruct
from test_ai_redraw import FakeHTTPReply
from test_image_source import artwork

VALID={'description':'Colored illustration','parts':[
    {'name':'body','box':[20,20,730,950],'order':1},
    {'name':'round detail','box':[150,150,490,650],'order':2}]}

def reply(content=None,**extra):
    return FakeHTTPReply(dict(message={'content':json.dumps(VALID) if content is None else content},
                              done=True,done_reason='stop',**extra))

class OllamaReliabilityTests(unittest.TestCase):
    def test_empty_length_reasoning_gets_one_larger_retry(self):
        seen=[]
        answers=iter([FakeHTTPReply({'message':{'content':'','thinking':'private reasoning'},
            'done_reason':'length','eval_count':3072}),reply()])
        def request(req,timeout):
            seen.append(json.loads(req.data));return next(answers)
        with patch('semantic_redraw.urlopen',side_effect=request):
            result=local_vision_analysis(artwork())
        self.assertEqual(result.parts[0].name,'body')
        self.assertEqual([r['options']['num_predict'] for r in seen],[INITIAL_TOKENS,RETRY_TOKENS])
        self.assertTrue(all(r['options']['num_ctx']==CONTEXT_TOKENS and r['think'] is False for r in seen))
        self.assertEqual(seen[1]['format'],'json')
        self.assertIn('1 to 4',seen[1]['messages'][0]['content'])

    def test_persistent_length_is_diagnostic_and_bounded(self):
        response=FakeHTTPReply({'message':{'content':'','thinking':'secret image analysis'},
                               'done_reason':'length','eval_count':6144})
        with patch('semantic_redraw.urlopen',return_value=response) as call:
            with self.assertRaisesRegex(ValueError,'thinking_chars=21') as error:
                local_vision_analysis(artwork())
        self.assertEqual(call.call_count,2)
        self.assertNotIn('secret image analysis',str(error.exception))
        self.assertIn('No Auto Trace fallback',str(error.exception))

    def test_truncation_retried_without_inventing_missing_json(self):
        broken='{"description":"x","parts":[{"name":"body","box":[1,2'
        with patch('semantic_redraw.urlopen',side_effect=[reply(broken),reply()]) as call:
            self.assertTrue(local_vision_analysis(artwork()).parts)
        self.assertEqual(call.call_count,2)
        payload=json.loads(call.call_args.args[0].data)
        self.assertEqual(payload['options']['num_predict'],INITIAL_TOKENS)
        with self.assertRaises(ValueError):extract_structured_parts(broken)

    def test_reasoning_is_not_accepted_as_answer(self):
        hidden='<think>'+json.dumps(VALID)+'</think>'
        with self.assertRaises(ValueError):extract_structured_parts(hidden)
        self.assertEqual(extract_structured_parts(hidden+'\nAnswer:\n'+
            '```json\n'+json.dumps(VALID)+'\n```'),VALID)
        with self.assertRaises(ValueError):extract_structured_parts('<think>'+json.dumps(VALID))

    def test_schema_rejection_falls_back_but_bad_parameters_do_not(self):
        error=HTTPError(OLLAMA_ENDPOINT,400,'Bad request',None,io.BytesIO(b'unsupported JSON schema format'))
        with patch('semantic_redraw.urlopen',side_effect=[error,reply()]) as call:
            self.assertTrue(local_vision_analysis(artwork()).parts)
        self.assertEqual(json.loads(call.call_args.args[0].data)['format'],'json')
        error=HTTPError(OLLAMA_ENDPOINT,400,'Bad request',None,io.BytesIO(b'invalid image'))
        with patch('semantic_redraw.urlopen',side_effect=error) as call:
            with self.assertRaisesRegex(RuntimeError,'HTTP 400'):local_vision_analysis(artwork())
        self.assertEqual(call.call_count,1)

    def test_timeout_and_unavailable_are_distinct_and_not_retried(self):
        for error,match in [(socket.timeout('slow'),'timed out'),
                            (URLError(ConnectionRefusedError()),'Cannot reach')]:
            with patch('semantic_redraw.urlopen',side_effect=error) as call:
                with self.assertRaisesRegex(RuntimeError,match):local_vision_analysis(artwork())
            self.assertEqual(call.call_count,1)

    def test_truncated_envelope_and_length_even_with_valid_content(self):
        with patch('semantic_redraw.urlopen',side_effect=[io.BytesIO(b'{"message":'),reply()]):
            self.assertTrue(local_vision_analysis(artwork()).parts)
        length=FakeHTTPReply({'message':{'content':json.dumps(VALID)},'done_reason':'length'})
        with patch('semantic_redraw.urlopen',side_effect=[length,reply()]) as call:
            self.assertTrue(local_vision_analysis(artwork()).parts)
        self.assertEqual(call.call_count,2)

    def test_successful_reconstruction_uses_model_parts_and_original_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';artwork().save(path)
            with patch('semantic_redraw.urlopen',return_value=reply()) as call:
                result=reconstruct(path,'ai_redraw','low')
            self.assertEqual(result.mode,'ai_redraw')
            self.assertTrue(any(s.name.startswith('AI ') for s in result.drawing.strokes))
            self.assertEqual(call.call_args.args[0].full_url,OLLAMA_ENDPOINT)
            self.assertEqual(result.image.width(),artwork().getbbox()[2]-artwork().getbbox()[0])

    def test_no_semantic_contours_must_not_report_auto_trace_as_ai(self):
        import numpy as np
        from image_regions import RegionMap
        fake=(RegionMap((4,4),(0,)*16,0,False),[np.zeros((4,4),np.uint8)],[])
        with patch('semantic_redraw.semantic_masks',return_value=fake):
            with self.assertRaisesRegex(ValueError,'No Auto Trace fallback'):
                ai_guided_drawing(artwork(),parse_analysis(VALID))
