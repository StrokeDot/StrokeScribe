"""Source-only edits: immutable asset contexts, shared by inspector and timeline."""
from __future__ import annotations
import copy
from dataclasses import dataclass
from pathlib import Path
from PySide6.QtWidgets import QFileDialog,QMessageBox

@dataclass(frozen=True,eq=False)
class SourceSnapshot:
    values: tuple
    def __deepcopy__(self,memo):
        # Drawings/strokes and Qt images are retained, never edited in place here.
        return self

class SourceEditing:
    SOURCE_FIELDS=('drawing','image_result','image_path','image_guide','color_path','color_original','final_image')
    def source_snapshot(self):
        values=tuple(getattr(self,k,None) for k in self.SOURCE_FIELDS)
        key=tuple(v.cacheKey() if hasattr(v,'cacheKey') else v if isinstance(v,(str,type(None))) else id(v) for v in values)
        if getattr(self,'_source_snapshot_key',None)!=key:
            self._source_snapshot_key=key
            self._source_snapshot=SourceSnapshot(values)
        return self._source_snapshot

    def restore_source_snapshot(self,snapshot):
        if snapshot is None:return
        for name,value in zip(self.SOURCE_FIELDS,snapshot.values):setattr(self,name,value)
        # Reuse the same record so ordinary edits compare in constant space.
        self._source_snapshot_key=None
        self.source_snapshot()
        self._source_snapshot=snapshot
        self.update_source_labels()

    def update_source_labels(self):
        image=self.is_image_artwork()
        self.load_color_button.setText('Change original image…' if image else 'Change matching colors…')
        if image and self.image_result:
            self.color_note.setText(self.image_result.filename+' • original colors')
        elif self.color_path:
            self.color_note.setText(getattr(self.drawing,'paint_source_name','Matching colors')+' • matching colors')
        elif getattr(self.drawing,'svg_has_fill',False):
            self.color_note.setText('Original SVG appearance • native fills')
        else:self.color_note.setText('No matching color image loaded')

    def _commit_source(self,values):
        self.commit_history()
        self.playing=False
        for name,value in values.items():setattr(self,name,value)
        self._source_snapshot_key=None
        self.scenes[self.scene_index]['thumb']=None
        self._scene_base_cache=None
        self.clear_frames()
        self.fill_order()
        self.update_source_labels()
        self.commit_history()
        self.project_changes.mark_changed()
        self.sync_workspace();self.refresh()
        return True

    def replace_paint_source(self,path):
        if not path:return False
        if self._artwork_busy() or not self.drawing:
            self.status.setText('Finish the current import/export before changing a source.')
            return False
        try:
            from artwork_assets import capture_assets,materialize_assets
            from image_reconstruct import load_raster,Reconstruction
            from adaptive_hand import qimage
            from image_regions import segment_regions
            metadata=capture_assets(path)
            previous=getattr(self.drawing,'artwork_assets',None)
            if previous:
                metadata['guide']=copy.deepcopy(previous.get('guide'))
                if previous.get('frame'):metadata['frame']=copy.deepcopy(previous['frame'])
            source,guide=materialize_assets(metadata)
            original=load_raster(source)
            image=qimage(original)
            drawing=copy.copy(self.drawing)
            drawing.strokes=list(self.drawing.strokes)
            drawing.artwork_assets=metadata
            drawing.paint_source_name=Path(path).name
            values=dict(drawing=drawing)
            if self.is_image_artwork():
                old=self.image_result
                regions=segment_regions(original,'high' if old.detail=='max' else old.detail)
                drawing.image_regions=regions
                values.update(image_result=Reconstruction(drawing,image,regions,old.mode,old.detail,Path(path).name),
                              image_path=source,image_guide=guide)
            else:
                from color_reveal import clean_qimage
                values.update(color_path=source,color_original=image,
                              final_image=clean_qimage(image) if self.clean_color.isChecked() else image)
        except Exception as exc:
            QMessageBox.warning(self,'Cannot change painting source',str(exc))
            return False
        # Preparation above has no effect on the selected element or history.
        enabled=self.use_color.isChecked()
        result=self._commit_source(values)
        if not self.is_image_artwork() and not enabled:
            self.use_color.setChecked(True);self.commit_history()
        self.status.setText('Painting source changed. Existing drawing paths and placement were kept.')
        return result
