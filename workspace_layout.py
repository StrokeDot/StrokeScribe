"""Persistent, collapsible three-column Studio layout.

The existing Qt splitter stays in charge of panel geometry. This module only
controls the sidebars and their widths; it never touches drawing or timeline
state, project settings, or rendering.

Panels start closed (only the icon rails show, so the canvas is big). Clicking
a rail icon slides its panel open toward the canvas, pushing the canvas over;
the panel's close button or the same icon slides it shut again.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QObject, QSettings, QTimer, QVariantAnimation

MIN_SOURCE, MAX_SOURCE = 225, 460
MIN_INSPECTOR, MAX_INSPECTOR = 270, 480
DEFAULT_SOURCE, DEFAULT_INSPECTOR = 290, 330
LAYOUT_VERSION = 2            # 2: panels closed until a rail icon is clicked
SLIDE_MS = 200


def headless(platform=None):
    """The offscreen test harness: no animation, panels open (controls measurable)."""
    platform = os.environ.get('QT_QPA_PLATFORM', '') if platform is None else platform
    return platform == 'offscreen'


def default_open(platform=None):
    """Panels are closed by default for people; the headless harness keeps them open."""
    return headless(platform)


def _width(value, default, minimum, maximum):
    try:
        return min(max(int(value), minimum), maximum)
    except (ValueError, TypeError, OverflowError):
        return default


class SidebarController(QObject):
    """Manage two independent sidebar visibility toggles and split positions.

    Hiding a splitter child removes both that panel and its handle, allowing the
    Program preview to use all available space. A permanently visible toggle
    in the Program header remains available to reopen either sidebar.
    """

    def __init__(self, owner, splitter, source, inspector, source_button, inspector_button, names=None):
        super().__init__(owner)
        self.splitter = splitter
        self.panels = {'source': source, 'inspector': inspector}
        self.buttons = {'source': source_button, 'inspector': inspector_button}
        # Display names for tooltips; the 'source'/'inspector' keys stay the
        # same so saved widths and open/closed states carry over.
        self.names = {'source': 'Source', 'inspector': 'Inspector'}
        self.names.update(names or {})
        # Called after every show/hide (e.g. to keep the icon rails in step).
        self.listeners = []
        self.settings = QSettings('StrokeScribe', 'Studio')
        self.widths = {
            'source': _width(self.settings.value('workspace/source_width', DEFAULT_SOURCE),
                             DEFAULT_SOURCE, MIN_SOURCE, MAX_SOURCE),
            'inspector': _width(self.settings.value('workspace/inspector_width', DEFAULT_INSPECTOR),
                                DEFAULT_INSPECTOR, MIN_INSPECTOR, MAX_INSPECTOR),
        }
        if not headless() and int(self.settings.value('workspace/layout_version', 1) or 1) < LAYOUT_VERSION:
            # First start with the rail layout: begin with both panels closed.
            for side in self.panels:
                self.settings.setValue('workspace/' + side + '_open', False)
            self.settings.setValue('workspace/layout_version', LAYOUT_VERSION)
        self.expanded = {
            side: self.settings.value('workspace/' + side + '_open', default_open(), type=bool)
            for side in self.panels
        }
        self.animate = not headless()
        self._slide = None
        self._adjusting = True
        for side, button in self.buttons.items():
            button.setCheckable(True)
            button.clicked.connect(lambda checked, s=side: self.set_expanded(s, checked))
        splitter.splitterMoved.connect(self._remember_drag)
        # Splitter geometry is not meaningful until the main window is shown.
        QTimer.singleShot(0, self.restore)

    def restore(self):
        self._adjusting = True
        try:
            for side, panel in self.panels.items():
                panel.setVisible(self.expanded[side])
            self._resize()
            self._update_buttons()
        finally:
            self._adjusting = False

    def _update_buttons(self):
        for side, button in self.buttons.items():
            shown = bool(self.expanded[side])
            button.blockSignals(True)
            button.setChecked(shown)
            button.setText(('◀' if shown else '▶') if side == 'source' else
                           ('▶' if shown else '◀'))
            description = ('Hide ' if shown else 'Show ') + self.names[side] + ' panel'
            button.setToolTip(description)
            button.setAccessibleName(description)
            button.blockSignals(False)
        for listener in list(getattr(self, 'listeners', ())):
            try:
                listener()
            except Exception:
                pass

    def _target(self):
        left = self.widths['source'] if self.expanded['source'] else 0
        right = self.widths['inspector'] if self.expanded['inspector'] else 0
        available = max(0, self.splitter.width())
        # Keep the middle pane as the expanding remainder. Qt enforces the
        # minimum widths if a restored window is narrower than before.
        center = max(390, available - left - right - self.splitter.handleWidth() * 2)
        return [left, center, right]

    def _resize(self):
        self.splitter.setSizes(self._target())

    def _finish_slide(self):
        """Jump to the end of a running slide (a new click wins over the old one)."""
        slide, self._slide = self._slide, None
        if slide is not None:
            slide.stop()
            slide.finished.emit()

    def _freeze(self, panel, width):
        """Hold the panel's contents at their open width while it slides.

        The panel can then be any width (its contents are clipped, not laid
        out again), so the splitter moves it smoothly all the way to zero in
        both directions instead of re-wrapping text every frame and stalling
        at the panel's minimum width before snapping shut.
        """
        from PySide6.QtWidgets import QLayout, QSizePolicy
        layout = panel.layout()
        children = [layout.itemAt(i).widget() for i in range(layout.count())]
        children = [c for c in children if c is not None]
        saved = dict(policy=panel.sizePolicy(), constraint=layout.sizeConstraint(),
                     minimum=panel.minimumWidth(),
                     children=[(c, c.minimumWidth(), c.maximumWidth()) for c in children])
        policy = QSizePolicy(panel.sizePolicy())
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        panel.setSizePolicy(policy)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        panel.setMinimumWidth(1)
        width = max(1, int(width))
        for child in children:
            child.setFixedWidth(width)
        return saved

    def _thaw(self, panel, saved):
        layout = panel.layout()
        for child, low, high in saved['children']:
            child.setMinimumWidth(low)
            child.setMaximumWidth(high)
        layout.setSizeConstraint(saved['constraint'])
        panel.setSizePolicy(saved['policy'])
        panel.setMinimumWidth(saved['minimum'])

    def _slide_to(self, side, expanded):
        """Animate the splitter from its current sizes to the new layout."""
        panel = self.panels[side]
        index = 0 if side == 'source' else 2
        start = list(self.splitter.sizes())
        width = self.widths[side] if expanded else max(start[index], 1)
        saved = self._freeze(panel, width)
        if expanded:
            panel.setVisible(True)
            start[index] = 0
            self._adjusting = True
            try:
                self.splitter.setSizes(start)
            finally:
                self._adjusting = False
        end = self._target()
        slide = QVariantAnimation(self)
        slide.setDuration(SLIDE_MS)
        slide.setStartValue(0.0)
        slide.setEndValue(1.0)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic if expanded else QEasingCurve.Type.InOutCubic)

        def step(t):
            t = float(t)
            self._adjusting = True
            try:
                self.splitter.setSizes([round(a + (b - a) * t) for a, b in zip(start, end)])
            finally:
                self._adjusting = False

        def done():
            if self._slide is slide:
                self._slide = None
            self._adjusting = True
            try:
                panel.setVisible(self.expanded[side])
                self._thaw(panel, saved)
                self._resize()
            finally:
                self._adjusting = False

        slide.valueChanged.connect(step)
        slide.finished.connect(done)
        self._slide = slide
        slide.start()

    def set_expanded(self, side, expanded):
        if side not in self.panels:
            raise ValueError('Unknown sidebar: ' + str(side))
        expanded = bool(expanded)
        if self.expanded[side] == expanded:
            self._update_buttons()
            return
        self._finish_slide()
        if not self._adjusting:
            self._capture_widths()
        self.expanded[side] = expanded
        if self.animate and self.splitter.isVisible():
            self._update_buttons()
            self._slide_to(side, expanded)
        else:
            self._adjusting = True
            try:
                self.panels[side].setVisible(expanded)
                self._resize()
                self._update_buttons()
            finally:
                self._adjusting = False
        self.settings.setValue('workspace/' + side + '_open', expanded)

    def _capture_widths(self):
        sizes = self.splitter.sizes()
        if len(sizes) != 3:
            return
        for side, i, low, high in (
            ('source', 0, MIN_SOURCE, MAX_SOURCE),
            ('inspector', 2, MIN_INSPECTOR, MAX_INSPECTOR),
        ):
            if self.expanded[side] and sizes[i] >= low:
                self.widths[side] = _width(sizes[i], self.widths[side], low, high)
                self.settings.setValue('workspace/' + side + '_width', self.widths[side])

    def _remember_drag(self, position, index):
        if not self._adjusting:
            self._capture_widths()
