"""End-to-end drawing, paint and original appearance acceptance (no AI service)."""
import copy,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtGui import QImage
from test_artwork_workflow import WorkflowFixture
from test_artwork_pairing import pair
from frame_render import compose_frame,timeline_seconds
from image_painting import original_frame
from engine import export_frames

def rgba(image):
    q=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(bytes(q.constBits()),np.uint8).reshape(q.height(),q.bytesPerLine())[:,:q.width()*4].reshape(q.height(),q.width(),4)

def render_options(window):
    o=window.options()
    o.update(width=320,height=180,duration=1.,fade_duration=1.,hold_duration=.2,
             hand=None,painting_hand=None,brush_width=.2,stroke_spacing=.55,
             layers='art',erase=None,workers=1,camera_zoom=1.)
    return o

def frame(d,o,f):
    return compose_frame(d,f,{k:v for k,v in o.items() if k not in ('fps','audio','workers')})

class RenderWorkflowTests(WorkflowFixture):
    def test_all_raster_entry_points_draw_then_paint_original_and_export_identically(self):
        import library,artwork_assets
        from scenes import job_from_state
        original,guide=pair(self.tmp.name)
        lib=library.Library();item=lib.add('images',guide)
        lib.set_artwork(item,artwork_assets.capture_assets(original,guide))
        self.w.image_detail.setCurrentText('Low')
        for route in ('image','ai-lineart','library'):
            with self.subTest(route=route):
                if route=='image':
                    self.assertTrue(self.w.request_artwork(str(original),placement='add'))
                elif route=='ai-lineart':
                    self.w.use_ai_result('lineart',str(guide),str(original),placement='add')
                else:
                    self.w.use_library_item('images',item,placement='add')
                self.wait_import()
                d=self.w.drawing;o=render_options(self.w)
                self.assertIsNotNone(o['final_image'])
                self.assertEqual(self.w.image_animation.currentText(),'Draw, then Paint')
                empty=rgba(frame(d,o,0))
                self.assertEqual(int(empty[:,:,3].max()),0)
                drawing=rgba(frame(d,o,.5/2.2))
                self.assertGreater(np.count_nonzero(drawing[:,:,3]),0)
                final=frame(d,o,1)
                expected=original_frame(d,o['final_image'],320,180)
                np.testing.assert_array_equal(rgba(final),rgba(expected))
                target=rgba(expected)
                colored=(target[:,:,3]>240)&(target[:,:,0]>150)&(target[:,:,1]<120)
                self.assertGreater(int(colored.sum()),100)
                counts=[]
                for p in (.25,.5,.75,1.):
                    actual=rgba(frame(d,o,(1+p)/2.2))
                    close=np.max(np.abs(actual.astype(int)-target.astype(int)),axis=2)<=2
                    counts.append(int((close&colored).sum()))
                self.assertEqual(counts,sorted(counts))
                self.assertGreater(counts[-1],counts[0])
                self.assertEqual(counts[-1],int(colored.sum()))
                self.assertEqual(int(target[0,0,3]),0)
                # Actual project reconstruction, not a copied QImage reference.
                state=self.w.scene_state()
                restored,restored_o,_=job_from_state(state)
                restored_o.update({k:v for k,v in o.items() if k!='final_image'})
                np.testing.assert_array_equal(rgba(frame(restored,restored_o,1)),target)
                if route=='ai-lineart':
                    folder=Path(self.tmp.name)/'exported'
                    eo={k:v for k,v in o.items() if k not in ('audio','workers','layers','erase','camera_zoom','offset','entrance','pause','sound_files','overlays')}
                    eo.update(fps=12)
                    export_frames(d,folder,**eo)
                    files=sorted(folder.glob('frame_*.png'))
                    self.assertGreater(len(files),2)
                    for i in (0,len(files)//3,len(files)*2//3,len(files)-1):
                        np.testing.assert_array_equal(rgba(QImage(str(files[i]))),
                                                      rgba(frame(d,o,i/(len(files)-1))))

    def test_native_svg_fill_survives_window_project_restore_and_has_exact_final_hole(self):
        from projects import drawing_to_dict
        self.svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><path fill="black" fill-rule="evenodd" d="M10 10H190V90H10Z M80 35H120V65H80Z"/></svg>')
        self.assertTrue(self.w.request_artwork(str(self.svg),kind='svg',placement='add'))
        self.assertTrue(self.w.use_color.isChecked())
        vectors=drawing_to_dict(self.w.drawing)['strokes']
        state=self.w.scene_state()
        self.assertIsNone(state['color_png'],'Native SVG keeps source, not a raster substitution')
        self.w.apply_scene_state(state)
        self.assertTrue(self.w.use_color.isChecked())
        self.assertEqual(drawing_to_dict(self.w.drawing)['strokes'],vectors)
        o=render_options(self.w);o['reveal_mode']='brush'
        final=frame(self.w.drawing,o,1)
        expected=original_frame(self.w.drawing,o['final_image'],320,180)
        np.testing.assert_array_equal(rgba(final),rgba(expected))
        self.assertEqual(final.pixelColor(160,90).alpha(),0)
        self.assertEqual(final.pixelColor(70,90).name(),'#000000')
        self.assertGreater(final.pixelColor(70,90).alpha(),250)
        # The explicit SVG reveal checkbox remains a drawing-only choice.
        self.w.use_color.setChecked(False)
        self.assertIsNone(self.w.options()['final_image'])

if __name__=='__main__':unittest.main()
