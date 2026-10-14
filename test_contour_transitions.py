"""Deterministic image-only transition regression and review fixtures."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from engine import Drawing, Stroke, render, export_frames
from adaptive_hand import qimage, adaptive_paint_mask
from color_reveal import render_color_timeline, artwork_rect
from contour_transition import retirement_states, remaining_contours, source_frame
from image_drawing import drawing_state
APP = QApplication.instance() or QApplication([])

def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(bytes(image.constBits()),np.uint8).reshape(image.height(),image.width(),4)

def fixture():
    image = Image.new('RGBA',(160,120))
    p = ImageDraw.Draw(image)
    p.arc((30,8,130,100),180,360,fill=(225,185,110,255),width=14)
    p.ellipse((18,45,60,103),fill=(205,145,65,255))
    p.ellipse((102,45,144,103),fill=(125,180,210,160))
    p.line((125,95,95,112,48,112),fill=(240,190,100,255),width=5)
    # Includes an intentionally protruding microphone trace.
    strokes = [
        Stroke('headband',[(30,50),(35,25),(65,10),(95,10),(125,25),(130,50)],'#142537',3),
        Stroke('left',[(20,55),(20,90),(40,103),(60,90),(60,55)],'#142537',3),
        Stroke('right',[(103,55),(103,90),(125,103),(144,90),(144,55)],'#142537',3),
        Stroke('microphone',[(125,95),(95,112),(38,112),(26,116)],'#142537',3)]
    drawing = Drawing(strokes,(0,0,160,120),[])
    drawing.source_kind='image'
    return drawing,qimage(image)

def frame(drawing,image,p,**kwargs):
    # One second drawing + one second paint, no hold.
    return render_color_timeline(drawing,(1+p)/2,width=320,height=240,
                                 duration=1,fade_duration=1,hold_duration=0,
                                 final_image=image,reveal_mode='adaptive',**kwargs)

class ContourTransitionTests(unittest.TestCase):
    def test_drawing_zero_future_hidden_and_pen_lift(self):
        d = Drawing([Stroke('a',[(10,10),(40,10)]),
                     Stroke('b',[(70,80),(100,80)])],(0,0,110,100),[])
        d.source_kind='image'
        self.assertEqual(pixels(render(d,0,220,200))[:,:,3].max(),0)
        early=pixels(render(d,.1,220,200))
        later=pixels(render(d,.35,220,200))
        self.assertGreater(later[:,:,3].sum(),early[:,:,3].sum())
        self.assertEqual(later[110:,:,3].max(),0)
        self.assertTrue(np.any(pixels(render(d,1,220,200))[110:,:,3]))
        lifts=[p for p in np.linspace(.4,.6,1001) if not drawing_state(d,p).painting]
        self.assertGreater(len(lifts),2)
        np.testing.assert_array_equal(pixels(render(d,lifts[0],220,200)),
                                      pixels(render(d,lifts[-1],220,200)))
        d.drawing_visibility='full'
        self.assertGreater(pixels(render(d,0,220,200))[:,:,3].sum(),0)

    def test_retirement_is_single_ordered_and_gated(self):
        d,_=fixture()
        for progress in np.linspace(0,1,101):
            states=retirement_states(d,progress)
            self.assertLessEqual(sum(s=='retiring' for s,_ in states),1)
            erased=[e for _,e in states]
            self.assertEqual(erased,sorted(erased,reverse=True))
            if progress<=.7:self.assertTrue(all(e==0 for e in erased))
        self.assertTrue(all(s=='removed' for s,_ in retirement_states(d,.98)))
        d.strokes.reverse()
        self.assertEqual(remaining_contours(d,.701).strokes[0].name,'microphone')

    def test_forward_reverse_and_scrub_determinism(self):
        d,im=fixture();d.contour_transition='retire'
        forward=frame(d,im,.75)
        d.retirement_direction='reverse'
        reverse=frame(d,im,.75)
        self.assertFalse(np.array_equal(pixels(forward),pixels(reverse)))
        frame(d,im,.99);frame(d,im,.02)
        np.testing.assert_array_equal(pixels(reverse),pixels(frame(d,im,.75)))

    def test_paint_erases_by_coverage_not_source_alpha(self):
        d,im=fixture();d.contour_transition='paint'
        mask=QImage(320,240,QImage.Format.Format_ARGB32_Premultiplied)
        mask.fill(Qt.GlobalColor.white)
        with patch('adaptive_hand.adaptive_paint_mask',return_value=(mask,None)):
            np.testing.assert_array_equal(pixels(frame(d,im,.2)),
                                          pixels(source_frame(d,im,320,240)))

    def test_final_exact_color_alpha_and_no_last_frame_pop(self):
        d,im=fixture()
        expected=pixels(source_frame(d,im,320,240))
        self.assertTrue(np.any((expected[:,:,3]>0)&(expected[:,:,3]<255)))
        for mode in ('paint','retire'):
            d.contour_transition=mode
            for progress in (.98,.99,1):
                np.testing.assert_array_equal(pixels(frame(d,im,progress)),expected)
            self.assertEqual(pixels(frame(d,im,.5))[0,0,3],0)

    def test_preview_export_and_setting_snapshot(self):
        d,im=fixture();d.contour_transition='retire';d.retirement_direction='reverse'
        snapshot=copy.deepcopy(d)
        d.retirement_direction='forward'
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'frames'
            count=export_frames(snapshot,folder,duration=1,fps=6,width=320,height=240,
                                final_image=im,fade_duration=1,hold_duration=0,
                                reveal_mode='adaptive')
            for i in range(count):
                preview=render_color_timeline(snapshot,i/(count-1),320,240,1,1,0,im,
                                              reveal_mode='adaptive')
                np.testing.assert_array_equal(pixels(QImage(str(folder/f'frame_{i:06d}.png'))),
                                              pixels(preview))

    def test_legacy_dispatch_and_svg_isolation(self):
        d,im=fixture()
        for mode in ('fade','brush','guided','clean','adaptive'):
            original=render_color_timeline(d,.7,320,240,1,1,0,im,reveal_mode=mode)
            d.contour_transition='legacy'
            explicit=render_color_timeline(d,.7,320,240,1,1,0,im,reveal_mode=mode)
            np.testing.assert_array_equal(pixels(original),pixels(explicit))
        del d.source_kind
        a=frame(d,im,.5)
        d.contour_transition='retire'
        np.testing.assert_array_equal(pixels(a),pixels(frame(d,im,.5)))

    def test_hand_uses_mask_tip_and_hides_for_cleanup(self):
        d,im=fixture();d.contour_transition='paint'
        hand=QImage(10,10,QImage.Format.Format_ARGB32);hand.fill(Qt.GlobalColor.magenta)
        mask=QImage(320,240,QImage.Format.Format_ARGB32);mask.fill(Qt.GlobalColor.transparent)
        with patch('adaptive_hand.adaptive_paint_mask',return_value=(mask,(12.,16.))):
            with patch('color_reveal.draw_hand') as draw:
                frame(d,im,.2,painting_hand=hand)
                self.assertEqual(draw.call_args.args[1],(12.,16.))
            with patch('color_reveal.draw_hand') as draw:
                frame(d,im,.8,painting_hand=hand)
                self.assertIsNone(draw.call_args.args[1])

    def test_image_controls_and_empty_initial_canvas(self):
        from app import Window
        w=Window()
        try:
            d,_=fixture()
            w.source_type.setCurrentIndex(1)
            w.set_drawing(d)
            self.assertEqual(w.position,0)
            self.assertEqual(w.contour_transition.currentIndex(),0)
            self.assertEqual(pixels(w.canvas.frame)[:,:,3].max(),0)
            w.contour_transition.setCurrentIndex(2)
            w.retirement_direction.setCurrentIndex(1)
            w.options()
            self.assertEqual(d.contour_transition,'retire')
            self.assertEqual(d.retirement_direction,'reverse')
            w.drawing_visibility.setCurrentIndex(1)
            self.assertGreater(pixels(w.canvas.frame)[:,:,3].sum(),0)
        finally:
            w.close()

if __name__=='__main__':
    unittest.main()
