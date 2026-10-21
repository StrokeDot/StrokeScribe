"""Appearance & Blending: mathematics, independent hand, paper cleanup and UI.

Real rendered pixel tests, plus project compatibility: no image bytes are
altered unless the optional feature is deliberately enabled.
"""
import os, unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD','1')

import numpy as np
from PySide6.QtGui import QImage,QColor
from PySide6.QtWidgets import QApplication
from scenes import stack,composite_element
from paper_cleanup import clean_paper,prepare_image

APP=QApplication.instance() or QApplication([])

def solid(r,g,b,w=100,h=100):
    image=QImage(w,h,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(r,g,b))
    return image

def pixel(image,x=1,y=1):
    c=image.pixelColor(x,y)
    return (c.red(),c.green(),c.blue(),c.alpha())

class AppearancePixelTests(unittest.TestCase):
    def test_white_multiply_is_expected_mathematics_not_transparency(self):
        white=solid(255,255,255)
        background=solid(120,180,220)
        self.assertEqual(pixel(stack(background,white,'Multiply')),pixel(background))
        self.assertEqual(pixel(stack(background,white,'Normal')),(255,255,255,255))
        self.assertEqual(pixel(stack(None,white,'Multiply')),(255,255,255,255))

    def test_hand_keeps_exact_opaque_pixel_even_over_dark_blending(self):
        under=solid(48,80,130)
        paper=solid(235,235,230)
        hand=QImage(100,100,QImage.Format.Format_ARGB32_Premultiplied)
        hand.fill(0)
        hand.setPixelColor(20,20,QColor(235,175,114))
        for mode in ('Normal','Multiply','Screen','Darken','Overlay'):
            for alpha in (0,35,100):
                image=stack(under,paper,mode,alpha,hand)
                self.assertEqual(pixel(image,20,20),(235,175,114,255),(mode,alpha))
                if alpha==0:
                    self.assertEqual(pixel(image),(48,80,130,255))

    def test_independent_scene_effects_do_not_spill_between_elements(self):
        red=solid(180,70,70)
        gray=solid(170,170,170)
        blue=solid(50,100,230)
        result=stack(stack(red,gray,'Multiply',55),blue,'Normal',80)
        result2=stack(stack(red,gray,'Multiply',55),blue,'Darken',80)
        self.assertNotEqual(pixel(result),pixel(result2))
        self.assertEqual(pixel(red),(180,70,70,255))

    def test_edge_connected_offwhite_removed_but_enclosed_white_kept(self):
        from PIL import Image,ImageDraw
        src=Image.new('RGBA',(120,96),(245,242,237,255))
        pen=ImageDraw.Draw(src)
        pen.rectangle((30,20,90,75),fill=(245,245,245,255),outline=(30,35,40,255),width=4)
        pen.line((5,10,25,10),fill=(50,55,60,255),width=3)
        rgba=np.asarray(src)
        raw=QImage(rgba.tobytes(),120,96,120*4,QImage.Format.Format_RGBA8888).copy()
        cleaned=clean_paper(raw,24,12)
        self.assertEqual(cleaned.pixelColor(0,0).alpha(),0)
        self.assertEqual(cleaned.pixelColor(60,48).alpha(),255)
        self.assertEqual(cleaned.pixelColor(30,20).alpha(),255)
        self.assertEqual(cleaned.pixelColor(10,10).alpha(),255)
        self.assertEqual(raw.pixelColor(0,0).alpha(),255)
        self.assertEqual(pixel(prepare_image(raw)),pixel(raw))
        self.assertIs(clean_paper(raw,24,12),cleaned)

    def test_coloured_borders_not_erased(self):
        blue=solid(110,180,220)
        cleaned=clean_paper(blue,80,40)
        self.assertEqual(pixel(blue),pixel(cleaned))

    def test_scene_helper_renders_hand_separately_from_artwork(self):
        from unittest.mock import patch
        background=solid(20,30,40)
        art=solid(245,245,245)
        hand=solid(200,100,30)
        calls=[]
        def fake(_drawing,_fraction,opts,_camera=None):
            calls.append(opts.get('layers','all'))
            return hand if opts.get('layers')=='hand' else art
        with patch('frame_render.compose_frame',side_effect=fake):
            output=composite_element(background,object(),.3,
                       {'blend_mode':'Multiply','artwork_opacity':40},None)
        self.assertEqual(calls,['art','hand'])
        self.assertEqual(pixel(output),(200,100,30,255))

