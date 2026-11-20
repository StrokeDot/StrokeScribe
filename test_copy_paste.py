"""exp.57 (the user): Ctrl+C / Ctrl+V for what is chosen, in This element, Whole video and Board;
and a new element goes where the playhead is (not after the last element), the end still a choice."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def pump(n=15):
    for _ in range(n): APP.processEvents()


class Base(unittest.TestCase):
    def setUp(self):
        import clipboard_edit
        from app import Window
        from engine import import_svg
        clipboard_edit.CLIPBOARD.clear()
        self.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg')); pump()
        for name in ('B', 'C'):
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); pump()
            w.scenes[w.scene_index]['name'] = name
        w.scenes[0]['name'] = 'A'
        w.store_scene(thumbnail=False)
        w.preview_scope.setCurrentIndex(1); pump()

    def tearDown(self):
        self.w.close()

    def playhead_in(self, k, share=.5):
        lay = self.w.timeline_layout()
        it = lay.items[k]
        self.w.position = (it.start + it.length * share) / lay.total

    def keys(self, widget, key):
        widget.setFocus(); pump(3)
        QTest.keyClick(widget, key, Qt.KeyboardModifier.ControlModifier); pump()


class NewElementAtThePlayhead(Base):
    def test_the_slot_is_the_element_under_the_playhead(self):
        self.playhead_in(0)
        self.assertEqual(self.w.playhead_slot(), (0, None))
        self.playhead_in(1)
        self.assertEqual(self.w.playhead_slot(), (1, None))

    def test_a_copy_goes_after_the_element_under_the_playhead(self):
        w = self.w
        w.select_scene(2)                    # C chosen, playhead in A
        self.playhead_in(0)
        k, start = w.playhead_slot()
        w.add_element_at(k, start, 'copy', False)
        self.assertEqual(len(w.scenes), 4)
        self.assertEqual(w.scene_index, 1)
        self.assertEqual([w.scenes[i].get('name') for i in (0, 2, 3)], ['A', 'B', 'C'])

    def test_in_empty_time_it_starts_at_the_playhead(self):
        w = self.w
        lay = w.timeline_layout()
        w.video_end = lay.total + 6.; w.__dict__.pop('_memo', None)
        lay = w.timeline_layout()
        t = lay.total - 2.
        w.position = t / lay.total
        k, start = w.playhead_slot()
        self.assertEqual(k, 2)
        self.assertAlmostEqual(start, round(t, 2))
        w.add_element_at(k, start, 'copy', False)
        self.assertEqual(w.scene_index, 3)
        w.__dict__.pop('_memo', None)
        self.assertAlmostEqual(w.timeline_layout().items[3].start, round(t, 2))

    def test_in_the_board(self):
        w = self.w
        idx = next(i for i in range(w.preview_scope.count()) if 'oard' in w.preview_scope.itemText(i))
        w.preview_scope.setCurrentIndex(idx); pump()
        self.assertTrue(w.board_mode())
        w.select_scene(2); self.playhead_in(0)
        w.copy_selection(w.stage_timeline); w.paste_selection(w.stage_timeline); pump()
        self.assertEqual(len(w.scenes), 4)
        self.assertEqual(w.scenes[1].get('name'), 'C')

    def test_the_end_is_still_a_choice(self):
        w = self.w
        self.playhead_in(0)
        w.add_element_at(len(w.scenes) - 1, None, 'copy', False)
        self.assertEqual(w.scene_index, 3)

    def test_the_strip_plus_does_not_jump_to_the_last_element(self):
        w = self.w
        w.select_scene(0)
        opened = []
        w.add_element_menu = lambda *a, **k: opened.append(w.scene_index)
        w._strip_menu_at = None
        w.strip_plus_clicked()
        self.assertEqual(opened, [0])


class CopyPaste(Base):
    def test_an_element_with_the_keys(self):
        w = self.w
        w.select_scene(2); self.playhead_in(0)
        tl = w.stage_timeline
        self.keys(tl, Qt.Key.Key_C)
        self.keys(tl, Qt.Key.Key_V)
        self.assertEqual(len(w.scenes), 4)
        self.assertEqual(w.scene_index, 1)
        self.assertEqual(w.scenes[1].get('name'), 'C')
        w.undo(); pump()
        self.assertEqual(len(w.scenes), 3)

    def test_a_text_on_top(self):
        w = self.w
        w.add_overlay_text() if False else None
        import overlays
        item = overlays.new_text('Hello', 1., 2.)
        w.overlays.append(item); w.select_overlay(item['id']); pump()
        self.keys(w.stage_timeline, Qt.Key.Key_C)
        self.playhead_in(2)
        t = w.video_seconds()
        self.keys(w.stage_timeline, Qt.Key.Key_V)
        self.assertEqual(len(w.overlays), 2)
        twin = w.overlays[-1]
        self.assertNotEqual(twin['id'], item['id'])
        self.assertAlmostEqual(twin['start'], round(t, 2), places=2)
        self.assertEqual(twin['text'], 'Hello')

    def test_a_hand_motion(self):
        w = self.w
        self.playhead_in(0)
        clip = w.add_camera_clip('Hand motion'); pump()
        n = len(w.cameras)
        self.keys(w.stage_timeline, Qt.Key.Key_C)
        self.playhead_in(2, .2)
        t = w.video_seconds()
        self.keys(w.stage_timeline, Qt.Key.Key_V)
        self.assertEqual(len(w.cameras), n + 1)
        twin = w.cameras[-1]
        self.assertEqual(twin['kind'], clip['kind'])
        self.assertNotEqual(twin['id'], clip['id'])
        self.assertAlmostEqual(twin['start'], round(min(t, w.video_length() - twin['duration']), 2), places=2)

    def test_lines_inside_the_element(self):
        w = self.w
        w.preview_scope.setCurrentIndex(0); pump()
        n = len(w.drawing.strokes)
        w.order.clearSelection(); w.order.item(0).setSelected(True); w.order.item(1).setSelected(True)
        self.keys(w.order, Qt.Key.Key_C)
        self.keys(w.order, Qt.Key.Key_V)
        self.assertEqual(len(w.drawing.strokes), n + 2)

    def test_typing_keeps_its_own_copy(self):
        import clipboard_edit
        from PySide6.QtWidgets import QLineEdit
        w = self.w
        box = QLineEdit(w); box.setText('abc'); box.show(); box.selectAll()
        self.keys(box, Qt.Key.Key_C)
        self.assertEqual(clipboard_edit.CLIPBOARD, {})


if __name__ == '__main__':
    unittest.main()
