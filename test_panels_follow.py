"""exp.241 (UI clean-up step 5): an open side panel shows the selected element."""
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import artwork_workflow
from element_kinds import IMAGE, LETTERING
from studio_workspace import LEFT, TABS


class FakeLayout:
    def __init__(self, left, right):
        self.expanded = {'source': left, 'inspector': right}

    def set_expanded(self, key, value):
        self.expanded[key] = value


class FakeTabs:
    def __init__(self, index):
        self.index = index

    def currentIndex(self):
        return self.index


def make(kind, left, ltab, right, rtab):
    w = mock.Mock()
    w.drawing = object()
    w.sidebar_layout = FakeLayout(left, right)
    w.left_tabs = FakeTabs(LEFT[ltab])
    w.inspector_tabs = FakeTabs(TABS[rtab])
    w.element_kind = lambda: kind
    w.show_right_panel = lambda key: (w.sidebar_layout.set_expanded('inspector', True), setattr(w, 'right', key))
    w.show_left_panel = lambda key: (w.sidebar_layout.set_expanded('source', True), setattr(w, 'left', key))
    return w


FOLLOW = next(v for v in vars(artwork_workflow).values()
              if isinstance(v, type) and hasattr(v, 'follow_selection_panels')).follow_selection_panels


class Follow(unittest.TestCase):
    def test_picture_closes_the_text_panel_and_opens_image(self):
        w = make(IMAGE, True, 'text', False, 'animation')
        FOLLOW(w)
        self.assertFalse(w.sidebar_layout.expanded['source'])
        self.assertEqual(w.right, 'source')

    def test_an_open_right_panel_keeps_its_page(self):
        w = make(IMAGE, True, 'text', True, 'hand')
        FOLLOW(w)
        self.assertFalse(w.sidebar_layout.expanded['source'])
        self.assertFalse(isinstance(getattr(w, 'right', None), str))

    def test_other_left_panels_stay(self):
        w = make(IMAGE, True, 'music', False, 'animation')
        FOLLOW(w)
        self.assertTrue(w.sidebar_layout.expanded['source'])

    def test_lettering_opens_the_text_panel_beside_image(self):
        w = make(LETTERING, False, 'text', True, 'source')
        FOLLOW(w)
        self.assertEqual(w.left, 'text')

    def test_closed_panels_stay_closed(self):
        w = make(LETTERING, False, 'text', False, 'source')
        FOLLOW(w)
        self.assertFalse(w.sidebar_layout.expanded['source'])
        self.assertFalse(w.sidebar_layout.expanded['inspector'])


if __name__ == '__main__':
    unittest.main()
