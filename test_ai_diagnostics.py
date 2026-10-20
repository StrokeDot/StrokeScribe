"""Truthful event-scoped progress and bounded, nonblocking diagnostic logging."""
import importlib.util,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
MONITOR=importlib.util.find_spec('ai_activity')
LOGGING=importlib.util.find_spec('ai_diagnostics')
if MONITOR:from ai_activity import Activity
if LOGGING:from ai_diagnostics import DiagnosticLog,sanitize

WORKFLOW={'1':{'class_type':'UNETLoader'},'2':{'class_type':'KSampler'},
          '3':{'class_type':'SamplerCustomAdvanced'},'4':{'class_type':'SaveImage'}}

class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MONITOR,'Prompt-scoped generation activity missing')
        self.a=Activity('wanted',WORKFLOW)
    def event(self,kind,**data):
        self.a.event(dict(type=kind,data=dict(prompt_id='wanted',**data)))
    def test_loading_has_no_sampling_percentage_even_with_loader_progress(self):
        self.event('executing',node='1')
        self.event('progress',node='1',value=9,max=10)
        self.assertIsNone(self.a.percent);self.assertEqual(self.a.stage,'preparing')
    def test_only_active_prompt_sampler_progress_can_reveal_percentage(self):
        self.a.event(dict(type='progress',data=dict(prompt_id='other',node='2',value=5,max=10)))
        self.assertIsNone(self.a.percent)
        self.event('progress',node='2',value=0,max=20)
        self.assertEqual(self.a.percent,0);self.assertEqual(self.a.stage,'sampling')
        self.event('progress',node='2',value=10,max=20);self.assertEqual(self.a.percent,50)
        self.event('executing',node='4');self.assertEqual(self.a.stage,'saving');self.assertIsNone(self.a.percent)
    def test_both_qwen_and_flux_sampler_classes_and_malformed_events(self):
        for node in ('2','3'):
            self.event('progress',node=node,value=4,max=8);self.assertEqual(self.a.percent,50)
        for value in (None,'bad',float('nan')):
            self.event('progress',node='2',value=value,max=8)
        self.a.event({'type':'progress','data':None})
    def test_elapsed_no_progress_does_not_claim_engine_crash(self):
        self.a.updated-=90
        text=self.a.label(alive=True,stall_seconds=30)
        self.assertIn('running',text.lower());self.assertIn('no progress',text.lower())
        self.assertNotIn('crash',text.lower())

class EngineProgressTests(unittest.TestCase):
    def test_stdout_loader_percent_is_not_sampler_evidence(self):
        import io,types,ai_engine,os
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'STROKESCRIBE_CONFIG_DIR':folder}):
            engine=ai_engine.Engine()
            proc=types.SimpleNamespace(stdout=io.StringIO('Loading checkpoint shards: 100%|done\n'),pid=123,poll=lambda:None)
            engine.proc=proc
            engine._read_output(proc)
            self.assertIsNone(engine.percent)
            if hasattr(engine,'flush_diagnostics'):engine.flush_diagnostics(1)

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(LOGGING,'Bounded diagnostic logger missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ai-engine.log'
    def test_log_rotation_and_oversized_lines_are_bounded(self):
        log=DiagnosticLog(self.path,max_bytes=2048,capacity=128)
        for index in range(60):log.emit('event '+str(index)+'x'*400)
        self.assertTrue(log.flush(3))
        for path in self.path.parent.glob('ai-engine.log*'):
            self.assertLessEqual(path.stat().st_size,2048)
        self.assertLessEqual(len(list(self.path.parent.glob('ai-engine.log*'))),2)
        log.emit('Z'*100000);self.assertTrue(log.flush(3))
        self.assertLessEqual(self.path.stat().st_size,2048)
    def test_slow_disk_never_blocks_generation_log_producer(self):
        log=DiagnosticLog(self.path,max_bytes=2048,capacity=8)
        gate=threading.Event();entered=threading.Event()
        original=log._write
        def slow(*args):
            entered.set();gate.wait(3);return original(*args)
        with patch.object(log,'_write',side_effect=slow):
            log.emit('blocked');self.assertTrue(entered.wait(1))
            start=time.monotonic()
            for index in range(2000):log.emit(str(index))
            self.assertLess(time.monotonic()-start,.5)
            gate.set();self.assertTrue(log.flush(3))
    def test_copy_redacts_local_roots_tokens_and_credentials(self):
        text='C:/Users/Alejandro/AI/model.safetensors token=abc123 Authorization: Bearer verysecret hf_12345678901234567890'
        clean=sanitize(text,roots=['C:/Users/Alejandro'])
        for secret in ('Alejandro','abc123','verysecret','hf_12345678901234567890'):
            self.assertNotIn(secret,clean)
        self.assertIn('model.safetensors',clean)

if __name__=='__main__':unittest.main()
