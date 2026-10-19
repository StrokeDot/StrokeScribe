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

    def _commit_source(self,values,settings=None):
        self.commit_history()
        self.playing=False
        for name,value in values.items():setattr(self,name,value)
        if settings:
            from projects import set_widget_value
            for name,value in settings.items():
                widget=getattr(self,name)
                widget.blockSignals(True);set_widget_value(widget,value);widget.blockSignals(False)
        self._source_snapshot_key=None
        self.scenes[self.scene_index]['thumb']=None
        self._base_cache.clear()
        self.clear_frames()
        self.fill_order()
        self.update_source_labels()
        self.commit_history()
        self.project_changes.mark_changed()
        self.sync_workspace();self.fill_scenes();self.refresh()
        return True

    def replace_paint_source(self,path,settings=None):
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
        changes=dict(settings or {})
        if not self.is_image_artwork():changes['use_color']=True
        result=self._commit_source(values,changes)
        self.status.setText('Painting source changed. Existing drawing paths and placement were kept.')
        return result

    def replace_drawing_source(self,path,reconstruct=False,settings=None):
        if self._artwork_busy() or not self.drawing:return False
        if not path and not reconstruct:return False
        try:
            if reconstruct and getattr(self.drawing,'drawing_source_kind',None)=='svg':
                from engine import import_svg
                import tempfile
                # Validated native source is already retained by the project serializer.
                with tempfile.TemporaryDirectory() as folder:
                    saved=Path(folder)/'drawing.svg'
                    saved.write_text(self.drawing.svg_source,encoding='utf-8')
                    drawing=import_svg(saved)
                return self._apply_drawing_source(drawing,None,settings,
                        getattr(self.drawing,'drawing_source_name','Drawing.svg'),'svg')
            if path and Path(path).suffix.lower()=='.svg':
                from engine import import_svg
                drawing=import_svg(path)
                return self._apply_drawing_source(drawing,None,settings,Path(path).name,'svg')
            from artwork_assets import capture_assets,materialize_assets
            old=self.image_result if self.is_image_artwork() else None
            source=self.image_path if old else None
            if reconstruct:
                guide=self.image_guide if old else None
                if not source:
                    raise ValueError('Choose an SVG or line-art image to reconstruct this drawing.')
                metadata=copy.deepcopy(self.drawing.artwork_assets)
            else:
                metadata=capture_assets(source or path,path if source else None)
            managed,guide=materialize_assets(metadata)
            ctx=dict(source_edit=True,generation=getattr(self,'_artwork_generation',0),
                     target=self.scenes[self.scene_index],drawing=self.drawing,
                     strokes=tuple(self.drawing.strokes),source=managed,guide=guide,assets=metadata,
                     name=Path(path).name if path else getattr(self.drawing,'drawing_source_name','Reconstructed drawing'),
                     settings=settings,cancelled=False,committed=False)
            self._pending_artwork=ctx
            self.build_image(managed,line_guide=guide,intake=ctx)
            return True
        except Exception as exc:
            self._pending_artwork=None
            QMessageBox.warning(self,'Cannot change drawing source',str(exc))
            return False

    def accept_drawing_source(self,result,ctx):
        unchanged=(ctx['drawing'] is self.drawing and len(ctx['strokes'])==len(self.drawing.strokes)
                   and all(a is b for a,b in zip(ctx['strokes'],self.drawing.strokes)))
        if (ctx.get('cancelled') or not unchanged or ctx['generation']!=getattr(self,'_artwork_generation',0)
                or ctx['target'] is not self.scenes[self.scene_index]):
            self.status.setText('Drawing source was not applied because the editing target changed.')
            return False
        metadata=ctx['assets']
        if hasattr(result.drawing,'source_frame'):metadata['frame']=result.drawing.source_frame
        committed=self._apply_drawing_source(result.drawing,metadata,ctx.get('settings'),ctx['name'],'raster')
        ctx['committed']=committed
        return committed

    def _apply_drawing_source(self,drawing,metadata,settings,name,kind):
        from image_reconstruct import Reconstruction
        from artwork_assets import materialize_assets
        drawing.drawing_source_name=name
        drawing.drawing_source_kind=kind
        values=dict(drawing=drawing)
        old=self.image_result if self.is_image_artwork() else None
        if metadata is None:
            metadata=copy.deepcopy(getattr(self.drawing,'artwork_assets',None))
            if metadata:metadata['guide']=None
        if metadata:drawing.artwork_assets=metadata
        if old:
            drawing.source_kind='image'
            drawing.image_regions=old.regions
            values.update(image_result=Reconstruction(drawing,old.image,old.regions,old.mode,old.detail,old.filename),
                          image_guide=materialize_assets(metadata)[1] if metadata else None)
        else:
            # A line-art image is a drawing source, not an implicit new paint source.
            drawing.source_kind='svg'
            if self.final_image is not None:values['color_path']=self.color_path or 'from-project'
        result=self._commit_source(values,settings)
        self.status.setText('Drawing source changed. Original colors, timing and hand settings were retained.')
        return result

    def edit_stage_source(self,stage,index):
        if stage not in ('draw','paint') or self._artwork_busy() or not 0<=index<len(self.scenes):return
        if index!=self.scene_index:
            self.select_scene(index)
            if index!=self.scene_index:return
        self.playing=False
        from source_editor import SourceEditor
        SourceEditor(self,stage).exec()
