"""The original image and its drawing stay paired across every entry point."""
import copy,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QMessageBox
from test_artwork_workflow import WorkflowFixture

def pair(root):
    original=Path(root)/'original.png';guide=Path(root)/'guide.png'
    color=Image.new('RGBA',(100,80),(0,0,0,0))
    ImageDraw.Draw(color).ellipse((10,10,90,70),fill=(235,70,45,255))
    color.save(original)
    lines=Image.new('RGB',(100,80),'white')
    ImageDraw.Draw(lines).ellipse((10,10,90,70),outline='black',width=3)
    lines.save(guide)
    return original,guide

class PairingTests(WorkflowFixture):
    def test_add_ai_element_does_not_erase_result_kind_or_original(self):
        self.api();original,guide=pair(self.tmp.name);calls=[]
        def dialog(parent,current,callback,engine):
            callback('lineart',str(guide),str(original))
            return SimpleNamespace(exec=lambda:None)
        with patch('create_image_dialog.CreateImageDialog',side_effect=dialog),\
             patch.object(self.w,'use_ai_result',side_effect=lambda *a,**kw:calls.append(a)):
            self.w.new_element('ai')
        self.assertEqual(calls[0][:3],('lineart',str(guide),str(original)))
    def test_library_pairing_survives_original_deletion_and_library_move(self):
        import library,artwork_assets
        original,guide=pair(self.tmp.name);lib=library.Library()
        item=lib.add('images',guide)
        self.assertTrue(callable(getattr(lib,'set_artwork',None)),'Library must retain paired artwork')
        data=artwork_assets.capture_assets(original,guide);lib.set_artwork(item,data)
        expected=original.read_bytes();original.unlink();guide.unlink()
        lib.move_to(Path(self.tmp.name)/'Moved library')
        moved=lib.items('images')[0]
        p,g=artwork_assets.materialize_assets(moved.artwork,Path(self.tmp.name)/'restored')
        self.assertEqual(Path(p).read_bytes(),expected);self.assertTrue(Path(g).is_file())
    def test_saved_pair_is_self_contained_and_old_project_still_loads(self):
        self.api();original,guide=pair(self.tmp.name)
        self.w.image_detail.setCurrentText('Low')
        self.w.request_artwork(str(guide),kind='lineart',original=str(original),placement='add')
        self.wait_import()
        data=self.w.project_state()
        self.assertIn('artwork',data,'Saved project must include its original and guide, not only paths')
        original.unlink();guide.unlink()
        self.w.apply_project(data)
        self.assertTrue(Path(self.w.image_path).is_file())
        self.assertTrue(Path(self.w.image_guide).is_file())
        self.assertIsNotNone(self.w.options()['final_image'])
        old=copy.deepcopy(data);old.pop('artwork',None)
        old['image']['path']='missing-original.png';old['image']['guide']='missing-guide.png'
        self.w.apply_project(old)
        self.assertIsNotNone(self.w.options()['final_image'])
    def test_explicit_drawing_only_suppresses_paint_but_paint_only_still_works(self):
        self.api();original,guide=pair(self.tmp.name)
        self.w.image_detail.setCurrentText('Low')
        self.w.request_artwork(str(guide),kind='lineart',original=str(original),placement='add')
        self.wait_import()
        index=self.w.image_animation.findText('Drawing only')
        self.assertGreaterEqual(index,0,'Drawing-only must be an explicit choice')
        self.w.image_animation.setCurrentIndex(index)
        self.assertIsNone(self.w.options()['final_image'])
        self.assertGreater(self.w.options()['duration'],0)
        self.assertAlmostEqual(self.w.element_times(self.w.scene_index)[0],self.w.options()['duration']+self.w.options().get('pause',0))
        self.w.image_animation.setCurrentText('Paint Only')
        self.assertIsNotNone(self.w.options()['final_image'])
        self.assertEqual(self.w.options()['duration'],0)

class GuideFramingTests(unittest.TestCase):
    def test_letterboxed_portrait_guide_preserves_proportions(self):
        from image_reconstruct import reconstruct
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'portrait.png';g=Path(tmp)/'square-guide.png'
            color=Image.new('RGBA',(90,180),(0,0,0,0))
            ImageDraw.Draw(color).ellipse((10,20,80,160),fill=(30,150,220,255));color.save(p)
            lines=Image.new('RGB',(90,180),'white')
            ImageDraw.Draw(lines).ellipse((10,20,80,160),outline='black',width=3)
            square=Image.new('RGB',(180,180),'white');square.paste(lines,(45,0));square.save(g)
            result=reconstruct(str(p),detail='low',line_guide=str(g))
            self.assertTrue(hasattr(result.drawing,'source_frame'),'Guide framing must be recorded')
            self.assertGreater(result.drawing.line_guide_score,.5)
            self.assertEqual(result.drawing.source_frame['guide_fit'],'cover')
if __name__=='__main__':unittest.main()
