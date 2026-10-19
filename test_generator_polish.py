"""Approved .62 follow-up: visible UI behavior and save-before-install safety."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox
import test_image_generator_updates as drawer_fixtures
from model_updates_live import ModelState
from image_generator_updates import UpdatePanel
from update_dialog import UpdateDialog
APP=QApplication.instance() or QApplication([])

class SmoothGeneratorTests(unittest.TestCase):
    setUp=drawer_fixtures.DrawerTests.setUp
    cleanup=drawer_fixtures.DrawerTests.cleanup
    wait_scan=drawer_fixtures.DrawerTests.wait_scan

    def test_panel_reverses_without_jump_and_x_finishes_closing(self):
        d=self.dialog
        d.resize(1500,900);d.show();APP.processEvents()
        d.open_updates();QTest.qWait(85)
        partial=d.updates_panel.width()
        self.assertGreater(partial,0)
        self.assertLess(partial,400,'Panel should not jump directly to its final width')
        d.close_updates();QTest.qWait(35)
        self.assertTrue(d.updates_panel.isVisible(),'Closing needs a visible transition')
        d.open_updates();self.wait_scan();QTest.qWait(300)
        self.assertEqual(d.updates_panel.width(),400)
        d.updates_panel.close_button.click();QTest.qWait(320)
        self.assertFalse(d.updates_panel.isVisible())
        self.assertFalse(d.check_updates_button.isChecked())

    def test_placeholder_has_icon_heading_and_explanation_after_reset(self):
        d=self.dialog
        d.show();d.show_result()
        text=' '.join(x.text() for x in d.preview.findChildren(QLabel))
        self.assertIn('The result appears here.',text)
        self.assertIn('Generate an image from your prompt',text)
        self.assertTrue(d.preview.findChild(QLabel,'resultPlaceholderIcon') is not None)

    def test_busy_motion_updates_at_display_rate_without_inventing_progress(self):
        d=self.dialog
        self.assertLessEqual(d.work_timer.interval(),17)
        d.on_progress(70,'Creating… 70%')
        APP.processEvents();QTest.qWait(70)
        self.assertGreater(d.progress.value(),0)
        self.assertLess(d.progress.value(),70,'Progress should animate toward the actual report')
        QTest.qWait(300)
        self.assertEqual(d.progress.value(),70)
        self.assertEqual(d.work['percent'],70)
        d.on_progress(-1,'Loading the model…')
        self.assertEqual(d.progress.maximum(),0)

    def test_finished_result_cannot_be_overwritten_by_pending_progress(self):
        d=self.dialog
        image=Path(self.tmp.name)/'made.png'
        pix=QPixmap(120,90);pix.fill(QColor('#7954dc'));pix.save(str(image))
        d.on_progress(70,'Creating… 70%')
        with patch('create_image_dialog.keep_in_library',return_value=None):
            d.on_result(str(image))
        self.assertEqual(d.progress.value(),100)
        QTest.qWait(320)
        self.assertEqual(d.progress.value(),100,'Completion must stop stale progress motion')

class PlainStatusTests(unittest.TestCase):
    def test_unknown_check_is_not_no_updates_and_optional_is_not_upgrade(self):
        states=[
            ModelState('one','Installed model','Publisher','Image generation','bf16','BF16',
                       'unverified','Connection unavailable',True),
            ModelState('two','Large model','Publisher','Image generation','q4','GGUF Q4',
                       'not_installed','Not installed',False),
        ]
        panel=UpdatePanel(items=states)
        try:
            text=' '.join(x.text() for x in panel.findChildren(QLabel))
            self.assertIn('Couldn’t check for updates',text)
            self.assertIn('Your installed model is unchanged',text)
            self.assertIn('Optional model',text)
            self.assertIn('not a required update',text)
            self.assertNotIn('Publisher check unavailable',text)
        finally:panel.close()

class UpdateBeforeSaveTests(unittest.TestCase):
    def test_online_and_zip_update_cancel_before_starting_any_worker(self):
        class Parent(QDialog):
            def confirm_before_app_update(self): return False
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'STROKESCRIBE_CONFIG_DIR':tmp}):
            parent=Parent();d=UpdateDialog(parent,latest='0.5.3-experimental.999',auto_check=False)
            try:
                with patch.object(d,'_start') as start,patch('updater.zip_version',return_value='0.5.3-experimental.999'):
                    d.update_online()
                    d.update_from_zip('sample.zip')
                    self.assertEqual(start.call_count,0,'Cancel must prevent all installation workers')
            finally:d.close();parent.close()

    def test_save_cancel_and_failed_save_block_update_and_success_marks_clean(self):
        from test_project_lifecycle import WindowLifecycleTests
        fixture=WindowLifecycleTests()
        fixture.setUp()
        w=fixture.w
        try:
            self.assertTrue(callable(getattr(w,'confirm_before_app_update',None)),
                            'Window must offer Save before installing, not only before restarting')
            w.duration.setValue(w.duration.value()+.5)
            for choice in (QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save):
                with patch.object(QMessageBox,'exec',return_value=int(choice)),patch.object(w,'save_project',return_value=None):
                    self.assertFalse(w.confirm_before_app_update())
            with patch.object(QMessageBox,'exec',return_value=int(QMessageBox.StandardButton.Save)),\
                 patch.object(w,'project_path',str(Path(fixture.tmp.name)/'saved.strokescribe'),create=True):
                self.assertTrue(w.confirm_before_app_update())
            self.assertFalse(w.has_unsaved_changes())
        finally:fixture.tearDown()

if __name__=='__main__':unittest.main(verbosity=2)
