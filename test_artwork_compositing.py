"""Artwork compositing regression tests. No model, ComfyUI or network required."""
import os
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtGui import QColor,QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from scenes import stack
from artwork_compositor import composite_element
from paper_cleanup import clean_paper

APP=QApplication.instance() or QApplication([])


def img(rgb=(255,255,255),size=(28,24)):
    q=QImage(*size,QImage.Format.Format_ARGB32_Premultiplied)
    q.fill(QColor(*rgb))
    return q


class AppearanceCompositingTests(unittest.TestCase):
    def test_multiply_pure_white_is_neutral_but_offwhite_is_not(self):
        base=img((60,90,130))
        pure=stack(base,img((255,255,255)),'Multiply')
        warm=stack(base,img((245,240,238)),'Multiply')
        self.assertEqual(pure.pixelColor(0,0),base.pixelColor(0,0))
        self.assertNotEqual(warm.pixelColor(0,0),base.pixelColor(0,0))

    def test_opacity_does_not_modify_inputs(self):
        lower=img((0,0,0)); top=img((255,255,255))
        composite=stack(lower,top,'Normal',50)
        pixel=composite.pixelColor(2,2)
        self.assertGreater(pixel.red(),120)
        self.assertLess(pixel.red(),135)
        self.assertEqual(top.pixelColor(2,2),QColor(255,255,255))
        self.assertEqual(lower.pixelColor(2,2),QColor(0,0,0))

    def test_separate_hand_is_never_multiplied_or_faded(self):
        base=img((90,130,190))
        artwork=img((255,255,255))
        artwork.setPixelColor(3,3,QColor(0,0,0))
        hand=QImage(*artwork.size(),QImage.Format.Format_ARGB32_Premultiplied)
        hand.fill(0)
        hand.setPixelColor(10,10,QColor(255,100,50))
        def fake_compose(drawing,fraction,options,camera_path=None):
            return hand if options['layers']=='hand' else artwork
        with patch('frame_render.compose_frame',side_effect=fake_compose):
            mixed=composite_element(base,object(),.5,
                                   dict(layers='all',blend_mode='Multiply',artwork_opacity=40))
        self.assertEqual(mixed.pixelColor(10,10),QColor(255,100,50))
        self.assertNotEqual(mixed.pixelColor(3,3),QColor(0,0,0))
        self.assertEqual(base.pixelColor(10,10),QColor(90,130,190))

    def test_paper_cleanup_removes_only_border_connected_white(self):
        source=img((247,246,244),(36,36))
        from PySide6.QtGui import QPainter,QPen
        painter=QPainter(source)
        painter.setPen(QPen(QColor(10,10,10),2))
        painter.drawRect(9,9,17,17)
        painter.end()
        original=source.copy()
        clean=clean_paper(source,tolerance=23,softness=0)
        self.assertEqual(clean.pixelColor(0,0).alpha(),0)
        self.assertEqual(clean.pixelColor(17,17).alpha(),255)
        self.assertEqual(clean.pixelColor(9,9).alpha(),255)
        self.assertEqual(source.pixelColor(0,0),original.pixelColor(0,0))

    def test_paper_cleanup_softness_and_off_switch(self):
        source=img((255,255,255))
        source.setPixelColor(0,0,QColor(237,237,237))
        hard=clean_paper(source,22,0)
        soft=clean_paper(source,22,10)
        self.assertEqual(hard.pixelColor(0,0).alpha(),0)
        self.assertGreater(soft.pixelColor(0,0).alpha(),0)
        self.assertLess(soft.pixelColor(0,0).alpha(),255)
        self.assertEqual(source.pixelColor(0,0).alpha(),255)

    def test_single_export_composer_keeps_hand_full_color(self):
        from frame_render import compose_frame
        art=img((255,255,255))
        pen=QImage(*art.size(),QImage.Format.Format_ARGB32_Premultiplied)
        pen.fill(0);pen.setPixelColor(12,12,QColor(225,45,25))
        def fake_raw(drawing,fraction,options,camera_path=None):
            return pen if options.get('layers')=='hand' else art
        with patch('frame_render._compose_raw_frame',side_effect=fake_raw):
            result=compose_frame(object(),.4,dict(layers='all',
                artwork_opacity=25,blend_mode='Screen'))
        self.assertEqual(result.pixelColor(12,12),QColor(225,45,25))
        faded=result.pixelColor(2,2)
        self.assertTrue(50<=faded.alpha()<=70, faded)

    def test_board_applies_each_saved_element_opacity_separately(self):
        from board import World
        white=img((255,255,255))
        red=img((255,0,0))
        items=[dict(frame=(0,0,1),options=dict(blend_mode='Normal',
                    artwork_opacity=100),key=('first',)),
               dict(frame=(0,0,1),options=dict(blend_mode='Normal',
                    artwork_opacity=20),key=('second',))]
        world=World(items,24/28)
        world.finished=lambda idx,width: white if idx==0 else red
        world.place=lambda *args:(0,0,28,24)
        actual=world.view((0,0,1),28,24,upto=2).pixelColor(12,12)
        self.assertGreater(actual.green(),195)
        self.assertLess(actual.red(),256)

    def test_per_scene_settings_independent_and_backward_compatible(self):
        from export_job import options_from_settings
        s1=dict(res='1920 × 1080',blend_mode='Multiply',artwork_opacity=60)
        s2=dict(res='1920 × 1080',blend_mode='Normal',artwork_opacity=100)
        s3=dict(res='1920 × 1080',blend_mode='Darken',artwork_opacity=85)
        results=[options_from_settings(s,None) for s in (s1,s2,s3)]
        self.assertEqual([r['blend_mode'] for r in results],
                         ['Multiply','Normal','Darken'])
        self.assertEqual([r['artwork_opacity'] for r in results],[60,100,85])
        self.assertEqual(s1['artwork_opacity'],60)

    def test_element_editor_mirrors_settings_and_undoes_on_cancel(self):
        from app import Window
        from element_dialog import ElementDialog
        w=Window()
        try:
            self.assertEqual(w.artwork_opacity.value(),100)
            self.assertFalse(w.paper_cleanup.isChecked())
            dialog=ElementDialog(w,w.scene_index)
            try:
                self.assertIsNotNone(dialog.paper_checkbox)
                self.assertEqual(w.blend_mode.currentText(),'Normal')
                w.artwork_opacity.setValue(65)
                w.paper_cleanup.setChecked(True)
                settings=w.settings_state()
                self.assertEqual(settings['artwork_opacity'],65)
                self.assertTrue(settings['paper_cleanup'])
            finally:
                dialog.reject()
            self.assertEqual(w.artwork_opacity.value(),100)
            self.assertFalse(w.paper_cleanup.isChecked())
        finally:
            w.close()

    def test_project_disk_roundtrip_keeps_appearance_with_original_source(self):
        from app import Window
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import projects
        first=Window()
        try:
            first.blend_mode.setCurrentText('Screen')
            first.artwork_opacity.setValue(43)
            first.paper_cleanup.setChecked(True)
            first.paper_tolerance.setValue(31)
            first.paper_softness.setValue(11)
            with TemporaryDirectory() as temp:
                path=projects.save(Path(temp)/'artwork.strokescribe',
                                   first.project_state())
                project=projects.load(path)
                saved=project['settings']
                self.assertEqual(saved['blend_mode'],'Screen')
                self.assertEqual(saved['artwork_opacity'],43)
                self.assertTrue(saved['paper_cleanup'])
                self.assertEqual(saved['paper_tolerance'],31)
                self.assertEqual(saved['paper_softness'],11)
                # No save operation may mutate embedded source artwork.
                self.assertIn('drawing',project)
        finally:
            first.close()

    def test_paint_complete_uses_cleaned_visual_without_mutating_original(self):
        from image_painting import paint_frame,original_frame
        from types import SimpleNamespace
        drawing=SimpleNamespace(bounds=(0,0,28,24),source_kind='image')
        original=img((245,245,245))
        cleaned=clean_paper(original,tolerance=23,softness=0)
        frame=paint_frame(drawing,original,64,48,.99,1,.14,.55,
                          None,.1,(.1,.1),False,display_image=cleaned)
        plain=original_frame(drawing,original,64,48)
        self.assertGreater(plain.pixelColor(30,25).alpha(),0)
        self.assertEqual(frame.pixelColor(30,25).alpha(),0)
        self.assertEqual(original.pixelColor(2,2).alpha(),255)

    def test_legacy_image_settings_do_not_inherit_previous_opacity(self):
        from export_job import options_from_settings
        s=dict(res='1920 × 1080',blend_mode='Multiply')
        opts=options_from_settings(s,None)
        self.assertEqual(opts['artwork_opacity'],100)
        self.assertFalse(opts['paper_cleanup'])

if __name__=="__main__":
    unittest.main(verbosity=2)
