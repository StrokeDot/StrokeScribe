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

    def test_legacy_image_settings_do_not_inherit_previous_opacity(self):
        from export_job import options_from_settings
        s=dict(res='1920 × 1080',blend_mode='Multiply')
        opts=options_from_settings(s,None)
        self.assertEqual(opts['artwork_opacity'],100)
        self.assertFalse(opts['paper_cleanup'])

if __name__=="__main__":
    unittest.main(verbosity=2)
