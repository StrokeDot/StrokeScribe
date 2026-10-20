"""Resource checks inform users; they never manage other applications."""
import importlib.util,math,unittest
from unittest.mock import patch
MODULE=importlib.util.find_spec('ai_resources')
if MODULE:import ai_resources as resources

class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MODULE,'Resource awareness module must be implemented')
    def test_high_and_low_memory_and_unknown_gpu(self):
        self.assertEqual(resources.warning_for(dict(ram_gb=32.,gpu_gb=8.),{}),'')
        message=resources.warning_for(dict(ram_gb=4.,gpu_gb=.8),{})
        self.assertIn('4.0 GB',message);self.assertIn('0.8 GB',message)
        self.assertIn('close',message.lower())
        self.assertEqual(resources.warning_for(dict(ram_gb=32.,gpu_gb=None),{}),'')
        self.assertNotIn('0.0 GB',resources.warning_for(dict(ram_gb=4.,gpu_gb=None),{}))
    def test_thresholds_configurable_finite_and_disabled(self):
        self.assertEqual(resources.warning_for(dict(ram_gb=4.,gpu_gb=1.),dict(ram_gb=2,vram_gb=.5)),'')
        self.assertEqual(resources.warning_for(dict(ram_gb=0.,gpu_gb=0.),dict(enabled=False)),'')
        limits=resources.limits(dict(ram_gb=float('nan'),vram_gb=-3,stall_seconds='bad'))
        self.assertTrue(math.isfinite(limits['ram_gb']));self.assertGreaterEqual(limits['vram_gb'],0)
    def test_missing_nvidia_and_timeout_unknown(self):
        import subprocess
        for error in (FileNotFoundError(),subprocess.TimeoutExpired('nvidia-smi',1)):
            with patch('ai_resources.subprocess.run',side_effect=error):
                self.assertIsNone(resources.gpu_available_gb())
    def test_gpu_probe_bounded_and_actual_memory(self):
        import subprocess
        with patch('ai_resources.subprocess.run',return_value=subprocess.CompletedProcess([],0,'1024, 8192\n','')) as run:
            self.assertAlmostEqual(resources.gpu_available_gb(),1.)
            self.assertLessEqual(run.call_args.kwargs['timeout'],2.)
        with patch('ai_resources.subprocess.run',return_value=subprocess.CompletedProcess([],0,'unavailable\n','')):
            self.assertIsNone(resources.gpu_available_gb())

from test_source_ai_lifecycle import AILifecycleTests,APP
from create_image_dialog import AIWorker
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import time

def pumped(predicate,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        APP.processEvents()
        if predicate():return True
        QTest.qWait(10)
    return predicate()

class ResourceDialogTests(unittest.TestCase):
    setUp=AILifecycleTests.setUp
    tearDown=AILifecycleTests.tearDown
    def worker(self):
        self.assertTrue(hasattr(self.dialog,'resources'),'Nonblocking resource panel missing')
        return AIWorker('generate',engine=self.engine,workflow={},image_path=None,
            resource_check=dict(warn=not self.dialog._resource_warning_shown,limits={}))
    def test_low_memory_warns_once_and_user_can_proceed_with_warm_engine(self):
        worker=self.worker();warnings=[]
        worker.resource_warning.connect(warnings.append)
        with patch('ai_resources.probe',return_value=dict(ram_gb=3.,gpu_gb=.5)):
            self.dialog._start(worker,lambda path:None)
            self.assertTrue(pumped(lambda:bool(warnings)))
            self.assertIsNone(self.engine.proc)
            self.assertFalse(self.dialog.resources.warning.isHidden())
            self.dialog.resources.proceed.click()
            self.assertTrue(pumped(lambda:not worker.isRunning()))
            self.assertTrue(worker.wait(1000));APP.processEvents()
            pid=self.engine.proc.pid
            next_worker=self.worker();next_worker.resource_warning.connect(warnings.append)
            self.dialog._start(next_worker,lambda path:None)
            self.assertTrue(pumped(lambda:not next_worker.isRunning()))
            self.assertTrue(next_worker.wait(1000));APP.processEvents()
            self.assertEqual(len(warnings),1);self.assertEqual(self.engine.proc.pid,pid)
    def test_cancel_while_warning_does_not_launch_engine(self):
        worker=self.worker();warnings=[]
        worker.resource_warning.connect(warnings.append)
        with patch('ai_resources.probe',return_value=dict(ram_gb=1.,gpu_gb=None)):
            self.dialog._start(worker,lambda path:None)
            self.assertTrue(pumped(lambda:bool(warnings)))
            self.dialog.resources.cancel.click()
            self.assertTrue(pumped(lambda:not worker.isRunning()))
            self.assertTrue(worker.wait(1000));APP.processEvents()
            self.assertIsNone(self.engine.proc)
    def test_limits_persist_without_modifying_model_parameters(self):
        self.worker()
        import ai_engine
        self.dialog.resource_limits_changed(dict(enabled=True,ram_gb=6,vram_gb=1,stall_seconds=45))
        self.assertEqual(ai_engine.load_settings()['resource_warning']['ram_gb'],6)

if __name__=='__main__':unittest.main()

