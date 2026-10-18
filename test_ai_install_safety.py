"""Phase 4: extraction safety and optional cryptographic download integrity."""
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import ai_engine


def packed(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        for name, payload in files.items():
            z.writestr('ComfyUI-test/' + name, payload)
    return b.getvalue()


class EngineInstallSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = self.root/'ComfyUI'
        self.engine.mkdir()
        (self.engine/'main.py').write_text('previous working engine')
        self.content = packed({'main.py': 'new engine', 'extras/nodes.py': 'node'})

    def test_cancelled_extraction_preserves_previous_engine(self):
        calls = [0]
        def cancel():
            calls[0] += 1
            return calls[0] > 2
        with self.assertRaises(ai_engine.Cancelled):
            ai_engine._extract_zip(self.content, self.engine, cancelled=cancel)
        self.assertEqual((self.engine/'main.py').read_text(), 'previous working engine')

    def test_failed_atomic_folder_swap_restores_previous_engine(self):
        real = ai_engine.os.replace
        def fail_stage(src, dst):
            if Path(dst) == self.engine and Path(src) != self.engine.with_name('ComfyUI.previous'):
                raise OSError('cannot rename staged engine')
            return real(src, dst)
        with patch.object(ai_engine.os, 'replace', side_effect=fail_stage):
            with self.assertRaises(OSError):
                ai_engine._extract_zip(self.content, self.engine)
        self.assertEqual((self.engine/'main.py').read_text(), 'previous working engine')

    def test_interrupted_folder_swap_is_recoverable_next_launch(self):
        real = ai_engine.os.replace
        def power_cut(src, dst):
            if Path(dst) == self.engine and Path(src) != self.engine.with_name('ComfyUI.previous'):
                raise KeyboardInterrupt('power cut between renames')
            return real(src, dst)
        with patch.object(ai_engine.os, 'replace', side_effect=power_cut):
            with self.assertRaises(KeyboardInterrupt):
                ai_engine._extract_zip(self.content, self.engine)
        self.assertTrue(ai_engine.recover_engine_folder(self.engine))
        self.assertEqual((self.engine/'main.py').read_text(), 'previous working engine')

    def test_successful_extraction_preserves_old_until_new_is_ready(self):
        ai_engine._extract_zip(self.content, self.engine)
        self.assertEqual((self.engine/'main.py').read_text(), 'new engine')
        self.assertEqual((self.engine/'extras'/'nodes.py').read_text(), 'node')
        self.assertFalse(self.engine.with_name('ComfyUI.previous').exists())

    def test_invalid_archive_preserves_engine(self):
        with self.assertRaises(Exception):
            ai_engine._extract_zip(b'not a zip', self.engine)
        self.assertEqual((self.engine/'main.py').read_text(), 'previous working engine')


class ModelIntegrityTests(unittest.TestCase):
    def test_incorrect_sha256_never_promotes_model_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'model.gguf'
            payload = b'model bytes'
            wanted = hashlib.sha256(b'correct model').hexdigest()
            def fake_single(url, part, size, progress, cancelled):
                part.write_bytes(payload)
            with patch.object(ai_engine, '_download_single', side_effect=fake_single):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256|checksum'):
                    ai_engine.download('file://fake', target, len(payload), sha256=wanted, connections=1)
            self.assertFalse(target.exists())

    def test_matching_sha256_accepts_model_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'model.gguf'
            payload = b'correct model'
            wanted = hashlib.sha256(payload).hexdigest()
            with patch.object(ai_engine, '_download_single', side_effect=lambda url, part, size, progress, cancelled: part.write_bytes(payload)):
                result = ai_engine.download('file://fake', target, len(payload), sha256=wanted, connections=1)
            self.assertEqual(result.read_bytes(), payload)

    def test_cached_correct_size_wrong_hash_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'model.gguf'
            target.write_bytes(b'BAD!')
            good = b'GOOD'
            wanted = hashlib.sha256(good).hexdigest()
            with patch.object(ai_engine, '_download_single', side_effect=lambda url, part, size, progress, cancelled: part.write_bytes(good)) as dl:
                ai_engine.download('file://fake', target, 4, sha256=wanted, connections=1)
                dl.assert_called_once()
            self.assertEqual(target.read_bytes(), good)


if __name__ == '__main__':
    unittest.main(verbosity=2)
