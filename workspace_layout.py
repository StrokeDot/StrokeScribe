"""Persistent, collapsible three-column Studio layout.

The existing Qt splitter stays in charge of panel geometry. This module only
controls the sidebars and their widths; it never touches drawing or timeline
state, project settings, or rendering.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, QTimer

MIN_SOURCE, MAX_SOURCE = 225, 460
MIN_INSPECTOR, MAX_INSPECTOR = 270, 480
DEFAULT_SOURCE, DEFAULT_INSPECTOR = 290, 330


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
        self.expanded = {
            side: self.settings.value('workspace/' + side + '_open', True, type=bool)
            for side in self.panels
        }
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

    def _resize(self):
        left = self.widths['source'] if self.expanded['source'] else 0
        right = self.widths['inspector'] if self.expanded['inspector'] else 0
        available = max(0, self.splitter.width())
        # Keep the middle pane as the expanding remainder. Qt enforces the
        # minimum widths if a restored window is narrower than before.
        center = max(390, available - left - right - self.splitter.handleWidth() * 2)
        self.splitter.setSizes([left, center, right])

    def set_expanded(self, side, expanded):
        if side not in self.panels:
            raise ValueError('Unknown sidebar: ' + str(side))
        expanded = bool(expanded)
        if self.expanded[side] == expanded:
            self._update_buttons()
            return
        if not self._adjusting:
            self._capture_widths()
        self.expanded[side] = expanded
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
