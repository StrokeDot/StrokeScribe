"""The menu bar: File, Edit, View, Effects, Help.

Every menu choice uses the same controls as the panels (a choice in a menu is
the same as choosing it in the panel), so menus and panels always agree, and
undo, projects and the preview work the same way.
"""
from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup


def _combo_menu(parent_menu, title, combo, tip='', after=None):
    """A submenu with one checkable item per choice of `combo`."""
    menu = parent_menu.addMenu(title)
    if tip:
        menu.setToolTip(tip)

    def fill():
        menu.clear()
        group = QActionGroup(menu)
        group.setExclusive(True)
        model = combo.model()
        for i in range(combo.count()):
            action = QAction(combo.itemText(i), menu, checkable=True)
            action.setChecked(i == combo.currentIndex())
            item = model.item(i) if hasattr(model, 'item') else None
            action.setEnabled(combo.isEnabled() and (item is None or item.isEnabled()))
            def choose(checked=False, k=i):
                combo.setCurrentIndex(k)
                if after:
                    after()
            action.triggered.connect(choose)
            group.addAction(action)
            menu.addAction(action)
    menu.aboutToShow.connect(fill)
    fill()
    owner = parent_menu.parent()
    while owner is not None and not hasattr(owner, 'submenus'):
        owner = owner.parent()
    if owner is not None:
        owner.submenus[title] = menu
    return menu


def _toggle(menu, text, box):
    action = QAction(text, menu, checkable=True)
    action.triggered.connect(lambda checked: box.setChecked(checked))
    menu.aboutToShow.connect(lambda: (action.setChecked(box.isChecked()), action.setEnabled(box.isEnabled())))
    menu.addAction(action)
    return action


def _go(w, tab):
    """Show an Inspector tab by name (studio_workspace.TABS)."""
    from studio_workspace import TABS
    w.inspector_tabs.setCurrentIndex(TABS[tab])


def build_menus(w):
    bar = w.menuBar()
    bar.setNativeMenuBar(False)
    w.menus = {}
    w.submenus = {}

    # ---------------------------------------------------------------- File
    file = bar.addMenu('&File'); w.menus['file'] = file
    file.addAction('Open project…\tCtrl+O', lambda: w.open_project())
    file.addAction('Save project\tCtrl+S', lambda: w.save_project())
    file.addAction('Save project as…', lambda: w.save_project(save_as=True))
    recent_menu = file.addMenu('Recent projects')

    def fill_recent():
        import autosave
        from pathlib import Path
        recent_menu.clear()
        paths = autosave.recent()
        for p in paths:
            recent_menu.addAction(Path(p).stem, lambda p=p: w.open_project(p)).setToolTip(p)
        if not paths:
            recent_menu.addAction('(none yet)').setEnabled(False)
    recent_menu.aboutToShow.connect(fill_recent)
    w.submenus['Recent projects'] = recent_menu
    file.addSeparator()
    file.addAction('Import SVG artwork…', w.open_svg_source)
    file.addAction('Import PNG / JPG artwork…', w.open_image_source)
    file.addAction('Library…', lambda: w.open_library())
    file.addSeparator()
    file.addAction('Export animation…', w.open_export)
    file.addAction('Batch export…', lambda: w.open_batch_export())
    file.addSeparator()
    file.addAction('Update StrokeScribe…', lambda: w.open_updates())
    file.addSeparator()
    file.addAction('Exit', w.close)

    # ---------------------------------------------------------------- Edit
    edit = bar.addMenu('&Edit'); w.menus['edit'] = edit
    undo = edit.addAction('Undo\tCtrl+Z', lambda: w.undo())
    redo = edit.addAction('Redo\tCtrl+Y', lambda: w.redo())
    edit.addSeparator()
    delete = edit.addAction('Delete selected lines\tDel', lambda: w.delete_lines())
    reverse = edit.addAction('Reverse selected lines', lambda: w.reverse_lines())
    edit.addSeparator()
    add_scene = edit.addAction('Add scene', lambda: w.add_scene())
    del_scene = edit.addAction('Delete scene', lambda: w.delete_scene())

    def edit_state():
        undo.setEnabled(w.history.can_undo()); redo.setEnabled(w.history.can_redo())
        has_lines = bool(w.selected_rows()) if w.drawing else False
        delete.setEnabled(has_lines); reverse.setEnabled(has_lines)
        add_scene.setEnabled(w.drawing is not None); del_scene.setEnabled(len(w.scenes) > 1)
    edit.aboutToShow.connect(edit_state)

    # ---------------------------------------------------------------- View
    view = bar.addMenu('&View'); w.menus['view'] = view
    theme_action = view.addAction('Dark mode', lambda: w.toggle_theme())
    theme_action.setCheckable(True)

    def view_state():
        import theme
        theme_action.setChecked(theme.current() == 'dark')
    view.aboutToShow.connect(view_state)
    _combo_menu(view, 'Preview background', w.preview_background)
    _combo_menu(view, 'Preview', w.preview_scope)
    view.addSeparator()
    view.addAction('Animation settings', lambda: _go(w, 'animation'))
    view.addAction('Hand settings', lambda: _go(w, 'hand'))
    view.addAction('Sound settings', lambda: _go(w, 'sound'))
    view.addAction('Export settings', lambda: _go(w, 'export'))

    # ---------------------------------------------------------------- Effects
    fx = bar.addMenu('Effe&cts'); w.menus['effects'] = fx
    _combo_menu(fx, 'Paint mode', w.reveal_mode)
    _combo_menu(fx, 'Pen movement', w.pen_ease)
    _combo_menu(fx, 'Camera follow', w.camera)
    _combo_menu(fx, 'Erase at the end', w.erase_mode)
    _combo_menu(fx, 'Eraser shown', w.eraser)
    fx.addSeparator()
    _combo_menu(fx, 'Painting hand', w.paint_hand, after=lambda: w.paint_hand_changed())
    _toggle(fx, 'Show hand while drawing', w.showhand)
    _toggle(fx, 'Show hand while painting', w.show_paint_hand)
    fx.addSeparator()
    _toggle(fx, 'Pencil, brush and eraser sounds', w.sound_on)
    fx.addAction('Sound settings…', lambda: _go(w, 'sound'))
    fx.addAction('Add a pencil sound…', lambda: w.choose_sound_file('sound_pencil_file'))
    fx.addAction('Create a sound with AI…', lambda: w.open_create_image('sound'))
    fx.addSeparator()
    _combo_menu(fx, 'Export', w.export_layers)
    _combo_menu(fx, 'MP4 background', w.mp4_background)
    fx.addSeparator()
    fx.addAction('Auto timing', lambda: w.auto_timing())
    fx.addAction('Create image with AI…', lambda: w.open_create_image())

    # ---------------------------------------------------------------- Help
    help_menu = bar.addMenu('&Help'); w.menus['help'] = help_menu
    help_menu.addAction('Setup && system check…', lambda: w.open_setup())
    help_menu.addAction('Check for updates…', lambda: w.open_updates())
    help_menu.addSeparator()
    help_menu.addAction('About StrokeScribe', lambda: w.show_version_info())
    return bar
