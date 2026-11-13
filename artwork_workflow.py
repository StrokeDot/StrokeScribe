"""Transactional artwork placement, shared by file, Library and AI intake."""
from __future__ import annotations
import copy
from pathlib import Path
from PySide6.QtWidgets import QFileDialog,QInputDialog,QMessageBox
from toast import notify
from PySide6.QtCore import Qt
LABELS={'Add to current project':'add','Replace selected artwork':'replace','New Project':'new'}

class ArtworkWorkflow:
    def is_image_artwork(self):
        return getattr(self.drawing,'source_kind',None)=='image'

    def element_kind(self):
        """'lettering', 'svg' or 'image' for the element being edited (UI state only)."""
        from element_kinds import kind_of_drawing
        return kind_of_drawing(self.drawing)

    def follow_selection_panels(self):
        """exp.241 (UI clean-up step 5): an open side panel shows the selected element.

        A picture or SVG chosen while the Text panel is open: the Text panel (which has
        nothing for it) closes, and the Image panel opens if the right side was closed. Lettering chosen while the
        Image panel is open: the Text panel opens beside it. Closed panels stay closed and
        the other side panels (Sound, Music, Camera, AI, Animation, Hand, Export) stay
        as they are."""
        layout=getattr(self,'sidebar_layout',None)
        if layout is None or self.drawing is None or not hasattr(self,'left_tabs'):
            return
        try:
            from element_kinds import LETTERING
            from studio_workspace import LEFT,TABS
            kind=self.element_kind()
            left_open=bool(layout.expanded.get('source'))
            right_open=bool(layout.expanded.get('inspector'))
            on_text=left_open and self.left_tabs.currentIndex()==LEFT['text']
            on_image=right_open and self.inspector_tabs.currentIndex()==TABS['source']
            if kind!=LETTERING and on_text:
                layout.set_expanded('source',False)
                if not right_open:          # an open right panel (Animation, Hand…) stays on its page
                    self.show_right_panel('source')
            elif kind==LETTERING and on_image and not left_open:
                self.show_left_panel('text')
        except Exception as exc:
            import applog; applog.error('Panels follow the selection',exc)

    def update_element_panels(self):
        """Show what belongs to the selected element's kind in Source and Handwriting.

        Lettering: Placement (size, position) in Handwriting; Source shows a
        handwriting card with no thumbnail and no file name. Imported SVG /
        image: thumbnail, its real name, Transform and Appearance in Source.
        Only visibility and placement of existing controls change here.
        """
        if not hasattr(self,'source_card') or not hasattr(self,'placement_box'):
            return
        from element_kinds import IMAGE,LETTERING,SVG,source_card
        kind=self.element_kind() if self.drawing is not None else None
        lettering=kind==LETTERING
        imported=kind in (SVG,IMAGE)
        # One size/position group, two homes; never shown twice.
        target=self.handwriting_placement_slot if lettering else self.source_transform_slot
        if target.indexOf(self.placement_box)<0:
            for slot in (self.handwriting_placement_slot,self.source_transform_slot):
                slot.removeWidget(self.placement_box)
            target.addWidget(self.placement_box)
        self.placement_box.setVisible(kind is not None)
        # Text panel stacks its fields (label above); Image lines them up beside.
        from PySide6.QtWidgets import QFormLayout
        self.placement_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows if lettering
                                             else QFormLayout.RowWrapPolicy.DontWrapRows)
        self.handwriting_placement_heading.setVisible(lettering)
        self.source_transform_heading.setVisible(imported)
        # The element card.
        self.source_card.setVisible(True)
        if lettering:
            heading,detail=source_card(LETTERING,text=self.text.toPlainText())
        elif kind==IMAGE and getattr(self,'image_result',None) is not None:
            k=getattr(self,'scene_index',-1)
            name=self.scene_label(k) if 0<=k<len(getattr(self,'scenes',[])) and hasattr(self,'scene_label') else ''
            heading,detail=source_card(IMAGE,filename=self.image_result.filename,title=name)
        elif imported:
            heading,detail=source_card(kind,title=getattr(self,'project_title',''))
        else:
            heading,detail='No image loaded','Import an SVG or PNG image to use as the drawing source.'
        self.source_card_title.setText(heading)
        self.source_card_detail.setText(detail)
        self.edit_handwriting_button.setVisible(lettering)
        self.source_card_thumb.setVisible(not lettering)
        self.source_card_thumb.clear()
        if not imported and not lettering:
            from ui_icons import pixmap as icon_pixmap
            self.source_card_thumb.setPixmap(icon_pixmap('image','#A9A6B8',64))
        if imported:
            # The scene strip's own thumbnail; no extra rendering here.
            thumb=None
            if 0<=getattr(self,'scene_index',-1)<len(getattr(self,'scenes',[])):
                thumb=self.scenes[self.scene_index].get('thumb')
            if thumb is not None and not thumb.isNull():
                from PySide6.QtGui import QPixmap
                from PySide6.QtCore import QSize
                box=QSize(max(120,self.source_card_thumb.width()),self.source_card_thumb.height())
                self.source_card_thumb.setPixmap(QPixmap.fromImage(thumb).scaled(
                    box,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            else:
                from ui_icons import pixmap as icon_pixmap
                self.source_card_thumb.setPixmap(icon_pixmap('image','#A9A6B8',64))
        # Appearance: blend and opacity for imported artwork; paper cleanup
        # only affects images. (The Element Editor keeps all of them.)
        form=self.appearance_form
        self.source_appearance_heading.setVisible(imported)
        for field in (self.blend_mode,self.opacity_row):
            form.setRowVisible(field,imported)
        for field in (self.paper_cleanup,self.paper_tolerance,self.paper_softness):
            form.setRowVisible(field,kind==IMAGE)
        # Ink on the page, Colour, Light: for an imported picture.
        for section in ('section_ink','section_look_colour','section_look_light'):
            if hasattr(self,section): getattr(self,section).setVisible(imported)
        # Matching colors (SVG) / Change original image (image).
        self.source_colors_heading.setVisible(imported)
        self.source_colors_heading.setText('Matching colours' if kind==SVG else 'Original image')
        self.load_color_button.setVisible(imported)
        self.color_note.setVisible(imported)
        self.clean_color.setVisible(kind==SVG)
        self.use_color.setVisible(kind==SVG)
        self.source_settings_toggle.setVisible(False)       # sections now (exp.100)
        self.source_settings.setVisible(imported)
        if hasattr(self,'update_ink_swatch'):
            self.update_ink_swatch()
        # Image to drawing follows the existing image controls.
        self.image_drawing_heading.setVisible(not self.image_controls.isHidden())

    def _artwork_busy(self):
        return bool((self.builder and self.builder.isRunning()) or
                    (self.worker and self.worker.isRunning()) or getattr(self,'_pending_artwork',None))

    def choose_artwork_placement(self):
        labels=list(LABELS)
        if not self.drawing:
            return 'add'
        choice,ok=QInputDialog.getItem(self,'Place artwork','Where should this artwork go?',labels,0,False)
        return LABELS.get(choice) if ok else None

    def new_project(self):
        # exp.156: each step in the log (the user: New Project did nothing, with no message).
        import applog
        applog.info('New Project: asked')
        if self._artwork_busy():
            applog.info('New Project: waiting for an import/export to finish')
            notify(self,'Finish or cancel the current import/export first.','warning')
            return False
        if not self.confirm_leave_project('create a New Project'):
            applog.info('New Project: not made (the unsaved changes were not saved or discarded)')
            self.status.setText('New Project: cancelled.')
            return False
        try:
            self._reset_artwork_project()
        except Exception as exc:
            applog.error('New Project could not be made',exc)
            QMessageBox.warning(self,'New Project',f'The new project could not be made: {str(exc)[:300]}')
            return False
        applog.info('New Project: made')
        return True

    def _reset_artwork_project(self):
        from engine import Drawing
        from projects import drawing_to_dict
        self._artwork_generation=getattr(self,'_artwork_generation',0)+1
        state=self.scene_state()
        state.update(title='Untitled project',source='svg',drawing=drawing_to_dict(Drawing([],(0.,0.,100.,100.),[])),
                     color_png=None,audio=None,overlays=[])
        state.pop('image',None);state.pop('artwork',None)
        state['settings'].update(use_color=False,preserve_colors=True,image_animation='Draw, then Paint',
                                 picture_x=0.,picture_y=0.,artwork_size=100.,audio_path=None)
        self.image_result=None;self.image_path=None;self.image_guide=None;self.svg_state=None
        self.__dict__.pop('_memo',None); self._scene_cache={}           # exp.198: nothing of the old project
        self.apply_project(state)
        self.preview_scope.setCurrentIndex(0)
        self.project_path=None
        self.position=0
        self.reset_history()
        self.project_changes.mark_saved(self.project_state())
        self._autosaved_signature=None
        import autosave
        autosave.clear()
        self.sync_workspace();self.fill_scenes();self.refresh()
        self.status.setText('New Project. Import artwork to add the first element.')

    def request_artwork(self,path,kind='image',original=None,placement=None,name=None,same_spot=False,assets=None,whole_preview=False):
        if self._artwork_busy():
            notify(self,'Wait for the current import/export to finish.','warning')
            return False
        placement=placement or self.choose_artwork_placement()
        if placement not in ('add','replace','new'):
            return False
        if placement=='replace' and not self.drawing:
            return False
        if placement in ('replace','new') and not self.confirm_leave_project(
                'replace the selected artwork' if placement=='replace' else 'create a New Project'):
            return False
        path=str(path)
        before_prepare=self.project_changes.revision
        ctx=dict(placement=placement,generation=getattr(self,'_artwork_generation',0),
                 target=self.scenes[self.scene_index],name=name or Path(original or path).stem,
                 same_spot=same_spot,whole_preview=whole_preview,cancelled=False,committed=False,path=path,confirmed_revision=before_prepare)
        try:
            if kind=='svg' or path.lower().endswith('.svg'):
                from engine import import_svg
                drawing=import_svg(path)
                return self._commit_artwork(ctx,drawing)
            from artwork_assets import capture_assets,validate_assets,materialize_assets
            if assets is None:
                import library
                assets=library.Library().artwork_for(path)
            metadata=validate_assets(assets) if assets else capture_assets(original or path,path if kind=='lineart' and original else None)
            source,guide=materialize_assets(metadata)
            ctx.update(assets=metadata,source=source,guide=guide)
            self._pending_artwork=ctx
            self.build_image(source,line_guide=guide,intake=ctx)
            return True
        except Exception as exc:
            self._pending_artwork=None
            QMessageBox.warning(self,'Cannot import artwork',str(exc))
            return False

    def cancel_artwork_import(self):
        ctx=getattr(self,'_pending_artwork',None)
        if ctx:
            ctx['cancelled']=True
            self.status.setText('Cancelling import; existing artwork will be kept.')
            if self.builder:
                self.builder.requestInterruption()

    def _accept_artwork_result(self,result,ctx):
        if ctx.get('cancelled'):
            return False
        if ctx['generation']!=getattr(self,'_artwork_generation',0) or ctx['target'] is not self.scenes[self.scene_index]:
            ctx['cancelled']=True
            self.status.setText('Import result was not applied because the editing target changed.')
            return False
        if hasattr(result.drawing,'source_frame'):
            ctx['assets']['frame']=result.drawing.source_frame
        result.drawing.artwork_assets=ctx['assets']
        return self._commit_artwork(ctx,result.drawing,result)

    def _commit_artwork(self,ctx,drawing,result=None):
        placement=ctx['placement']
        if ctx.get('cancelled'):
            return False
        if placement in ('replace','new') and ctx.get('confirmed_revision')!=self.project_changes.revision and not self.confirm_leave_project(
                'replace the selected artwork' if placement=='replace' else 'create a New Project'):
            ctx['cancelled']=True
            return False
        previous=self.project_state()
        tracker=copy.deepcopy(self.project_changes)
        history=copy.deepcopy(self.history)
        old_path=getattr(self,'project_path',None)
        self._preparing=True
        spot=None
        try:
            if placement=='new':
                self._reset_artwork_project()
            elif placement=='add' and self.drawing:
                if ctx.get('same_spot'):
                    # exp.244 (the user): at its normal size in the middle of what the camera
                    # shows; nothing is made smaller to fit (the existing picture is not touched)
                    self.store_scene(thumbnail=False)
                    spot=self.same_page_spot()
                self.record_structure('add element')
                self._leave_scene()
                self._stash_history()
                from scenes import DEFAULT_TRANSITION,DEFAULT_TRANSITION_SECONDS
                scene=dict(state=None,transition=DEFAULT_TRANSITION,
                           transition_seconds=DEFAULT_TRANSITION_SECONDS,name=ctx['name'],thumb=None)
                if spot is not None:
                    current=self.scenes[self.scene_index]
                    scene['transition']=current['transition']
                    scene['transition_seconds']=current['transition_seconds']
                    current['transition']='Same page'
                elif not ctx.get('same_spot'):
                    # exp.235 (the user: the new element was cut and its camera did not follow): "In a
                    # new place" means the camera moves to it: the element before goes there with a
                    # camera move (it said Same page, so the new one landed on the same page)
                    import board as _board
                    current=self.scenes[self.scene_index]
                    if current.get('transition') not in _board.CAMERA_KINDS:
                        current['transition']=DEFAULT_TRANSITION if DEFAULT_TRANSITION in _board.CAMERA_KINDS else 'Camera move'
                    ctx['ask_camera']=True
                self.scene_index+=1;self.scenes.insert(self.scene_index,scene)
                self.fresh_element_settings()        # exp.112: from zero, not the element before
            if placement!='replace':
                pass                                  # texts belong to the whole video (exp.116)
            self.image_result=result
            self.image_path=ctx.get('source') if result is not None else None
            self.image_guide=ctx.get('guide') if result is not None else None
            self.final_image=None;self.color_original=None;self.color_path=None;self.svg_state=None
            self.source_type.blockSignals(True)
            self.source_type.setCurrentIndex(1 if result is not None else 0)
            self.source_type.blockSignals(False)
            self.image_controls.setVisible(result is not None)
            self.use_color.blockSignals(True);self.use_color.setChecked(False);self.use_color.blockSignals(False)
            if result is not None:
                self.image_animation.blockSignals(True);self.image_animation.setCurrentIndex(0);self.image_animation.blockSignals(False)
                self.preserve_colors.blockSignals(True);self.preserve_colors.setChecked(True);self.preserve_colors.blockSignals(False)
                self.color_note.setText(ctx['name']+' • original colors; paired drawing')
            else:
                if getattr(drawing,'svg_has_fill',False):
                    from svg_appearance import render_appearance
                    self.final_image=render_appearance(drawing)
                    self.color_original=self.final_image
                    self.use_color.blockSignals(True);self.use_color.setChecked(True);self.use_color.blockSignals(False)
                    self.color_note.setText('Original SVG appearance • native fills')
                else:
                    self.color_note.setText('Outline-only SVG')
            if placement!='replace':
                size,x,y=spot or (100.,0.,0.)
                for control,value in ((self.picture_x,x),(self.picture_y,y),(self.artwork_size,size)):
                    control.blockSignals(True);control.setValue(value);control.blockSignals(False)
            self.scenes[self.scene_index]['name']=ctx['name']
            self.scenes[self.scene_index]['thumb']=None
            self.set_drawing(drawing)
            self.position=0;self.slider.setValue(0)
            if ctx.get('whole_preview') and len(self.scenes)>1 and self.preview_scope.currentIndex()==0:
                self.preview_scope.setCurrentIndex(1)
            self.project_changes.mark_changed()
            ctx['committed']=True
            try:
                import library
                if library.load_settings().get('keep_imports',True):
                    lib=library.Library()
                    item=lib.add('images',ctx['path'],name=ctx['name'])
                    if result is not None:lib.set_artwork(item,ctx['assets'])
            except Exception as exc:
                import applog
                applog.error('Could not preserve artwork in the Library',exc)
            self.status.setText('Artwork added.' if placement=='add' else 'Selected artwork replaced.' if placement=='replace' else 'Artwork added to New Project.')
            import sys as _sys
            if ctx.get('ask_camera') and len(self.scenes)>1 and 'unittest' not in _sys.modules:
                # exp.235 (the user: if it goes to a new camera place, ask me to select the place)
                from PySide6.QtCore import QTimer
                k=self.scene_index
                QTimer.singleShot(0,lambda k=k: self.set_camera(k) if 0<=k<len(self.scenes) else None)
        except Exception as exc:
            self.apply_project(previous)
            self.project_changes=tracker;self.history=history;self.project_path=old_path
            QMessageBox.warning(self,'Cannot place artwork',str(exc))
            return False
        finally:
            self._preparing=False
        self.fill_scenes();self.sync_workspace();self.refresh()
        return True

    def import_artwork(self,path,placement=None):
        return self.request_artwork(path,kind='svg' if str(path).lower().endswith('.svg') else 'image',
                                    placement=placement)

    def open_svg_source(self):
        return self.load(kind='svg')

    def open_image_source(self):
        return self.load(kind='image')

    def load(self,kind=None):
        kind=kind or ('image' if self.source_type.currentIndex() else 'svg')
        path,_=QFileDialog.getOpenFileName(self,'Import artwork','',
                     'SVG (*.svg)' if kind=='svg' else 'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            return self.request_artwork(path,kind=kind)
        return False
