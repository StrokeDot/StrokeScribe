"""Regression: selecting image and lettering must not reflow Inspector spin buttons.

Unlike old tests that checked only QWidget.isVisible() and width(), this test
verifies *the entire control* (including its + / - arrow column) falls inside
the actual Inspector scroll viewport after source-dependent rows change.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STROKESCRIBE_TEST_AUTODISCARD", "1")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QFormLayout, QScrollArea
from PySide6.QtTest import QTest
from app import Window

APP=QApplication.instance() or QApplication([])


class InspectorSceneSwitchGeometryTests(unittest.TestCase):
    def setUp(self):
        self.w=Window()
        self.w.resize(1490, 890)
        self.w.show()
        APP.processEvents()
        APP.processEvents()
        self.w.inspector_tabs.setCurrentIndex(0)
        self.area=self.w.inspector_tabs.widget(0)
        self.assertIsInstance(self.area, QScrollArea)
        self.original_image_check=self.w.is_image_artwork

    def tearDown(self):
        self.w.is_image_artwork=self.original_image_check
        self.w.playing=False
        self.w.close()
        APP.processEvents()

    def switch_element_type(self, image):
        # Reproduce source-kind-dependent Inspector row visibility. This is the
        # same production sync_workspace() used when selecting a different
        # project element; no AI/image worker or file I/O is needed.
        self.w.is_image_artwork=lambda: image
        self.w.sync_workspace()
        APP.processEvents()
        APP.processEvents()

    def area_of(self, widget):
        """The right-panel page holding a control, opened (one page at a time).

        Since experimental.76, Size and Position sit in Source → Transform for
        imported artwork (the sample is an SVG) instead of the Animation page.
        """
        tabs=self.w.inspector_tabs
        for i in range(tabs.count()):
            if tabs.widget(i).isAncestorOf(widget):
                if tabs.currentIndex()!=i:
                    tabs.setCurrentIndex(i)
                    APP.processEvents()
                return tabs.widget(i)
        return self.area

    def assert_inside_inspector(self, widget, name):
        self.area=self.area_of(widget)
        self.area.ensureWidgetVisible(widget, 0, 0)
        APP.processEvents()
        self.assertTrue(widget.isVisible(), name+" is not visible")
        self.assertGreaterEqual(widget.width(), 76, name+" has no usable width")
        self.assertGreaterEqual(widget.height(), 20, name+" has no usable height")
        left=widget.mapTo(self.area.viewport(), QPoint(0, 0)).x()
        right=left+widget.width()
        viewport=self.area.viewport().width()
        self.assertGreaterEqual(left, -2, f"{name} begins outside Inspector: {left}")
        self.assertLessEqual(right, viewport+2,
                             f"{name} arrow clipped: right={right}, viewport={viewport}")

    def test_font_to_image_switch_never_clips_spinner_arrows(self):
        w=self.w
        for win_width, win_height in ((1040,768),(1490,890),
                                      (1920,1080),(2560,1440)):
            w.resize(win_width,win_height)
            APP.processEvents()
            for right_width in (270,330,420):
                split=w.workspace_splitter
                split.moveSplitter(split.width()-right_width,2)
                APP.processEvents()
                for image in (False,True,False,True):
                    self.switch_element_type(image)
                    # This is where Experimental.72 could still paint controls
                    # outside the right edge of the visible Inspector.
                    from studio_workspace import TABS
                    for page in (TABS['animation'],TABS['source']):
                        area=w.inspector_tabs.widget(page)
                        w.inspector_tabs.setCurrentIndex(page)
                        APP.processEvents()
                        self.assertLessEqual(area.widget().width(),
                                             area.viewport().width()+2,
                                             "Inspector contents wider than viewport")
                    for name in ("duration","speed","thickness",
                                 "artwork_size","picture_x","picture_y",
                                 "pause_after","pen_ease","entrance",
                                 "reveal_mode"):
                        self.assert_inside_inspector(getattr(w,name), name)
                    # Position X and Y are rows of their own (experimental.81).
                    self.area=self.area_of(w.picture_x)
                    from PySide6.QtCore import QRect
                    rx=QRect(w.picture_x.mapTo(self.area.viewport(),QPoint(0,0)),w.picture_x.size())
                    ry=QRect(w.picture_y.mapTo(self.area.viewport(),QPoint(0,0)),w.picture_y.size())
                    self.assertFalse(rx.intersects(ry),"X/Y position boxes overlap")
                    self.assertTrue(w.canvas.isVisible())
                    self.assertTrue(w.stage_timeline.isVisible())

    def test_spinbox_up_down_arrows_receive_real_mouse_clicks(self):
        w=self.w
        for image in (False,True):
            self.switch_element_type(image)
            for name in ("duration","speed","picture_x","picture_y"):
                spin=getattr(w,name)
                self.assert_inside_inspector(spin,name)
                self.assertTrue(spin.isEnabled(), name+" unexpectedly disabled")
                start=spin.value()
                point=QPoint(spin.width()-10,max(3,spin.height()//4))
                QTest.mouseClick(spin,Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier,point)
                APP.processEvents()
                self.assertGreater(spin.value(),start,
                                   name+" increment arrow was not clickable")
                spin.setValue(start)

    def test_inspector_form_uses_stable_row_layout_on_image_switch(self):
        w=self.w
        # The drawing form must not rewrap when image-specific rows change.
        for image in (False,True,False):
            self.switch_element_type(image)
            self.area=self.area_of(w.duration)
            forms=self.area.widget().findChildren(QFormLayout)
            self.assertGreater(len(forms),2)
            for form in forms:
                self.assertEqual(form.rowWrapPolicy(),
                                 QFormLayout.RowWrapPolicy.DontWrapRows)
            self.assertTrue(w.duration.isVisible())
            self.assertTrue(w.speed.isVisible())
            self.area_of(w.picture_center)
            self.assertTrue(w.picture_center.isVisible())
            self.area=self.area_of(w.duration)
            self.assert_inside_inspector(w.duration,"Draw time")
            self.assert_inside_inspector(w.speed,"Playback speed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
