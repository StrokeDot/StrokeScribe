"""Source mode consistency: Image source must never clip behind the sidebar.

Since experimental.76 lettering controls live in the left Handwriting panel and
every import / image setting lives in the right Source page; both are checked.

The .71 regression tests checked QComboBox width but not whether the *right*
end was inside the Source scroll viewport. Image settings used a nested form
that could be wider than the scroll viewport, hiding the arrow and controls.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QLabel, QVBoxLayout
from PySide6.QtTest import QTest

from app import Window

APP = QApplication.instance() or QApplication([])


class SourceModeConsistencyTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("STROKESCRIBE_TEST_AUTODISCARD", "1")
        self.window=Window()
        self.window.resize(1490,890)
        self.window.show()
        APP.processEvents()
        APP.processEvents()
        from studio_workspace import TABS
        self.handwriting=self.window.workspace_splitter.widget(0).findChild(QScrollArea)
        self.window.show_right_panel('source')
        APP.processEvents()
        self.source=self.window.inspector_tabs.widget(TABS['source'])
        self.assertIsInstance(self.source,QScrollArea)
        self.assertIsNotNone(self.handwriting)
        self.scroll=self.source

    def tearDown(self):
        self.window.playing=False
        self.window.close()
        APP.processEvents()

    def assert_inside_source_viewport(self, widget, name, scroll=None):
        self.scroll=scroll or self.source
        self.assertFalse(widget.isHidden(), name+" unexpectedly hidden")
        self.scroll.ensureWidgetVisible(widget, 0, 0)
        APP.processEvents()
        point=widget.mapTo(self.scroll.viewport(), QPoint(0,0))
        viewport_width=self.scroll.viewport().width()
        self.assertGreaterEqual(widget.width(), 84, name+" unusable width")
        self.assertGreaterEqual(point.x(), -2, name+" outside source left")
        self.assertLessEqual(point.x()+widget.width(), viewport_width+2,
                             name+" overflows and hides its right-hand arrow")
        self.assertGreater(widget.height(), 18, name+" unusable height")

    def test_both_source_modes_fit_at_small_and_large_sidebar_widths(self):
        w=self.window
        for window_width, window_height in ((1040,768),(1490,890),
                                            (1920,1080),(2560,1440)):
            w.resize(window_width,window_height)
            APP.processEvents()
            for sidebar_width in (225,280,350,450):
                split=w.workspace_splitter
                split.moveSplitter(sidebar_width,1)
                split.moveSplitter(split.width()-max(270,sidebar_width),2)
                APP.processEvents()
                self.assertGreater(self.handwriting.viewport().width(), 140)
                self.assertGreater(self.source.viewport().width(), 140)
                w.source_type.setCurrentIndex(0)
                APP.processEvents()
                self.assert_inside_source_viewport(w.import_button,"Import SVG")
                self.assert_inside_source_viewport(w.import_image_button,"Import image")
                for name in ("font_select","font_size","font_color_button"):
                    self.assert_inside_source_viewport(getattr(w,name), name, self.handwriting)
                w.source_type.setCurrentIndex(1)
                APP.processEvents()
                self.assertIsInstance(w.image_source_form,QVBoxLayout)
                for name in ("import_button","image_animation_style","image_style",
                             "image_detail","clean_faint","preserve_colors",
                             "rebuild_button","ai_lineart_button","own_lines_button",
                             "export_svg_button"):
                    self.assert_inside_source_viewport(getattr(w,name),name)
                # No phantom horizontal canvas bigger than the scroll viewport.
                self.assertLessEqual(self.scroll.widget().width(),
                                     self.scroll.viewport().width()+2)

    def test_image_mode_labels_and_fields_are_near_and_clickable(self):
        w=self.window
        w.workspace_splitter.moveSplitter(230,1)
        w.source_type.setCurrentIndex(1)
        APP.processEvents()
        controls=(("Animation",w.image_animation_style),
                  ("Drawing style",w.image_style),
                  ("Detail",w.image_detail))
        for name, combo in controls:
            self.assert_inside_source_viewport(combo,name)
            label=next((l for l in w.image_controls.findChildren(QLabel)
                        if l.text()==name),None)
            self.assertIsNotNone(label, name+" label missing")
            self.assertTrue(label.isVisible())
            self.assertLessEqual(combo.y()-label.y()-label.height(),18,
                                 name+" label too far from dropdown")
            before=combo.currentIndex()
            target=(before+1)%combo.count()
            combo.showPopup()
            APP.processEvents()
            view=combo.view()
            self.assertTrue(view.isVisible(), name+" dropdown popup hidden")
            index=view.model().index(target,0)
            view.scrollTo(index)
            APP.processEvents()
            QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier,
                             view.visualRect(index).center())
            APP.processEvents()
            self.assertEqual(combo.currentIndex(),target,
                             name+" popup did not update selection")
            combo.hidePopup()

    def test_switching_modes_does_not_change_existing_settings(self):
        w=self.window
        w.source_type.setCurrentIndex(1)
        w.image_detail.setCurrentText("Max")
        w.image_style.setCurrentText("Detailed (all lines)")
        w.source_type.setCurrentIndex(0)
        w.source_type.setCurrentIndex(1)
        self.assertEqual(w.image_detail.currentText(),"Max")
        self.assertEqual(w.image_style.currentText(),"Detailed (all lines)")
        self.assertTrue(w.workspace_splitter.widget(1).isVisible())
        self.assertTrue(w.stage_timeline.isVisible())


if __name__=="__main__":
    unittest.main(verbosity=2)