class AppearanceProjectTests(unittest.TestCase):
    def setUp(self):
        from app import Window
        self.w=Window()
        self.w.resize(1440,900)
        self.w.show()
        APP.processEvents()

    def tearDown(self):
        self.w.playing=False
        self.w.close()
        APP.processEvents()

    def test_controls_are_per_scene_and_old_files_default_safely(self):
        w=self.w
        self.assertEqual(w.artwork_opacity.value(),100)
        self.assertFalse(w.paper_cleanup.isChecked())
        w.blend_mode.setCurrentText('Multiply')
        w.artwork_opacity.setValue(38)
        w.paper_cleanup.setChecked(True)
        w.paper_tolerance.setValue(31)
        w.paper_softness.setValue(8)
        original=w.project_state()
        self.assertTrue(w.new_element('text',text='Second element'))
        w.blend_mode.setCurrentText('Screen')
        w.artwork_opacity.setValue(88)
        w.paper_cleanup.setChecked(False)
        w.select_scene(0)
        self.assertEqual(w.blend_mode.currentText(),'Multiply')
        self.assertEqual(w.artwork_opacity.value(),38)
        self.assertTrue(w.paper_cleanup.isChecked())
        w.select_scene(1)
        self.assertEqual(w.blend_mode.currentText(),'Screen')
        self.assertEqual(w.artwork_opacity.value(),88)
        w.apply_project(original)
        self.assertEqual(w.blend_mode.currentText(),'Multiply')
        self.assertEqual(w.artwork_opacity.value(),38)
        self.assertEqual(w.paper_tolerance.value(),31)
        self.assertEqual(w.paper_softness.value(),8)
        legacy=w.project_state()
        legacy['settings'].pop('artwork_opacity',None)
        legacy['settings'].pop('paper_cleanup',None)
        legacy['settings'].pop('paper_tolerance',None)
        legacy['settings'].pop('paper_softness',None)
        w.apply_project(legacy)
        self.assertEqual(w.artwork_opacity.value(),100)
        self.assertFalse(w.paper_cleanup.isChecked())

    def test_element_dialog_controls_exist_and_mirror_live_settings(self):
        from element_dialog import ElementDialog
        w=self.w
        dlg=ElementDialog(w,w.scene_index)
        try:
            dlg.show()
            APP.processEvents()
            self.assertTrue(dlg.appearance_mode.isVisible())
            self.assertTrue(dlg.opacity.isVisible())
            self.assertTrue(dlg.clean_paper.isVisible())
            self.assertEqual(dlg.appearance_mode.count(),w.blend_mode.count())
            dlg.appearance_mode.setCurrentText('Darken')
            dlg.opacity.setValue(67)
            dlg.clean_paper.setChecked(True)
            self.assertEqual(w.blend_mode.currentText(),'Darken')
            self.assertEqual(w.artwork_opacity.value(),67)
            self.assertTrue(w.paper_cleanup.isChecked())
            dlg.test_background.setCurrentText('Dark')
            APP.processEvents()
            self.assertFalse(dlg.preview.pixmap().isNull())
        finally:
            dlg.reject()
        self.assertEqual(w.blend_mode.currentText(),'Normal')
        self.assertEqual(w.artwork_opacity.value(),100)

class AppearanceExportTests(unittest.TestCase):
    def test_frame_renderer_never_fades_hand_when_artwork_opacity_is_zero(self):
        from unittest.mock import patch
        from frame_render import compose_frame
        artwork=solid(180,180,180)
        hand=solid(210,130,40)
        def fake_core(_drawing,_fraction,opts,_camera=None):
            return hand if opts.get('layers')=='hand' else artwork
        with patch('frame_render._core',side_effect=fake_core):
            result=compose_frame(object(),.4,dict(width=100,height=100,
                duration=1.,artwork_opacity=0,background=False,overlays=[]))
        self.assertEqual(pixel(result),(210,130,40,255))

    def test_real_png_export_has_transparent_opacity_not_missing_parameter(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from app import Window
        from engine import export_frames
        w=Window()
        try:
            options=w.options()
            options.update(width=128,height=72,fps=4,duration=.5,
                hand=None,painting_hand=None,final_image=None,background=False,
                camera_zoom=1.,workers=1,erase=None,artwork_opacity=35,
                overlays=[],blend_mode='Normal')
            options.pop('audio',None)
            with TemporaryDirectory() as folder:
                target=Path(folder)/'pngframes'
                export_frames(w.drawing,target,**options)
                frame=QImage(str(sorted(target.glob('frame_*.png'))[-1]))
                self.assertFalse(frame.isNull())
                arr=np.frombuffer(frame.convertToFormat(QImage.Format.Format_RGBA8888).constBits(),np.uint8).reshape(72,-1)[:,:128*4].reshape(72,128,4)
                self.assertGreater(int(arr[:,:,3].max()),30)
                self.assertLessEqual(int(arr[:,:,3].max()),100)
        finally:
            w.close()
            APP.processEvents()

if __name__=='__main__':
    unittest.main(verbosity=2)
