"""Draw/Paint source routing follows the visible clip, never the selected import mode."""
import copy
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtWidgets import QSlider,QApplication
from PySide6.QtTest import QTest,QSignalSpy
from studio_workspace import StageTimeline
from test_artwork_workflow import WorkflowFixture,APP
from test_artwork_pairing import pair

class SourceTimelineTests(WorkflowFixture):
    def test_single_scope_uses_selected_scene_not_zero(self):
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        self.w.preview_scope.setCurrentIndex(0);self.w.refresh()
        self.assertEqual(self.w.stage_timeline.current_scene,1)
    def test_stage_hit_uses_draw_paint_rectangles_and_skips_join(self):
        t=StageTimeline(QSlider());t.resize(900,140)
        self.assertTrue(callable(getattr(t,'source_at',None)),'Stage source hit testing missing')
        t.update_state(2,3,1,0)
        t.set_scenes(None,current=4)
        y=t._rows()[1].center().y()
        self.assertEqual(t.source_at(QPointF(t._x(1),y)),('draw',4))
        self.assertEqual(t.source_at(QPointF(t._x(3),y)),('paint',4))
        self.assertIsNone(t.source_at(QPointF(t._x(5.5),y)))
        t.set_scenes([('One',6,'scene',[('draw',2),('paint',3),('hold',1)]),
                      ('Move',1,'join',[]),('Two',4,'scene',[('draw',3),('paint',1)])],current=1)
        self.assertEqual(t.source_at(QPointF(t._x(1),y)),('draw',0))
        self.assertEqual(t.source_at(QPointF(t._x(4),y)),('paint',0))
        self.assertIsNone(t.source_at(QPointF(t._x(6.5),y)))
        self.assertEqual(t.source_at(QPointF(t._x(8),y)),('draw',1))
        self.assertEqual(t.source_at(QPointF(t._x(10.5),y)),('paint',1))
        self.assertIsNone(t.source_at(QPointF(t._x(2),5)))
        t.deleteLater()
    def test_double_click_one_edit_click_scrubs_and_locked_blocks(self):
        t=StageTimeline(QSlider());t.resize(900,140);t.update_state(2,3,1,0);t.set_scenes(None,2);t.show()
        self.assertTrue(hasattr(t,'stage_source_edit'),'Stage source signal missing')
        spy=QSignalSpy(t.stage_source_edit);edge=QSignalSpy(t.stage_dragged)
        p=QPoint(round(t._x(3)),round(t._rows()[1].center().y()))
        QTest.mouseClick(t,Qt.MouseButton.LeftButton,pos=p)
        self.assertEqual(spy.count(),0)
        QTest.mouseDClick(t,Qt.MouseButton.LeftButton,pos=p)
        self.assertEqual(spy.count(),1);self.assertEqual(spy.at(0),['paint',2]);self.assertEqual(edge.count(),0)
        t.locked=True;QTest.mouseDClick(t,Qt.MouseButton.LeftButton,pos=p)
        self.assertEqual(spy.count(),1)
        t.close();t.deleteLater()
    def test_keyboard_source_actions_exist_even_without_paint_duration(self):
        t=self.w.stage_timeline
        self.assertTrue(hasattr(t,'stage_source_edit'),'Stage source signal missing')
        spy=QSignalSpy(t.stage_source_edit)
        t.set_scenes(None,0);t.update_state(4,0,0,0)
        with patch('source_editor.SourceEditor.exec',return_value=0):
            QTest.keyClick(t,Qt.Key.Key_P,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(spy.count(),1);self.assertEqual(spy.at(0),['paint',0])
    def test_cancel_editor_keeps_project_and_history(self):
        self.assertTrue(callable(getattr(self.w,'edit_stage_source',None)),'Source editor missing')
        before=self.w.project_state();history=self.w.history.current
        with patch('source_editor.SourceEditor.exec',return_value=0):
            self.w.edit_stage_source('draw',0)
        self.assertEqual(self.w.project_state(),before);self.assertIs(self.w.history.current,history)

class DrawingSourceTests(WorkflowFixture):
    def setup_image(self):
        original,guide=pair(self.tmp.name)
        self.w.image_detail.setCurrentText('Low')
        self.w.request_artwork(str(guide),kind='lineart',original=str(original),placement='add');self.wait_import()
        self.assertTrue(callable(getattr(self.w,'replace_drawing_source',None)),'Drawing source replacement missing')
        return original,guide
    def test_drawing_replacement_keeps_shared_bounds_and_final_paint_placement(self):
        self.setup_image()
        from test_artwork_rendering import frame,render_options,rgba
        import numpy as np
        old_bounds=self.w.drawing.bounds;o=render_options(self.w)
        before=rgba(frame(self.w.drawing,o,1))
        self.w.replace_drawing_source(str(self.svg))
        self.assertEqual(self.w.drawing.bounds,old_bounds)
        np.testing.assert_array_equal(rgba(frame(self.w.drawing,render_options(self.w),1)),before)
    def test_initial_svg_can_reconstruct_retained_native_source(self):
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        self.assertTrue(self.w.replace_drawing_source(None,reconstruct=True))
    def test_svg_element_raster_guide_can_reconstruct_after_external_deletion(self):
        original,guide=pair(self.tmp.name)
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        self.w.replace_drawing_source(str(guide));self.wait_import()
        state=self.w.scene_state();original.unlink();guide.unlink()
        self.w.apply_scene_state(state)
        self.assertFalse(self.w.is_image_artwork())
        self.assertTrue(self.w.replace_drawing_source(None,reconstruct=True));self.wait_import()
        self.assertFalse(self.w.is_image_artwork())
    def test_svg_drawing_replacement_keeps_original_pixels_settings_and_undo(self):
        self.setup_image()
        pixels=self.w.image_result.image.copy();old=tuple(self.w.drawing.strokes);path=self.w.image_path
        self.w.duration.setValue(6);settings=self.w.settings_state()
        self.assertTrue(self.w.replace_drawing_source(str(self.svg)))
        self.assertNotEqual(tuple(self.w.drawing.strokes),old)
        self.assertTrue(self.w.is_image_artwork())
        self.assertEqual(self.w.image_path,path);self.assertEqual(self.w.image_result.image,pixels)
        self.assertEqual(self.w.settings_state(),settings)
        self.w.undo();self.assertEqual(tuple(self.w.drawing.strokes),old)
        self.w.redo();self.assertEqual(self.w.image_result.image,pixels)
    def test_raster_drawing_replacement_and_reopen_preserves_pair(self):
        original,guide=self.setup_image();before=self.w.image_result.image.copy()
        self.assertTrue(self.w.replace_drawing_source(str(guide)));self.wait_import()
        self.assertEqual(self.w.image_result.image,before)
        self.assertEqual(self.w.drawing.artwork_assets['original']['extension'],'.png')
        from projects import save,load
        path=save(Path(self.tmp.name)/'drawing-source',self.w.project_state())
        original.unlink();guide.unlink();self.w.apply_project(load(path))
        self.assertEqual(self.w.image_result.image,before);self.assertTrue(Path(self.w.image_guide).is_file())
    def test_cancel_async_drawing_reconstruction_is_atomic(self):
        original,guide=self.setup_image();before=self.w.project_state()
        self.w.replace_drawing_source(str(guide))
        self.w.cancel_artwork_import();self.wait_import()
        self.assertEqual(self.w.project_state(),before)
    def test_native_svg_guide_survives_reopen_and_can_rerun(self):
        self.setup_image();self.w.replace_drawing_source(str(self.svg))
        before=self.w.image_result.image.copy()
        self.w.apply_scene_state(self.w.scene_state())
        self.assertEqual(self.w.drawing.drawing_source_kind,'svg')
        self.assertTrue(self.w.replace_drawing_source(None,reconstruct=True))
        self.assertEqual(self.w.image_result.image,before)
        self.assertTrue(self.w.is_image_artwork())
    def test_svg_raster_drawing_guide_is_independent_of_later_paint_replacement(self):
        original,guide=pair(self.tmp.name)
        self.w.request_artwork(str(self.svg),kind='svg',placement='add')
        self.w.replace_drawing_source(str(guide));self.wait_import()
        saved_guide=self.w.drawing.artwork_assets.get('guide')
        self.assertIsNotNone(saved_guide)
        self.w.replace_paint_source(str(original))
        self.assertEqual(self.w.drawing.artwork_assets['guide'],saved_guide)
        self.assertTrue(self.w.replace_drawing_source(None,reconstruct=True));self.wait_import()
        self.assertEqual(self.w.drawing.artwork_assets['guide'],saved_guide)
    def test_invalid_drawing_and_cancel_keep_source(self):
        self.setup_image();before=self.w.project_state()
        self.assertFalse(self.w.replace_drawing_source(None))
        self.svg.write_text('not svg')
        with patch('PySide6.QtWidgets.QMessageBox.warning'):
            self.assertFalse(self.w.replace_drawing_source(str(self.svg)))
        self.assertEqual(self.w.project_state(),before)

if __name__=='__main__':
    import unittest
    unittest.main()
