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



class OneAddPlace(unittest.TestCase):
    """exp.242: "+ Add element" lists everything that can be added."""

    def test_the_add_menu_has_elements_timeline_things_and_sound(self):
        from PySide6 import QtWidgets
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        seen = []

        class Menu(QtWidgets.QMenu):          # records instead of opening
            def exec(self, *args):
                seen.append([x.text() for x in self.actions() if x.text()])

        with mock.patch.object(QtWidgets, 'QMenu', Menu):
            w.add_element_menu(False)
        self.assertTrue(seen)
        texts = seen[-1]
        for wanted in ('Picture or SVG file…', 'Text (handwriting)…', 'Camera move or zoom…',
                       'Hand motion', 'Eraser…', 'Music…'):
            self.assertIn(wanted, texts)


if __name__ == '__main__':
    unittest.main()
