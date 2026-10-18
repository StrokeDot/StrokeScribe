"""Phase 2.3 RED tests: update cancellation and restart/rollback messaging."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import updater
from update_dialog import UpdateDialog, UpdateWorker

APP = QApplication.instance() or QApplication([])


class DownloadCancellationTests(unittest.TestCase):
    def test_cancellation_does_not_overwrite_existing_good_update_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'update.zip'
            path.write_bytes(b'previous download')
            class Response(io.BytesIO):
                headers = {'Content-Length': '131072'}
                def __enter__(self): return self
                def __exit__(self, *args): return False
            seen = [0]
            def progress(done, total):
                seen[0] = done
            with patch.object(updater, '_request', return_value=Response(b'A' * 131072)):
                with self.assertRaises(updater.CancelledUpdate):
                    updater.download(None, path, cancelled=lambda: seen[0] > 0, progress=progress)
            self.assertEqual(path.read_bytes(), b'previous download')
            self.assertFalse(path.with_suffix('.zip.partial').exists())

    def test_completed_download_replaces_old_file_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'update.zip'
            path.write_bytes(b'old')
            class Response(io.BytesIO):
                headers = {'Content-Length': '6'}
                def __enter__(self): return self
                def __exit__(self, *args): return False
            with patch.object(updater, '_request', return_value=Response(b'NEWZIP')):
                updater.download(None, path)
            self.assertEqual(path.read_bytes(), b'NEWZIP')


class WorkerCancellationTests(unittest.TestCase):
    def test_request_cancel_prevents_commit_and_removes_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            staged = MagicMock()
            staged.stage_dir = Path(temp) / 'stage'
            staged.stage_dir.mkdir()
            worker = UpdateWorker('update', zip_path=str(Path(temp) / 'candidate.zip'))
            def stage(*args, **kwargs):
                worker.request_cancel()
                return staged
            with patch.object(updater, 'stage_update', side_effect=stage), \
                 patch.object(updater, 'commit_update') as commit:
                with self.assertRaises(updater.CancelledUpdate):
                    worker._update(zip_path=str(Path(temp) / 'candidate.zip'))
                commit.assert_not_called()
            self.assertFalse(staged.stage_dir.exists())

    def test_cancel_is_refused_when_commit_is_in_progress(self):
        worker = UpdateWorker('update')
        worker.phase = 'installing'
        self.assertFalse(worker.request_cancel())
        self.assertFalse(worker.cancelled())


class DialogSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('STROKESCRIBE_CONFIG_DIR')
        os.environ['STROKESCRIBE_CONFIG_DIR'] = self.tmp.name
        self.d = UpdateDialog(None, latest='0.5.3-experimental.999', auto_check=False)
        self.d.show()
        APP.processEvents()

    def tearDown(self):
        self.d.worker = None
        self.d.close()
        if self.old is None: os.environ.pop('STROKESCRIBE_CONFIG_DIR', None)
        else: os.environ['STROKESCRIBE_CONFIG_DIR'] = self.old
        self.tmp.cleanup()

    def test_rollback_cancel_does_not_change_app_and_success_shows_restart(self):
        with patch.object(updater, 'can_roll_back', return_value=True), \
             patch.object(updater, 'roll_back', return_value='0.5.3-experimental.57') as rb:
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
                self.d.roll_back()
            rb.assert_not_called()
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.d.roll_back()
            rb.assert_called_once()
        self.assertTrue(self.d.restart_button.isVisible())
        self.assertIn('0.5.3-experimental.57', self.d.status.text())
        self.assertIn('Restart', self.d.status.text())

    def test_rollback_confirmation_names_restored_version(self):
        with patch.object(updater, 'rollback_target_version', return_value='0.5.3-experimental.57'), \
             patch.object(updater, 'roll_back') as rollback, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as confirm:
            self.d.roll_back()
            self.assertIn('0.5.3-experimental.57', str(confirm.call_args))
            rollback.assert_not_called()

    def test_running_worker_cannot_destroy_dialog_and_requests_cancel(self):
        busy = MagicMock()
        busy.isRunning.return_value = True
        busy.request_cancel.return_value = True
        busy.phase = 'downloading'
        self.d.worker = busy
        self.assertFalse(self.d.close())
        busy.request_cancel.assert_called_once()
        self.assertTrue(self.d.isVisible())

    def test_installing_worker_disables_cancel_and_close_is_blocked(self):
        busy = MagicMock()
        busy.isRunning.return_value = True
        busy.phase = 'installing'
        busy.request_cancel.return_value = False
        self.d.worker = busy
        self.d.refresh()
        self.assertFalse(self.d.cancel_button.isEnabled())
        self.assertFalse(self.d.close())
        self.assertIn('install', self.d.status.text().lower())

    def test_rejected_restart_keeps_dialog_open(self):
        class Parent(QDialog):
            def restart_after_update(self):
                return False
        parent = Parent()
        d = UpdateDialog(parent, latest='0.5.3-experimental.999', auto_check=False)
        d.show(); APP.processEvents()
        try:
            d.restart()
            self.assertTrue(d.isVisible())
        finally:
            d.close(); parent.close()

    def test_worker_cancel_status_is_not_reported_as_failure(self):
        w = UpdateWorker('update')
        self.d.worker = w
        self.d.on_failed('Update cancelled before installation.')
        self.assertNotIn('✗', self.d.status.text())
        self.assertIn('cancel', self.d.status.text().lower())
        self.d.worker = None


class RestartSafetyTests(unittest.TestCase):
    def test_failed_new_process_launch_keeps_original_window_open(self):
        from app import Window
        old_discard = os.environ.pop('STROKESCRIBE_TEST_AUTODISCARD', None)
        with tempfile.TemporaryDirectory() as temp:
            old = os.environ.get('STROKESCRIBE_CONFIG_DIR')
            os.environ['STROKESCRIBE_CONFIG_DIR'] = temp
            w = Window()
            w.show(); APP.processEvents()
            try:
                w.duration.setValue(w.duration.value() + 0.5)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard), \
                     patch.object(QMessageBox, 'warning'), \
                     patch.object(updater, 'restart', side_effect=OSError('cannot launch new process')):
                    self.assertFalse(w.restart_after_update())
                self.assertTrue(w.isVisible())
                self.assertTrue(w.has_unsaved_changes())
            finally:
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
                    w.close()
                if old is None: os.environ.pop('STROKESCRIBE_CONFIG_DIR', None)
                else: os.environ['STROKESCRIBE_CONFIG_DIR'] = old
        if old_discard is not None:
            os.environ['STROKESCRIBE_TEST_AUTODISCARD'] = old_discard

    def test_cancelled_unsaved_restart_never_launches_new_process(self):
        from app import Window
        old_discard = os.environ.pop('STROKESCRIBE_TEST_AUTODISCARD', None)
        with tempfile.TemporaryDirectory() as temp:
            old = os.environ.get('STROKESCRIBE_CONFIG_DIR')
            os.environ['STROKESCRIBE_CONFIG_DIR'] = temp
            w = Window()
            w.show(); APP.processEvents()
            try:
                w.duration.setValue(w.duration.value() + 0.5)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel), \
                     patch.object(updater, 'restart') as spawn:
                    self.assertFalse(w.restart_after_update())
                    spawn.assert_not_called()
                self.assertTrue(w.isVisible())
            finally:
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
                    w.close()
                if old is None: os.environ.pop('STROKESCRIBE_CONFIG_DIR', None)
                else: os.environ['STROKESCRIBE_CONFIG_DIR'] = old
        if old_discard is not None:
            os.environ['STROKESCRIBE_TEST_AUTODISCARD'] = old_discard


if __name__ == '__main__':
    unittest.main(verbosity=2)
