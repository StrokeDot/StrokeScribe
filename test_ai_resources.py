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

if __name__=='__main__':unittest.main()
