"""Filmora-style, non-destructive artwork blend mode regressions."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from blend_modes import MODES, composition_mode
from scenes import stack

APP=QApplication.instance() or QApplication([])


def solid(rgb,size=(64,48)):
    im=QImage(*size,QImage.Format.Format_ARGB32_Premultiplied)
    im.fill(QColor(*rgb))
    return im


class BlendTests(unittest.TestCase):
    def test_normal_is_default_and_modes_are_supported(self):
        from PySide6.QtGui import QPainter
        self.assertEqual(composition_mode('No longer offered'),
                         QPainter.CompositionMode.CompositionMode_SourceOver)
        self.assertTrue({'Normal','Multiply','Screen','Darken','Lighten'}<=set(MODES))
        for name in MODES:
            self.assertIsNotNone(composition_mode(name))

    def test_multiply_hides_white_paper_over_existing_background(self):
        base=solid((70,130,190))
        sheet=solid((255,255,255))
        black=QColor(0,0,0)
        sheet.setPixelColor(15,10,black)
        normal=stack(base,sheet,'Normal')
        multiplied=stack(base,sheet,'Multiply')
        self.assertEqual(normal.pixelColor(0,0),QColor(255,255,255))
        self.assertEqual(multiplied.pixelColor(0,0),QColor(70,130,190))
        self.assertEqual(multiplied.pixelColor(15,10),black)
        self.assertEqual(base.pixelColor(15,10),QColor(70,130,190))

    def test_screen_retains_light_detail_over_existing_background(self):
        base=solid((50,100,150))
        ink=solid((0,0,0))
        ink.setPixelColor(3,3,QColor(255,255,255))
        mixed=stack(base,ink,'Screen')
        self.assertEqual(mixed.pixelColor(0,0),QColor(50,100,150))
        self.assertEqual(mixed.pixelColor(3,3),QColor(255,255,255))

    def test_transparent_base_does_not_fake_white_removal(self):
        clear=QImage(16,16,QImage.Format.Format_ARGB32_Premultiplied)
        clear.fill(0)
        white=solid((255,255,255),(16,16))
        result=stack(clear,white,'Multiply')
        self.assertEqual(result.pixelColor(0,0).alpha(),255)

    def test_board_finished_art_uses_per_element_blend(self):
        from board import World
        white=solid((255,255,255))
        gray=solid((70,130,190))
        items=[dict(frame=(0,0,1),options={'blend_mode':'Normal'},key=('one',)),
               dict(frame=(0,0,1),options={'blend_mode':'Multiply'},key=('two',))]
        world=World(items,48/64)
        world.finished=lambda idx,width: gray if idx==0 else white
        # This fixture tests artwork blend only; independent overlays are
        # tested separately with real drawing data in test_element_appearance.
        world.finished_extras=lambda idx,width: None
        world.place=lambda *args:(0,0,64,48)
        image=world.view((0,0,1),64,48,upto=2)
        self.assertEqual(image.pixelColor(0,0),QColor(70,130,190))

    def test_changing_blend_mode_updates_live_monitor(self):
        from app import Window
        w=Window()
        try:
            w.show()
            APP.processEvents()
            w.preview_background.setCurrentText('Dark')
            w.blend_mode.setCurrentText('Multiply')
            APP.processEvents()
            self.assertEqual(w.canvas.blend_mode,'Multiply')
            w.blend_mode.setCurrentText('Screen')
            APP.processEvents()
            self.assertEqual(w.canvas.blend_mode,'Screen')
        finally:
            w.close()
            APP.processEvents()

    def test_monitor_composites_against_contrasting_background(self):
        from app import Canvas
        w=Canvas()
        try:
            w.resize(620,400)
            w.frame=solid((255,255,255),(160,90))
            w.set_background(2)  # Dark
            w.show()
            APP.processEvents()
            w.blend_mode='Normal'
            w.update()
            APP.processEvents()
            normal=w.grab().toImage()
            w.blend_mode='Multiply'
            w.update()
            APP.processEvents()
            multiplied=w.grab().toImage()
            center=(w.width()//2,w.height()//2)
            self.assertNotEqual(normal.pixelColor(*center),multiplied.pixelColor(*center))
        finally:
            w.close()
            APP.processEvents()

    def test_ui_setting_maps_to_export_and_project_reload(self):
        from app import Window
        w=Window()
        try:
            self.assertEqual(w.blend_mode.currentText(),'Normal')
            w.blend_mode.setCurrentText('Multiply')
            options=w.options()
            self.assertEqual(options['blend_mode'],'Multiply')
            saved=w.project_state()
            w.blend_mode.setCurrentText('Normal')
            w.apply_project(saved)
            self.assertEqual(w.blend_mode.currentText(),'Multiply')
        finally:
            w.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
