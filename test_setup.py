"""Setup window and system preflight tests (fake Ollama/FFmpeg answers)."""
import faulthandler
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

import preflight

APP = QApplication.instance() or QApplication([])
faulthandler.enable()  # print a Python traceback if Qt crashes


class FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): return False


def fake_ollama(models):
    def urlopen(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        if url.endswith('/api/version'):
            return FakeResponse(b'{"version":"0.12.6"}')
        if url.endswith('/api/tags'):
            return FakeResponse(json.dumps({'models': [
                {'name': name, 'size': int(gb * 1e9)} for name, gb in models.items()]}).encode())
        raise AssertionError(url)
    return urlopen


class IsolatedSettings(unittest.TestCase):
    """Keep the saved setup choice in a temporary folder for each test."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'STROKESCRIBE_CONFIG_DIR': self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()


class PreflightTests(IsolatedSettings):
    def item(self, items, key):
        return next(i for i in items if i.key == key)

    def test_tiers_use_instruct_models_with_sizes(self):
        self.assertEqual(preflight.TIER_ORDER, ('fast', 'balanced', 'quality', 'max'))
        for tier in preflight.TIER_ORDER:
            settings = preflight.TIERS[tier]
            self.assertTrue(settings['model'].endswith('-instruct'), tier)
            self.assertGreater(settings['model_gb'], 0)
            self.assertIn(settings['profile'], ('fast', 'balanced', 'quality'))
        self.assertEqual(preflight.TIERS['max']['model'], 'qwen3-vl:8b-instruct')

    def test_missing_ollama_offers_install_then_model(self):
        with patch('preflight.find_ollama', return_value=None), \
             patch('preflight.ollama_version', return_value=None):
            items = preflight.run_checks('max')
        ollama, model = self.item(items, 'ollama'), self.item(items, 'model')
        self.assertEqual((ollama.status, ollama.action), ('missing', 'winget_ollama'))
        self.assertEqual((model.status, model.action), ('missing', 'pull_model'))
        self.assertEqual(model.name, 'qwen3-vl:8b-instruct')
        self.assertAlmostEqual(model.size_gb, 6.1)
        self.assertEqual(model.location, str(preflight.models_dir()))

    def test_installed_model_and_running_ollama_are_ok_with_locations(self):
        with patch('preflight.urlopen', fake_ollama({'qwen3-vl:4b-instruct': 3.3})), \
             patch('preflight.find_ollama', return_value=r'C:\Ollama\ollama.exe'):
            items = preflight.run_checks('balanced')
        self.assertEqual(self.item(items, 'ollama').status, 'ok')
        self.assertIn('0.12.6', self.item(items, 'ollama').name)
        self.assertEqual(self.item(items, 'ollama').location, r'C:\Ollama\ollama.exe')
        model = self.item(items, 'model')
        self.assertEqual((model.status, model.action), ('ok', ''))
        # Libraries report where they are installed.
        pyside = self.item(items, 'pkg:PySide6')
        self.assertEqual(pyside.status, 'ok')
        self.assertTrue(Path(pyside.location).is_dir())

    def test_ffmpeg_missing_and_encoder_check(self):
        with patch('preflight.find_ffmpeg', return_value=None):
            item = self.item(preflight.run_checks('fast'), 'ffmpeg')
        self.assertEqual((item.status, item.action), ('missing', 'winget_ffmpeg'))
        with patch('preflight.find_ffmpeg', return_value='/x/ffmpeg'), \
             patch('preflight.ffmpeg_encoders', return_value={'libx264'}):
            item = self.item(preflight.run_checks('fast'), 'ffmpeg')
        self.assertEqual(item.status, 'warning')
        self.assertIn('WebM', item.detail)
        self.assertEqual(item.location, '/x/ffmpeg')

    def test_advice_for_small_computers(self):
        info = preflight.SystemInfo('Windows 11', 7.8, 4., 50., 'C:\\', [])
        self.assertEqual(preflight.advice(info, 'fast'), [])  # "8 GB" PCs are fine
        notes = preflight.advice(info, 'max')
        self.assertTrue(any('16 GB' in n for n in notes))
        self.assertTrue(any('GPU' in n for n in notes))
        tight = preflight.SystemInfo('Windows 11', 32., 20., 4., 'C:\\', [('RTX', 8.)])
        self.assertTrue(any('free' in n for n in preflight.advice(tight, 'max')))

    def test_model_download_reports_progress(self):
        lines = b'\n'.join(json.dumps(x).encode() for x in (
            {'status': 'pulling manifest'},
            {'status': 'downloading', 'completed': 50, 'total': 100},
            {'status': 'success'}))
        seen = []
        with patch('preflight.urlopen', return_value=FakeResponse(lines)) as call:
            self.assertTrue(preflight.pull_model('qwen3-vl:4b-instruct',
                                                 lambda *a: seen.append(a)))
        body = json.loads(call.call_args.args[0].data)
        self.assertEqual(body['model'], 'qwen3-vl:4b-instruct')
        self.assertIn(('downloading', 50, 100), seen)
        failing = FakeResponse(b'{"error":"model not found"}')
        with patch('preflight.urlopen', return_value=failing):
            with self.assertRaisesRegex(RuntimeError, 'model not found'):
                preflight.pull_model('nope')

    def test_settings_saved_and_loaded(self):
        self.assertEqual(preflight.load_setup(), {'tier': None, 'show_at_startup': True})
        preflight.save_setup('max', False)
        self.assertEqual(preflight.load_setup(), {'tier': 'max', 'show_at_startup': False})
        self.assertTrue(str(preflight.config_path()).startswith(self.tmp.name))


class SetupWindowTests(IsolatedSettings):
    def test_window_lists_items_and_applies_level(self):
        from setup_wizard import SetupDialog
        dialog = SetupDialog(auto_check=False)
        self.assertEqual(dialog.tier, 'balanced')
        dialog.choose('max', run_check=False)
        self.assertIn('qwen3-vl:8b-instruct', dialog.tier_summary.text())
        info = preflight.SystemInfo('Windows 11', 16., 9., 120., 'C:\\Users\\me', [])
        items = [preflight.CheckItem('ffmpeg', 'FFmpeg', 'Video export', 'ok', '', r'C:\ffmpeg.exe'),
                 preflight.CheckItem('model', 'qwen3-vl:8b-instruct', 'AI', 'missing',
                                     '6.1 GB download', r'C:\Users\me\.ollama\models',
                                     required=False, action='pull_model', size_gb=6.1)]
        dialog.show_results(info, items)
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertIn('Location: C:\\ffmpeg.exe', dialog.table.item(0, 2).text())
        self.assertIn('Missing', dialog.table.item(1, 1).text())
        self.assertIn('6.1 GB', dialog.download_button.text())
        self.assertTrue(dialog.download_button.isEnabled())
        # Saying "No" to the download question installs nothing.
        from PySide6.QtWidgets import QMessageBox
        with patch('setup_wizard.QMessageBox.question',
                   return_value=QMessageBox.StandardButton.No):
            dialog.download_missing()
        self.assertIsNone(dialog.installer)
        applied = []
        dialog.tier_applied.connect(applied.append)
        dialog.show_at_startup.setChecked(False)
        dialog.finish()
        self.assertEqual(applied, ['max'])
        self.assertEqual(preflight.load_setup(), {'tier': 'max', 'show_at_startup': False})

    def test_main_window_applies_level_and_gear_opens_setup(self):
        from app import Window
        w = Window()
        try:
            w.apply_tier('fast')
            self.assertEqual(w.ai_model.currentText(), 'qwen3-vl:2b-instruct')
            self.assertEqual(w.ai_profile.currentText(), 'Fast')
            w.apply_tier('max')
            self.assertEqual(w.ai_model.currentText(), 'qwen3-vl:8b-instruct')
            self.assertEqual(w.ai_profile.currentText(), 'Quality')
            # Swap in a stand-in window class. (Patching a method on the real
            # Qt class crashes PySide6 when it later connects signals.)
            opened = []
            class FakeDialog:
                def __init__(self, parent=None):
                    from types import SimpleNamespace
                    opened.append(parent)
                    self.tier_applied = SimpleNamespace(connect=lambda slot: opened.append(slot))
                def exec(self):
                    return 0
            with patch('setup_wizard.SetupDialog', FakeDialog):
                w.settings_button.click()
            self.assertIs(opened[0], w)
            self.assertEqual(opened[1], w.apply_tier)
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
