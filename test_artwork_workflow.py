"""Placement is a transaction: prepare first, commit one element, retain others."""
import copy,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog
from PIL import Image
APP=QApplication.instance() or QApplication([])
class WorkflowFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'STROKESCRIBE_CONFIG_DIR':self.tmp.name,'STROKESCRIBE_TEST_AUTODISCARD':'0'})
        self.env.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.env.stop)
        import library
        library.save_settings(dict(root=str(Path(self.tmp.name)/'Library'),keep_imports=True))
        self.warning=patch.object(QMessageBox,'warning',side_effect=lambda *args:self.fail('Unexpected warning: '+str(args[-1])))
        self.warning.start()
        self.addCleanup(self.warning.stop)
        from app import Window
        self.w=Window();self.w.show();APP.processEvents()
        self.svg=Path(self.tmp.name)/'new.svg'
        self.svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><path d="M10 10L100 60" fill="none" stroke="#ed8045"/></svg>')
    def tearDown(self):
        if self.w.builder and self.w.builder.isRunning():
            if hasattr(self.w,'cancel_artwork_import'):self.w.cancel_artwork_import()
            self.w.builder.wait(60000);APP.processEvents()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Discard):
            self.w.close()
        import applog
        applog._on_error[:]=[c for c in applog._on_error if getattr(c,'__self__',None) is not self.w]
        self.w.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
        self.env.stop();self.tmp.cleanup()
    def api(self):
        self.assertTrue(callable(getattr(self.w,'request_artwork',None)),'Shared non-destructive artwork placement is missing')
    def wait_import(self):
        if self.w.builder:
            self.assertTrue(self.w.builder.wait(60000))
        APP.processEvents();QTest.qWait(10);APP.processEvents()

class PlacementTests(WorkflowFixture):
    def test_default_add_retains_existing_artwork_and_has_no_leave_prompt(self):
        self.api()
        from projects import drawing_to_dict
        before=copy.deepcopy(drawing_to_dict(self.w.drawing))
        with patch.object(QInputDialog,'getItem',return_value=('Add to current project',True)) as choose,\
             patch.object(QMessageBox,'question',side_effect=AssertionError('Add cannot discard work')):
            self.assertTrue(self.w.request_artwork(str(self.svg),kind='svg'))
        self.assertEqual(choose.call_args.args[3][0],'Add to current project')
        self.assertEqual(len(self.w.scenes),2)
        self.assertEqual(self.w.scenes[0]['state']['drawing'],before)
    def test_replace_selected_keeps_other_element_and_project_identity(self):
        self.api()
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        before=copy.deepcopy(self.w.scenes[0]['state'])
        self.w.project_path='existing.strokescribe'
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.w.request_artwork(str(self.svg),kind='svg',placement='replace'))
        self.assertEqual(len(self.w.scenes),2)
        self.assertEqual(self.w.scenes[0]['state'],before)
        self.assertEqual(self.w.project_path,'existing.strokescribe')
    def test_same_page_add_preserves_join_direction_and_planned_position(self):
        self.api()
        with patch.object(self.w,'free_spot',return_value=(45.,-20.,0.)):
            self.assertTrue(self.w.request_artwork(str(self.svg),kind='svg',placement='add',same_spot=True))
        self.assertEqual(self.w.scenes[0]['transition'],'Same page')
        self.assertEqual(self.w.artwork_size.value(),45.)
        self.assertEqual(self.w.picture_x.value(),-20.)

    def test_invalid_import_never_adds_a_scene_shell(self):
        self.api()
        self.svg.write_text('broken SVG')
        old=self.w.drawing
        with patch.object(QMessageBox,'warning'):
            self.assertFalse(self.w.request_artwork(str(self.svg),kind='svg',placement='add'))
        self.assertIs(self.w.drawing,old);self.assertEqual(len(self.w.scenes),1)
    def test_new_project_cancel_and_failed_save_preserve_work(self):
        self.api();old=self.w.drawing
        self.w.duration.setValue(self.w.duration.value()+1)
        for choice in (QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save):
            with patch.object(QMessageBox,'question',return_value=choice),patch.object(self.w,'save_project',return_value=None):
                self.assertFalse(self.w.new_project())
                self.assertIs(self.w.drawing,old)
    def test_new_project_after_saving_is_empty_and_clean(self):
        self.api()
        path=Path(self.tmp.name)/'previous.strokescribe'
        self.w.duration.setValue(self.w.duration.value()+1)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save),\
             patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(path),'StrokeScribe project')):
            self.assertTrue(self.w.new_project())
        self.assertTrue(path.is_file())
        self.assertFalse(self.w.drawing.strokes)
        self.assertIsNone(self.w.project_path)
        self.assertFalse(self.w.has_unsaved_changes())
        self.assertFalse(self.w.export.isEnabled())
    def test_cancelled_async_import_cannot_replace_current_artwork(self):
        self.api()
        p=Path(self.tmp.name)/'raster.png';Image.new('RGBA',(80,60),(40,100,200,255)).save(p)
        old=self.w.drawing
        self.w.image_detail.setCurrentText('Low')
        self.assertTrue(self.w.request_artwork(str(p),placement='add'))
        self.w.cancel_artwork_import();self.wait_import()
        self.assertIs(self.w.drawing,old);self.assertEqual(len(self.w.scenes),1)

if __name__=='__main__':unittest.main()
