"""Segment pre-render: a change only makes the changed segment's frames again.

The preview keeps ready-made frames per element (counted from the element's
own start) and per camera move, so editing one element, or making it longer,
does not throw away the frames of the others.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage

APP = QApplication.instance() or QApplication([])
HERE = Path(__file__).parent


class CacheTests(unittest.TestCase):
    def test_memory_and_disk_tiers(self):
        from preview_cache import SegmentCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = SegmentCache(tmp, memory_budget=3 * 200 * 100 * 4, disk_budget=10 ** 9)
            opaque = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
            opaque.fill(QColor('#336699'))
            clear = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
            clear.fill(0)
            cache.put(('a',), 0, 200, opaque, disk=True)
            cache.put(('a',), 1, 200, clear, disk=True)
            self.assertIs(cache.get(('a',), 0, 200), opaque)
            names = sorted(p.suffix for p in Path(tmp).iterdir())
            self.assertEqual(names, ['.raw', '.raw'])           # raw pixels: fast to read back (exp.101)
            for i in range(2, 6):                                 # memory overflows: oldest leave
                cache.put(('b',), i, 200, opaque)
            self.assertLessEqual(cache._memory_bytes, cache.memory_budget)
            again = cache.get(('a',), 1, 200)                     # comes back from disk
            self.assertIsNotNone(again)
            self.assertEqual(again.pixelColor(10, 10).alpha(), 0)
            fresh = SegmentCache(tmp)                             # a new session finds them too
            self.assertTrue(fresh.has(('a',), 0, 200))
            self.assertFalse(fresh.has(('a',), 0, 100))           # another width is another frame

    def test_raw_frames_come_back_exactly_and_quickly(self):
        import time
        from preview_cache import SegmentCache, memory_budget
        self.assertGreaterEqual(memory_budget(), 600 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            cache = SegmentCache(tmp, memory_budget=1, disk_budget=10 ** 9)
            frame = QImage(960, 540, QImage.Format.Format_ARGB32_Premultiplied)
            frame.fill(QColor(30, 120, 200, 128))
            cache.put(('v',), 0, 960, frame, disk=True)
            cache.forget_memory()
            began = time.perf_counter()
            back = cache.get(('v',), 0, 960)
            spent = time.perf_counter() - began
            self.assertEqual(back.size(), frame.size())
            self.assertEqual(back.pixelColor(5, 5), frame.pixelColor(5, 5))
            self.assertLess(spent, .1)
            old = Path(tmp) / (cache.name(('w',), 0, 960) + '.png')      # older versions: PNG
            frame.save(str(old)); cache._disk = None
            self.assertIsNotNone(cache.get(('w',), 0, 960))

    def test_disk_budget_removes_the_oldest(self):
        from preview_cache import SegmentCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = SegmentCache(tmp, disk_budget=1)
            image = QImage(50, 50, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor('red'))
            cache.put(('x',), 0, 50, image, disk=True)
            cache.put(('x',), 1, 50, image, disk=True)
            self.assertLessEqual(len(list(Path(tmp).iterdir())), 1)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['STROKESCRIBE_PREVIEW_CACHE'] = self.tmp.name
        from app import Window
        from engine import import_svg
        self.w = Window()
        self.w.show()
        w = self.w
        w.duration.setValue(1.)
        w.add_scene()
        w.set_drawing(import_svg(HERE / 'samples' / 'arthur-headset-traced.svg'))
        w.duration.setValue(1.)
        w.preview_scope.setCurrentIndex(1)                      # the whole video
        APP.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close()
        APP.processEvents()
        os.environ.pop('STROKESCRIBE_PREVIEW_CACHE', None)
        self.tmp.cleanup()

    def prerender_everything(self):
        w = self.w
        ready, total = w.ready_frames()
        for _ in range(total + 5):
            w.prerender_step()
        return w.ready_frames()

    def ready_in(self, k):
        """(ready, total) frames of element k in the whole-video view."""
        w = self.w
        ready = total = 0
        count = w.frame_index(1.)[1]
        for i in range(count + 1):
            segment, local, frames, where, kk = w.segment_at(i)
            if where == 'scene' and kk == k:
                total += 1
                ready += w.segment_cache.has(segment, local, w.PREVIEW_WIDTH)
        return ready, total

    def test_changing_one_element_keeps_the_others_ready(self):
        w = self.w
        ready, total = self.prerender_everything()
        self.assertEqual(ready, total)
        self.assertEqual(w.scene_index, 1)
        # A look change in element 2: element 1 stays ready, element 2 is made again.
        w.thickness.setValue(2.)
        APP.processEvents()
        first, first_total = self.ready_in(0)
        second, second_total = self.ready_in(1)
        self.assertEqual(first, first_total)
        self.assertEqual(second, 0)
        self.assertGreater(second_total, 0)

    def test_longer_element_does_not_redo_the_later_one(self):
        w = self.w
        self.prerender_everything()
        w.scene_list.setCurrentRow(0)                           # edit element 1
        APP.processEvents()
        self.assertEqual(w.scene_index, 0)
        self.prerender_everything()
        before, total_before = self.ready_in(1)
        self.assertEqual(before, total_before)
        w.duration.setValue(2.)                                 # element 1 gets longer
        APP.processEvents()
        after, total_after = self.ready_in(1)
        self.assertEqual(after, total_after)                     # element 2 moved, still ready

    def test_ready_frames_are_the_same_pictures_as_fresh_ones(self):
        w = self.w
        self.prerender_everything()
        count = w.frame_index(1.)[1]
        for i in (0, count // 3, count // 2, count - 1):
            segment, local, frames, where, k = w.segment_at(i)
            cached = w.segment_cache.get(segment, local, w.PREVIEW_WIDTH)
            fresh = w.render_segment(where, k, local, frames, w.PREVIEW_WIDTH)
            self.assertEqual(cached.convertToFormat(fresh.format()), fresh, (i, where, k))

    def test_a_stale_held_button_does_not_stop_prerender_forever(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        w = self.w
        with mock.patch.object(QApplication, 'mouseButtons', return_value=Qt.MouseButton.LeftButton):
            for _ in range(30):
                w.prerender_step()
        self.assertGreater(w.ready_frames()[0], 0)

    def test_prerender_button_sits_next_to_library(self):
        w = self.w
        bar = w.library_button.parentWidget().layout()
        self.assertIs(w.prerender_button.parentWidget(), w.library_button.parentWidget())
        self.assertEqual(bar.indexOf(w.prerender_button), bar.indexOf(w.library_button) + 1)
        self.assertTrue(w.prerender_button.isVisible())

    def test_prerender_button_runs_and_finishes(self):
        w = self.w
        w.prerender_whole()
        self.assertTrue(w._prerender_all)
        self.assertTrue(w.prerender_button.text().startswith('Stop pre-render'))
        count = w.frame_index(1.)[1]
        for _ in range(count + 10):
            w.prerender_step()
            if not w._prerender_all:
                break
        self.assertFalse(w._prerender_all)
        self.assertEqual(w.prerender_button.text(), 'Pre-render')
        self.assertTrue(any(Path(self.tmp.name).iterdir()))     # kept on disk as well


if __name__ == '__main__':
    unittest.main(verbosity=2)


class EditorSmoothnessTests(unittest.TestCase):
    def test_dragging_opacity_does_not_redraw_on_every_step(self):
        from unittest import mock
        from PySide6.QtTest import QTest
        from app import Window
        from element_dialog import ElementDialog
        w = Window(); w.show(); APP.processEvents()
        dialog = ElementDialog(w, w.scene_index)
        try:
            with mock.patch.object(w, 'build_view', wraps=w.build_view) as views:
                for value in range(100, 50, -1):                 # 50 slider steps
                    dialog.opacity.setValue(value)
                self.assertEqual(w.artwork_opacity.value(), 51)  # values arrive at once
                self.assertLessEqual(views.call_count, 1)        # no rebuild per step
                QTest.qWait(150)
                self.assertGreaterEqual(views.call_count, 1)     # one redraw afterwards
                self.assertLessEqual(views.call_count, 3)
            self.assertEqual(w._view['options']['artwork_opacity'], 51)
        finally:
            dialog.reject()
            w.close()
