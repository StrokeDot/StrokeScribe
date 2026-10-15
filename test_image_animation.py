"""Regression for the two continuous image animations and independent hand size.

These tests render real (small) Qt frames and the original adaptive paint plan.
No actual local Ollama model is required.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from app import Window
from color_reveal import render_color_timeline, draw_hand
from contour_transition import source_frame
from engine import render, scale_animation_frame, export_frames
from image_painting import paint_frame
from test_contour_transitions import fixture, pixels

APP=QApplication.instance() or QApplication([])


class ImageAnimationTests(unittest.TestCase):
    def test_modes_are_two_not_a_three_stage_cleanup(self):
        drawing,image=fixture()
        baseline=source_frame(drawing,image,320,240)
        original=pixels(baseline)
        for mode in ('draw_paint','paint_only'):
            drawing.image_animation=mode
            options=dict(width=320,height=240,duration=1,
                         fade_duration=2,hold_duration=0,
                         final_image=image,reveal_mode='adaptive')
            start=render_color_timeline(drawing,0,**options)
            if mode=='paint_only':
                self.assertEqual(pixels(start)[:,:,3].max(),0)
            else:
                self.assertEqual(pixels(start)[:,:,3].max(),0)
                drawing_stage=render_color_timeline(drawing,.2,**options)
                self.assertGreater(pixels(drawing_stage)[:,:,3].sum(),0)
                np.testing.assert_array_equal(
                    pixels(render_color_timeline(drawing,1/3,**options)),
                    pixels(render(drawing,1,320,240)))
            for position in (.98,.99,1.):
                frac=position if mode=='paint_only' else (1+2*position)/3
                np.testing.assert_array_equal(
                    pixels(render_color_timeline(drawing,frac,**options)),original)

    def test_paint_only_is_never_overlaid_with_black_tracing(self):
        drawing,image=fixture()
        drawing.image_animation='paint_only'
        for progress in (.1,.45,.75):
            frame=paint_frame(drawing,image,320,240,progress,1,.14,.55,
                              None,.2,(.1,.1),False)
            # Paint-only never produces pixels outside original art's
            # support; the line geometry may exceed those boundaries.
            source=pixels(source_frame(drawing,image,320,240))
            actual=pixels(frame)
            self.assertFalse(np.any((actual[:,:,3]>0)&(source[:,:,3]==0)))
            self.assertTrue(np.any(actual[:,:,3]>0))
        self.assertEqual(pixels(paint_frame(drawing,image,320,240,0,1,.14,.55,
                                           None,.2,(.1,.1),False))[:,:,3].max(),0)

    def test_draw_then_paint_erases_ink_during_painting_not_after(self):
        drawing,image=fixture()
        drawing.image_animation='draw_paint'
        blank=pixels(render(drawing,1,320,240))
        early=pixels(paint_frame(drawing,image,320,240,.08,1,.14,.55,
                                 None,.2,(.1,.1),True))
        midway=pixels(paint_frame(drawing,image,320,240,.6,1,.14,.55,
                                  None,.2,(.1,.1),True))
        result=pixels(source_frame(drawing,image,320,240))
        self.assertFalse(np.array_equal(early,blank))
        self.assertFalse(np.array_equal(midway,early))
        self.assertFalse(np.array_equal(midway,result))
        np.testing.assert_array_equal(
            pixels(paint_frame(drawing,image,320,240,.98,1,.14,.55,
                               None,.2,(.1,.1),True)),result)

    def test_hand_does_not_resize_when_artwork_zoom_changes(self):
        hand=QImage(30,20,QImage.Format.Format_ARGB32)
        hand.fill(Qt.GlobalColor.magenta)
        output_width=600
        for zoom in (.75,1.,1.5):
            frame=QImage(output_width,450,QImage.Format.Format_ARGB32_Premultiplied)
            frame.fill(Qt.GlobalColor.transparent)
            p=QPainter(frame)
            # The hand is rendered at inverse scale before artwork transform.
            draw_hand(p,(300,225),hand,output_width,.16/zoom,(.3,.4))
            p.end()
            frame=scale_animation_frame(frame,zoom)
            rgba=pixels(frame)
            hot=(rgba[:,:,0]>200)&(rgba[:,:,2]>200)&(rgba[:,:,3]>190)
            xs=np.where(hot)[1]
            self.assertGreater(len(xs),200)
            self.assertTrue(90<=np.max(xs)-np.min(xs)+1<=98,
                            f'Zoom {zoom} changed the physical hand size.')

    def test_preview_and_export_use_same_mode_and_hand_scale(self):
        d,image=fixture()
        hand=QImage(12,12,QImage.Format.Format_ARGB32)
        hand.fill(Qt.GlobalColor.magenta)
        options=dict(width=220,height=165,duration=1,fade_duration=1,
                     hold_duration=0,final_image=image,reveal_mode='adaptive',
                     painting_hand=hand,hand_scale=.15,artwork_scale=1.3)
        d.image_animation='paint_only'
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'out'
            count=export_frames(d,folder,fps=6,**options)
            for i in range(count):
                f=i/(count-1)
                preview=render_color_timeline(d,f,width=220,height=165,
                         duration=1,fade_duration=1,hold_duration=0,
                         final_image=image,reveal_mode='adaptive',
                         painting_hand=hand,hand_scale=.15/1.3)
                preview=scale_animation_frame(preview,1.3)
                np.testing.assert_array_equal(pixels(preview),
                    pixels(QImage(str(folder/f'frame_{i:06d}.png'))))
            self.assertGreater(count,2)

    def test_brush_control_is_debounced_and_render_errors_do_not_escape(self):
        d,image=fixture()
        w=Window()
        try:
            w.source_type.setCurrentIndex(1)
            from image_reconstruct import Reconstruction
            w.image_result=Reconstruction(d,image,None,'ai_redraw','medium','test.png')
            w.set_drawing(d)
            w.position=.7
            w.image_animation.setCurrentIndex(1)
            self.assertFalse(w.duration.isEnabled())
            self.assertTrue(w.preserve_colors.isChecked())
            self.assertFalse(w.preserve_colors.isEnabled())
            w.brush_width.setValue(.18)
            self.assertTrue(w.brush_preview_timer.isActive(),
                            'Brush change should defer expensive preview rebuild')
            w.brush_preview_timer.stop()
            with patch('image_painting.paint_frame',side_effect=RuntimeError(
                    'controlled preview failure')):
                w.refresh()
            self.assertIn('controlled preview failure',w.status.text())
            w.image_animation.setCurrentIndex(0)
            self.assertTrue(w.duration.isEnabled())
        finally:
            w.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
