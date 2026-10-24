"""Setup window and system preflight tests (fake FFmpeg answers)."""
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

    def test_levels_set_line_art_detail(self):
        self.assertEqual(preflight.TIER_ORDER, ('fast', 'balanced', 'quality', 'max'))
        self.assertEqual([preflight.TIERS[t]['detail'] for t in preflight.TIER_ORDER],
                         ['low', 'medium', 'high', 'max'])

    def test_checklist_has_libraries_model_and_no_ai_downloads(self):
        items = preflight.run_checks('max')
        keys = {i.key for i in items}
        self.assertIn('line_model', keys)
        self.assertIn('pkg:onnxruntime', keys)
        self.assertFalse(keys & {'ollama', 'model'})
        model = self.item(items, 'line_model')
        self.assertEqual(model.status, 'ok')
        self.assertTrue(model.location.endswith('teed.onnx'))
        pyside = self.item(items, 'pkg:PySide6')
        self.assertEqual(pyside.status, 'ok')
        self.assertTrue(Path(pyside.location).is_dir())
        with patch('preflight.LINE_MODEL', Path('/nonexistent/teed.onnx')):
            self.assertEqual(self.item(preflight.run_checks(), 'line_model').status, 'missing')

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

    def test_advice_for_low_disk(self):
        roomy = preflight.SystemInfo('Windows 11', 8., 4., 50., 'C:\\')
        self.assertEqual(preflight.advice(roomy, 'max'), [])
        tight = preflight.SystemInfo('Windows 11', 8., 4., 1., 'C:\\')
        self.assertTrue(any('free' in n for n in preflight.advice(tight, 'max')))

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
        self.assertIn('Line art detail: Max', dialog.tier_summary.text())
        info = preflight.SystemInfo('Windows 11', 16., 9., 120., 'C:\\Users\\me')
        items = [preflight.CheckItem('line_model', 'Line art model (TEED)', 'Lines', 'ok', '',
                                     r'C:\app\models\teed.onnx'),
                 preflight.CheckItem('ffmpeg', 'FFmpeg', 'Video export', 'missing',
                                     'videos need it', action='winget_ffmpeg', size_gb=.2)]
        dialog.show_results(info, items)
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertIn('Location: C:\\app\\models\\teed.onnx', dialog.table.item(0, 2).text())
        self.assertIn('Missing', dialog.table.item(1, 1).text())
        self.assertIn('0.2 GB', dialog.download_button.text())
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
            self.assertEqual(w.image_detail.currentText(), 'Low')
            w.apply_tier('max')
            self.assertEqual(w.image_detail.currentText(), 'Max')
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
