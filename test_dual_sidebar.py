"""Dual-sidebar UI (experimental.76): Handwriting left, Source and the other
panels right, and panel content driven by the selected element's kind.

Checks the corrections: no project selector / resolution / FPS in the top bar;
no imports in Handwriting; lettering is never shown as an imported image or
file; thumbnail, transforms and blend mode only for imported artwork; Pen
movement stays in Animation; Lines & order works from Animation.
"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')

from PySide6.QtWidgets import QApplication, QPushButton
from app import Window
from studio_workspace import TABS

APP = QApplication.instance() or QApplication([])


class DualSidebarTests(unittest.TestCase):
    def setUp(self):
        self.w = Window()
        self.w.resize(1490, 890)
        self.w.show()
        APP.processEvents()
        APP.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close()
        APP.processEvents()

    def page(self, key):
        return self.w.inspector_tabs.widget(TABS[key])

    def make_lettering(self, text='Hello world!'):
        w = self.w
        w.text.setPlainText(text)
        w.font_select.setCurrentIndex(0)          # built-in pen: offline
        w.letter()
        APP.processEvents()
        APP.processEvents()

    def test_top_bar_has_no_project_selector_or_output_summary(self):
        w = self.w
        self.assertFalse(w.project_menu.isVisible())
        self.assertFalse(w.output_summary.isVisible())
        # Their functions are still reachable: File menu and Export.
        file_items = [a.text().split('\t')[0] for a in w.menus['file'].actions()]
        for item in ('Open project…', 'Save project', 'Save project as…',
                     'Import SVG artwork…', 'Import PNG / JPG artwork…', 'Batch export…'):
            self.assertIn(item, file_items)
        self.assertTrue(self.page('export').isAncestorOf(w.res))
        self.assertTrue(self.page('export').isAncestorOf(w.fps))

    def test_imports_only_in_source(self):
        w = self.w
        left = w.handwriting_panel
        imports = [b for b in left.findChildren(QPushButton) if 'Import SVG' in b.text()
                   or 'Import image' in b.text()]
        self.assertEqual(imports, [])
        self.assertTrue(self.page('source').isAncestorOf(w.import_button))
        self.assertTrue(self.page('source').isAncestorOf(w.import_image_button))
        self.assertTrue(self.page('source').isAncestorOf(w.image_controls))
        # The font importer is not an artwork import and stays with the text.
        self.assertTrue(left.isAncestorOf(w.import_font_button))
        for name in ('text', 'font_select', 'font_size', 'font_color_button', 'generate_text'):
            self.assertTrue(left.isAncestorOf(getattr(w, name)), name)

    def test_pen_movement_and_lines_live_in_animation(self):
        w = self.w
        animation = self.page('animation')
        for name in ('pen_ease', 'camera', 'duration', 'lines_toggle', 'order', 'line_pace'):
            self.assertTrue(animation.isAncestorOf(getattr(w, name)), name)
        self.assertEqual([w.pen_ease.itemText(i) for i in range(w.pen_ease.count())],
                         ['Constant speed', 'Natural (ease in and out)'])
        self.assertFalse(w.handwriting_panel.isAncestorOf(w.lines_group))

    def test_imported_svg_shows_card_transform_and_appearance(self):
        w = self.w
        self.assertEqual(w.element_kind(), 'svg')          # the bundled sample
        w.show_right_panel('source')
        APP.processEvents()
        source = self.page('source')
        self.assertTrue(source.isAncestorOf(w.placement_box))
        self.assertFalse(w.handwriting_panel.isAncestorOf(w.placement_box))
        self.assertTrue(w.source_transform_heading.isVisible())
        self.assertFalse(w.handwriting_placement_heading.isVisible())
        self.assertEqual(w.source_card_title.text(), 'SVG drawing')
        self.assertTrue(w.source_card_thumb.isVisible())
        self.assertFalse(w.edit_handwriting_button.isVisible())
        self.assertTrue(w.blend_mode.isVisible())
        self.assertTrue(w.artwork_opacity.isVisible())
        self.assertFalse(w.paper_cleanup.isVisible())         # images only
        self.assertTrue(w.load_color_button.isVisible())
        self.assertTrue(w.clean_color.isVisible())

    def test_lettering_is_not_an_imported_image(self):
        w = self.w
        self.make_lettering('Hello world!')
        self.assertEqual(w.element_kind(), 'lettering')
        w.show_right_panel('source')
        APP.processEvents()
        # Source: a handwriting card, no thumbnail, no file name.
        self.assertEqual(w.source_card_title.text(), 'Handwriting element')
        detail = w.source_card_detail.text()
        self.assertIn('Hello world!', detail)
        for invented in ('.svg', '.png', 'Sample drawing'):
            self.assertNotIn(invented, detail)
        self.assertFalse(w.source_card_thumb.isVisible())
        pixmap = w.source_card_thumb.pixmap()
        self.assertTrue(pixmap is None or pixmap.isNull())
        self.assertTrue(w.edit_handwriting_button.isVisible())
        # No image transforms or per-image blend mode in Source for lettering.
        self.assertFalse(w.source_transform_heading.isVisible())
        self.assertFalse(w.blend_mode.isVisible())
        self.assertFalse(w.artwork_opacity.isVisible())
        self.assertFalse(w.load_color_button.isVisible())
        self.assertFalse(w.image_controls.isVisible())
        # Size and position are in Handwriting → Placement instead.
        self.assertTrue(w.handwriting_panel.isAncestorOf(w.placement_box))
        self.assertTrue(w.handwriting_placement_heading.isVisible())
        self.assertTrue(w.artwork_size.isVisible())
        # Saved with its kind; 'source' keeps its old value for compatibility.
        state = w.scene_state()
        self.assertEqual(state['element_kind'], 'lettering')
        self.assertEqual(state['source'], 'svg')

    def test_edit_in_handwriting_reopens_the_left_panel(self):
        w = self.w
        self.make_lettering('Hi')
        w.sidebar_layout.set_expanded('source', False)
        APP.processEvents()
        self.assertTrue(w.handwriting_panel.isHidden())
        w.show_right_panel('source')
        w.edit_handwriting_button.click()
        APP.processEvents()
        self.assertFalse(w.handwriting_panel.isHidden())

    def test_menu_view_entries_open_panels(self):
        w = self.w
        w.sidebar_layout.set_expanded('inspector', False)
        APP.processEvents()
        view = {a.text(): a for a in w.menus['view'].actions()}
        view['Source panel'].trigger()
        APP.processEvents()
        self.assertFalse(w.workspace_splitter.widget(2).isHidden())
        self.assertEqual(w.inspector_tabs.currentIndex(), TABS['source'])
        view['Animation settings'].trigger()
        self.assertEqual(w.inspector_tabs.currentIndex(), TABS['animation'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
