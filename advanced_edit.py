"""Advanced edit: one element in a big window, like Filmora's Advanced Text Edit (exp.17).

The user: double-clicking a part of an element on the timeline opened small windows with a few
of its settings (and Hand in / Hand out opened the wrong one or none). In Filmora the advanced
window shows the settings of the panels outside, and a little more. So this window is an
extension of the panels: the real preview (with its play buttons) and the real panels, Text,
Image, Animation, Hand and Camera, are moved into it while it is open and go back to their places
when it closes. Nothing is a copy, so every setting behaves exactly as outside.

It opens on the tab of the part that was double-clicked: Draw (Text for a text, Image for a
picture), Paint (Animation, Colour & painting), Hand in / Hand out (Hand), Out (Animation).
Apply keeps the changes; Cancel puts the element back as it was.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

# which tab a double-clicked part opens on
PART_TAB = {'draw': 'draw', 'paint': 'animation', 'glide': 'hand', 'hold': 'hand', 'back': 'hand',
            'hand': 'hand', 'erase': 'effects', 'out': 'effects', 'move': 'effects',   # exp.27
            'element': 'draw'}


class AdvancedEdit(QDialog):
    def __init__(self, window, k, part='element'):
        super().__init__(window)
        self.w = w = window
        self.k = k
        self.part = part
        self.scope = w.preview_scope.currentIndex()
        self.main_position = w.position
        scene = w.scenes[k]
        self.saved = dict(snapshot=w.snapshot(), name=scene.get('name'),
                          transition=scene.get('transition'), seconds=scene.get('transition_seconds'),
                          overlays=[dict(o) for o in getattr(w, 'overlays', []) or []])
        if self.scope:
            w.preview_scope.setCurrentIndex(0)                 # the element itself
        self.text = getattr(w.drawing, 'source_kind', None) in ('font', 'lettering')
        self.setObjectName('advancedEdit')
        self.setWindowTitle(f'Advanced edit · Element {k + 1}: {w.scene_label(k)}')
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        root = QVBoxLayout(self); root.setContentsMargins(14, 12, 14, 12); root.setSpacing(10)

        # ------------------------------------------------ header: what it is, extra editors
        head = QHBoxLayout(); head.setSpacing(8)
        kind = 'Text' if self.text else ('Image' if w.is_image_artwork() else 'Drawing')
        title = QLabel(f'{kind} · {w.scene_label(k)}'); title.setObjectName('panelTitle')
        head.addWidget(title); head.addStretch(1)
        self.extra = []
        if not self.text:
            for label, stage, tip in (('Replace drawing…', 'draw', 'Another SVG or line-art picture for its lines.'),
                                      ('Replace colours…', 'paint', 'Another picture for the colours it paints.')):
                b = QPushButton(label); b.setToolTip(tip)
                b.clicked.connect(lambda checked=False, s=stage: self.source_editor(s))
                head.addWidget(b); self.extra.append(b)
        glide = QPushButton('Hand way in and back…')
        glide.setToolTip('How the hand comes to the element and goes back to its corner (the Hand row).')
        glide.clicked.connect(lambda checked=False: w.edit_hand_glide(self.k))
        head.addWidget(glide); self.extra.append(glide)
        root.addLayout(head)

        # ------------------------------------------------ the real preview and panels
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)
        self._borrow()

        # ------------------------------------------------ Apply / Cancel
        foot = QHBoxLayout()
        note = QLabel('These are the same settings as in the panels outside. Apply keeps the changes; '
                      'Cancel puts the element back as it was.')
        note.setObjectName('caption'); note.setWordWrap(True)
        foot.addWidget(note, 1)
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject)
        apply = QPushButton('Apply'); apply.setObjectName('primary'); apply.setDefault(True)
        apply.clicked.connect(self.accept)
        foot.addWidget(cancel); foot.addWidget(apply)
        root.addLayout(foot)
        screen = window.screen().availableGeometry() if window.screen() else None
        width = min(1500, int(screen.width() * .9)) if screen else 1400
        height = min(920, int(screen.height() * .88)) if screen else 860
        self.resize(width, height)
        self.open_tab(PART_TAB.get(part, 'draw'))
        w.slider.setValue(1000)                 # the finished element (press play to watch it)
        w.refresh()

    # ------------------------------------------------------------ borrowing the panels
    def _borrow(self):
        """Move the preview, the Inspector tabs and the Text / Camera pages into this window."""
        from studio_workspace import LEFT
        w = self.w
        self.home = {}
        # the preview (canvas + play buttons): its place in the main window's splitter
        monitor = w.workspace_splitter.widget(1)
        self.home['monitor'] = (monitor, w.workspace_splitter.sizes())
        self.split.addWidget(monitor)
        monitor.show()
        self.home['fullscreen'] = w.fullscreen_button.isEnabled()
        w.fullscreen_button.setEnabled(False)          # it works on the main window, behind this one
        # the Inspector tabs: their place in the Inspector panel
        tabs = w.inspector_tabs
        holder = tabs.parentWidget()
        lay = holder.layout()
        self.home['tabs'] = (lay, lay.indexOf(tabs), tabs.currentIndex())
        self.split.addWidget(tabs)
        tabs.show()
        # the left pages that belong to an element: Text (for a text) and Camera
        self.borrowed = []
        for key, name in (('camera', 'Camera'), ('text', 'Text')):
            if key == 'text' and not self.text:
                continue
            page = w.left_tabs.widget(LEFT[key])
            self.borrowed.append((key, page, w.left_tabs.tabText(LEFT[key])))
        self.home['left'] = w.left_tabs.currentIndex()
        for key, page, label in sorted(self.borrowed, key=lambda b: -LEFT[b[0]]):
            w.left_tabs.removeTab(w.left_tabs.indexOf(page))
        for key, page, label in self.borrowed:
            at = 0 if key == 'text' else tabs.count()
            tabs.insertTab(at, page, label)
            page.show()
        # not about one element: hidden while the window is open
        from studio_workspace import TABS
        self.hidden_tabs = []
        for key in ('export', 'ai', 'stickers'):     # exp.27: stickers are not part of one element
            page = self.page_of(key)
            i = tabs.indexOf(page)
            if i >= 0 and tabs.isTabVisible(i):
                tabs.setTabVisible(i, False); self.hidden_tabs.append(page)
        tabs.tabBar().show()
        self.home['elide'] = tabs.tabBar().elideMode()
        tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)      # whole tab names here
        self.split.setStretchFactor(0, 3); self.split.setStretchFactor(1, 2)
        self.split.setSizes([880, 560])
        tabs.setMaximumWidth(16777215)

    def page_of(self, key):
        """The page widget of an Inspector tab (by its key in studio_workspace.TABS)."""
        from studio_workspace import TABS
        pages = getattr(self, '_pages', None)
        if pages is None:
            tabs = self.w.inspector_tabs
            # the original pages, before the Text / Camera pages were put in front
            self._pages = pages = {}
        if key not in pages:
            pages[key] = self._original_page(key)
        return pages[key]

    def _original_page(self, key):
        from studio_workspace import TABS
        tabs = self.w.inspector_tabs
        borrowed = {id(p) for _, p, _ in getattr(self, 'borrowed', [])}
        own = [tabs.widget(i) for i in range(tabs.count()) if id(tabs.widget(i)) not in borrowed]
        i = TABS.get(key)
        return own[i] if i is not None and i < len(own) else None

    def open_tab(self, which):
        """Show the tab for a part: 'draw' = Text (a text) or Image, else an Inspector key."""
        from ui_sections import reveal
        w = self.w
        tabs = w.inspector_tabs
        if which == 'draw':
            page = next((p for key, p, _ in self.borrowed if key == 'text'), None) if self.text else None
            page = page or self.page_of('source')
        else:
            page = self.page_of(which)
        if page is not None and tabs.indexOf(page) >= 0:
            tabs.setCurrentIndex(tabs.indexOf(page))
        if self.part == 'paint' and hasattr(w, 'section_painting'):
            reveal(w.section_painting)
            w.section_painting.set_expanded(True)
        if self.part in ('glide', 'hold', 'back', 'hand') and hasattr(w, 'section_draw_hand'):
            w.section_draw_hand.set_expanded(True)          # the hand that draws it

    def give_back(self):
        """Every borrowed panel back to its place in the main window."""
        from studio_workspace import LEFT
        if not self.home:
            return                                  # already given back
        w = self.w
        tabs = w.inspector_tabs
        for page in getattr(self, 'hidden_tabs', []):
            i = tabs.indexOf(page)
            if i >= 0: tabs.setTabVisible(i, True)
        for key, page, label in getattr(self, 'borrowed', []):
            i = tabs.indexOf(page)
            if i >= 0: tabs.removeTab(i)
        for key, page, label in sorted(getattr(self, 'borrowed', []), key=lambda b: LEFT[b[0]]):
            w.left_tabs.insertTab(LEFT[key], page, label)
        if 'left' in self.home:
            w.left_tabs.setCurrentIndex(self.home['left'])
        lay, index, current = self.home['tabs']
        tabs.tabBar().setElideMode(self.home.get('elide', Qt.TextElideMode.ElideRight))
        tabs.setMaximumWidth(16777215)
        lay.insertWidget(index, tabs, 1)
        tabs.setCurrentIndex(current)
        w.fullscreen_button.setEnabled(self.home.get('fullscreen', True))
        monitor, sizes = self.home['monitor']
        w.workspace_splitter.insertWidget(1, monitor)
        w.workspace_splitter.setSizes(sizes)
        monitor.show(); tabs.show()
        self.home = {}

    # ------------------------------------------------------------ extra editors
    def source_editor(self, stage):
        from source_editor import SourceEditor
        SourceEditor(self.w, stage).exec()
        self.w.refresh()

    # ------------------------------------------------------------ Apply / Cancel
    def _back_to_view(self):
        w = self.w
        scope = w.preview_scope
        if self.scope and scope.currentIndex() != self.scope and len(w.scenes) > 1:
            scope.setCurrentIndex(self.scope)
        w.position = self.main_position
        w.slider.blockSignals(True); w.slider.setValue(round(w.position * 1000)); w.slider.blockSignals(False)

    def accept(self):
        w = self.w
        w.playing = False
        self.give_back()
        w.commit_history()
        self._back_to_view()
        w.fill_scenes(); w.refresh()
        super().accept()

    def reject(self):
        w = self.w
        w.playing = False
        self.give_back()
        w.restore(self.saved['snapshot'])
        scene = w.scenes[self.k]
        scene['name'] = self.saved['name']
        scene['transition'], scene['transition_seconds'] = self.saved['transition'], self.saved['seconds']
        if hasattr(w, 'overlays'):
            w.overlays[:] = self.saved['overlays']          # a Goes out clip made here goes too
        self._back_to_view()
        w.fill_scenes(); w.refresh()
        super().reject()
