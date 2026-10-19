"""Source edits replace only the chosen asset, retain timing and survive project I/O."""
import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QFileDialog
from projects import drawing_to_dict,save,load
from test_artwork_workflow import WorkflowFixture
from test_artwork_pairing import pair

class PaintSourceTests(WorkflowFixture):
    def setup_image(self):
        original,guide=pair(self.tmp.name)
        self.w.image_detail.setCurrentText('Low')
        self.w.request_artwork(str(guide),kind='lineart',original=str(original),placement='add')
        self.wait_import()
        return original,guide
    def api_source(self):
        self.assertTrue(callable(getattr(self.w,'replace_paint_source',None)),
                        'Shared painting-source replacement is missing')
    def blue(self,name='blue.png'):
        p=Path(self.tmp.name)/name
        Image.new('RGBA',(100,80),(30,70,225,255)).save(p)
        return p
    def test_image_button_is_enabled_and_named_for_original_image(self):
        self.setup_image()
        self.assertTrue(self.w.load_color_button.isEnabled())
        self.assertIn('original image',self.w.load_color_button.text().lower())
    def test_repeated_paint_changes_keep_paths_settings_and_other_elements(self):
        self.setup_image();self.api_source()
        old_strokes=tuple(self.w.drawing.strokes)
        other=copy.deepcopy(self.w.scenes[0]['state'])
        self.w.duration.setValue(6.);self.w.ax.setValue(.31)
        settings=self.w.settings_state()
        for name,rgb in (('blue.png',(30,70,225)),('green.webp',(40,190,80)),('orange.jpg',(230,110,30))):
            with self.subTest(name=name):
                p=Path(self.tmp.name)/name;Image.new('RGB',(100,80),rgb).save(p)
                self.assertTrue(self.w.replace_paint_source(str(p)))
                self.assertEqual(tuple(self.w.drawing.strokes),old_strokes)
                self.assertTrue(all(a is b for a,b in zip(self.w.drawing.strokes,old_strokes)))
                self.assertEqual(self.w.settings_state(),settings)
                self.assertEqual(self.w.scenes[0]['state'],other)
                self.assertEqual(len(self.w.scenes),2)
                self.assertIsNotNone(self.w.options()['final_image'])
                c=self.w.image_result.image.pixelColor(50,40)
                for actual,want in zip((c.red(),c.green(),c.blue()),rgb):
                    self.assertLessEqual(abs(actual-want),3)
    def test_cancel_and_invalid_file_do_not_modify_project(self):
        self.setup_image();self.api_source();before=self.w.project_state()
        with patch.object(QFileDialog,'getOpenFileName',return_value=('','')):
            self.w.load_color()
        self.assertEqual(self.w.project_state(),before)
        bad=Path(self.tmp.name)/'bad.png';bad.write_bytes(b'not an image')
        with patch('PySide6.QtWidgets.QMessageBox.warning'):
            self.assertFalse(self.w.replace_paint_source(str(bad)))
        self.assertEqual(self.w.project_state(),before)
    def test_paint_source_reopens_after_external_files_deleted(self):
        original,guide=self.setup_image();self.api_source();blue=self.blue()
        self.w.replace_paint_source(str(blue))
        path=save(Path(self.tmp.name)/'paired',self.w.project_state())
        original.unlink();guide.unlink();blue.unlink()
        self.w.apply_project(load(path))
        self.assertTrue(Path(self.w.image_path).is_file())
        self.assertTrue(Path(self.w.image_guide).is_file())
        self.assertEqual(self.w.image_result.image.pixelColor(50,40).blue(),225)
        self.assertEqual(self.w.drawing.artwork_assets['original']['extension'],'.png')
    def test_paint_replacement_undo_redo_restores_both_source_and_pixels(self):
        self.setup_image();self.api_source()
        before=self.w.image_result.image.pixelColor(30,30)
        old_path=self.w.image_path
        self.w.replace_paint_source(str(self.blue()))
        self.assertTrue(self.w.history.can_undo())
        self.w.undo()
        self.assertEqual(self.w.image_path,old_path)
        self.assertEqual(self.w.image_result.image.pixelColor(30,30),before)
        self.w.redo()
        self.assertEqual(self.w.image_result.image.pixelColor(50,40).blue(),225)
    def test_outline_svg_first_paint_is_one_undo_and_named_after_reopen(self):
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        old=self.w.color_path;count=len(self.w.history.undo_stack)
        self.w.replace_paint_source(str(self.blue()))
        self.assertEqual(len(self.w.history.undo_stack),count+1)
        self.w.undo();self.assertEqual(self.w.color_path,old);self.assertIsNone(self.w.final_image)
        self.w.redo()
        state=self.w.scene_state();self.w.apply_scene_state(state)
        self.assertIn('blue.png',self.w.color_note.text())
        self.w.clean_color.setChecked(not self.w.clean_color.isChecked())
        self.assertIn('blue.png',self.w.color_note.text())
    def test_svg_jpeg_and_webp_reclean_from_original_without_png_restriction(self):
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        for name in ('colors.jpg','colors.webp','colors.bmp'):
            p=Path(self.tmp.name)/name;Image.new('RGB',(100,80),(30,70,225)).save(p)
            self.w.replace_paint_source(str(p))
            self.w.clean_color.setChecked(True);self.w.clean_color.setChecked(False)
            self.assertIn(name,self.w.color_note.text())
            self.assertGreater(self.w.final_image.pixelColor(50,40).blue(),220)
    def test_svg_matching_color_replacement_retains_native_vectors(self):
        self.api_source()
        self.svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"><rect x="10" y="10" width="80" height="60" fill="black"/></svg>')
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        strokes=tuple(self.w.drawing.strokes)
        self.w.clean_color.setChecked(False)
        self.assertTrue(self.w.replace_paint_source(str(self.blue())))
        self.assertEqual(tuple(self.w.drawing.strokes),strokes)
        self.assertFalse(self.w.is_image_artwork())
        self.assertEqual(self.w.options()['final_image'].pixelColor(50,40).blue(),225)
        state=self.w.scene_state();self.w.apply_scene_state(state)
        self.assertEqual(self.w.options()['final_image'].pixelColor(50,40).blue(),225)

if __name__=='__main__':unittest.main()
