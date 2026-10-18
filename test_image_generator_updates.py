"""UI contract for the image-only model update drawer; runs without models/network."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
import ai_engine
import ai_models
from create_image_dialog import CreateImageDialog

APP = QApplication.instance() or QApplication([])

class DrawerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'STROKESCRIBE_CONFIG_DIR':self.tmp.name})
        self.env.start()
        settings = ai_engine.load_settings()
        settings['root'] = str(Path(self.tmp.name)/'engine')
        ai_engine.save_settings(settings)
        self.dialog = CreateImageDialog(hardware=ai_models.Hardware('Test GPU',16,64,True))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.dialog.close()
        APP.processEvents()
        self.env.stop()
        self.tmp.cleanup()

    def drawer(self):
        self.assertTrue(hasattr(self.dialog,'updates_panel'),
                        'Create Image needs an image-generator updates drawer')
        return self.dialog.updates_panel

    def test_persistent_header_action_and_model_management(self):
        drawer = self.drawer()
        self.dialog.show(); APP.processEvents()
        self.assertFalse(drawer.isVisible())
        self.assertTrue(self.dialog.check_updates_button.isVisible())
        self.assertTrue(self.dialog.manage_models_button.isVisible())
        self.dialog.check_updates_button.click(); APP.processEvents()
        self.assertTrue(drawer.isVisible())
        self.assertTrue(self.dialog.check_updates_button.isVisible())
        self.dialog.check_updates_button.click()
        self.assertTrue(drawer.isVisible(), 'Repeated checks keep the drawer open')
        drawer.close_button.click()
        self.assertFalse(drawer.isVisible())
        self.assertTrue(self.dialog.check_updates_button.isVisible())

    def test_escape_closes_drawer_without_losing_generation_state(self):
        drawer = self.drawer()
        d = self.dialog
        path=Path(self.tmp.name)/'result.png'
        pix=QPixmap(80,60);pix.fill(QColor('#794fe8'));pix.save(str(path))
        d.prompt.setPlainText('My unchanged drawing prompt')
        d.seed.setValue(1701)
        d.new_seed.setChecked(False)
        d.result_path=str(path);d.show_result()
        model=d.model_box.currentData()
        d.show();d.check_updates_button.click();APP.processEvents()
        QTest.keyClick(d.prompt,Qt.Key.Key_Escape);APP.processEvents()
        self.assertFalse(drawer.isVisible())
        self.assertTrue(d.isVisible())
        self.assertEqual(d.prompt.toPlainText(),'My unchanged drawing prompt')
        self.assertEqual(d.seed.value(),1701)
        self.assertEqual(d.result_path,str(path))
        self.assertEqual(d.model_box.currentData(),model)
        self.assertFalse(d.preview.pixmap().isNull())

    def test_mock_sections_and_actions_cannot_start_real_downloads(self):
        drawer=self.drawer()
        d=self.dialog
        d.show();d.check_updates_button.click();APP.processEvents()
        labels=' '.join(w.text() for w in drawer.findChildren(QLabel))
        self.assertIn('Demonstration data',labels)
        self.assertIn('Installed models (2)',labels)
        self.assertIn('Updates available (1)',labels)
        self.assertIn('Compatible models (1)',labels)
        self.assertIn('audio',labels.lower())
        self.assertNotIn('Stable Audio',labels)
        with patch.object(d,'_start',side_effect=AssertionError('Must not launch a worker')):
            update=next(b for b in drawer.findChildren(QPushButton) if b.text()=='Update')
            update.click()
            self.assertIn('preview only',drawer.feedback.text().lower())
            keep=next(b for b in drawer.findChildren(QPushButton) if b.text()=='Keep current')
            keep.click()
            self.assertIn('kept',drawer.feedback.text().lower())
        drawer.close_button.click();d.check_updates_button.click()
        self.assertIn('kept',drawer.feedback.text().lower())

    def test_details_and_general_management_are_separate(self):
        self.drawer()
        d=self.dialog
        d.show();d.manage_models_button.click();APP.processEvents()
        manager=d.model_manager
        self.assertTrue(manager.isVisible())
        self.assertFalse(d.updates_panel.isVisible())
        choose=next(b for b in manager.findChildren(QPushButton)
                    if b.property('modelId')==ai_models.QWEN_EDIT.id)
        choose.click();APP.processEvents()
        self.assertEqual(d.task,'edit')
        self.assertEqual(d.model_box.currentData(),ai_models.QWEN_EDIT.id)
        self.assertFalse(manager.isVisible())

    def test_result_rescales_when_drawer_opens_and_closes(self):
        self.drawer()
        d=self.dialog
        path=Path(self.tmp.name)/'large-result.png'
        pix=QPixmap(1200,800);pix.fill(QColor('#794fe8'));pix.save(str(path))
        d.resize(1500,900);d.show();APP.processEvents()
        d.result_path=str(path);d.show_result(animate=False)
        for opened in (True,False):
            if opened:d.check_updates_button.click()
            else:d.updates_panel.close_button.click()
            QTest.qWait(50);APP.processEvents()
            shown=d.preview.pixmap()
            self.assertLessEqual(shown.width(),d.preview.width())
            self.assertLessEqual(shown.height(),d.preview.height())
            self.assertTrue(abs(shown.width()-d.preview.width())<=1 or
                            abs(shown.height()-d.preview.height())<=1,
                            'Result should fit the current preview, not its previous size')

    def test_title_bar_close_closes_dialog_even_when_drawer_is_open(self):
        drawer=self.drawer()
        d=self.dialog
        d.show();d.check_updates_button.click();APP.processEvents()
        self.assertTrue(drawer.isVisible())
        d.close();APP.processEvents()
        self.assertFalse(d.isVisible(),'Window close must not merely hide the drawer')

    def test_drawer_is_image_only_even_on_sound_tab(self):
        drawer=self.drawer()
        self.dialog.set_task('sound')
        self.dialog.show();self.dialog.check_updates_button.click();APP.processEvents()
        self.assertEqual(self.dialog.task,'sound')
        self.assertTrue(drawer.isVisible())
        self.assertNotIn('Stable Audio',' '.join(w.text() for w in drawer.findChildren(QLabel)))

    def test_narrow_and_wide_layout_never_overlaps_drawer(self):
        drawer=self.drawer()
        d=self.dialog
        d.show();d.check_updates_button.click()
        for width,height in ((1000,740),(1480,900)):
            d.resize(width,height);APP.processEvents()
            self.assertLessEqual(d.minimumSizeHint().width(),1000)
            self.assertGreaterEqual(drawer.width(),340)
            self.assertLessEqual(d.main_panel.geometry().right(),drawer.geometry().left())
            self.assertGreaterEqual(d.preview.width(),280)
            self.assertGreaterEqual(d.prompt.width(),200)
            self.assertLessEqual(d.check_updates_button.mapTo(d,d.check_updates_button.rect().topRight()).x(),
                                 drawer.geometry().left())
        drawer.close_button.click();APP.processEvents()
        self.assertFalse(drawer.isVisible())

class MetadataTests(unittest.TestCase):
    def test_metadata_is_injectable_and_never_mixes_audio(self):
        self.assertIsNotNone(importlib.util.find_spec('image_generator_updates'),
                             'Reusable image update UI module is missing')
        from image_generator_updates import ModelUpdateItem, UpdatePanel
        image=ModelUpdateItem(id='sample',name='Example Image',provider='Example',
                              category='Image generation',installed=False,
                              available_version='2',precision='BF16',download_size=123,
                              compatibility='Fits your PC')
        sound=ModelUpdateItem(id='sound',name='Hidden Sound',provider='Example',
                              category='Audio',installed=True,installed_version='1')
        panel=UpdatePanel(items=(image,sound))
        try:
            text=' '.join(w.text() for w in panel.findChildren(QLabel))
            self.assertIn('Example Image',text)
            self.assertNotIn('Hidden Sound',text)
            self.assertIn('Installed models (0)',text)
            self.assertIn('Compatible models (1)',text)
        finally: panel.close()

if __name__=='__main__':unittest.main()
