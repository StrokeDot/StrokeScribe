"""exp.97: Filmora-style pre-render — a red/green bar over the timeline, a progress
window with the frame count, time left and Cancel, and the render deleted when
StrokeScribe closes (unless "Keep the render" is on)."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


@unittest.skipIf(SKIP, 'needs Qt')
class PrerenderWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['STROKESCRIBE_PREVIEW_CACHE'] = self.tmp.name
        from prerender_dialog import set_keep_render
        set_keep_render(False)
        from app import Window
        from engine import import_svg
        self.w = Window()
        self.w.show()
        self.w.duration.setValue(1.)
        self.w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        self.w.duration.setValue(1.)
        self.app.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close()
        self.app.processEvents()
        os.environ.pop('STROKESCRIBE_PREVIEW_CACHE', None)
        self.tmp.cleanup()

    def run_prerender(self):
        w = self.w
        w.prerender_whole()
        count = w.frame_index(1.)[1]
        for _ in range(count + 10):
            w.prerender_step()
            if not w._prerender_all:
                break
        self.app.processEvents()

    def test_window_shows_progress_and_closes_when_done(self):
        w = self.w
        w.prerender_whole()
        dialog = w.prerender_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        w.prerender_step(); w.prerender_step(); w.prerender_step()
        self.assertIn('Rendering frame', dialog.frames.text())
        self.assertIn('/', dialog.frames.text())
        for _ in range(w.frame_index(1.)[1] + 10):
            w.prerender_step()
            if not w._prerender_all:
                break
        self.app.processEvents()
        self.assertIsNone(w.prerender_dialog)                       # closed by itself when done
        self.assertEqual(w.prerender_button.text(), 'Pre-render')

    def test_a_frame_that_fails_is_skipped_not_stuck(self):
        """exp.101: one frame raising an error stopped pre-render on "Rendering frame 1"
        for ever, without a word. Now it is said, skipped, and the rest is made."""
        from unittest import mock
        w = self.w
        real = w.render_segment
        calls = {'n': 0}

        def flaky(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise ValueError('The color image has no nontransparent pixels.')
            return real(*args, **kwargs)
        with mock.patch.object(w, 'render_segment', side_effect=flaky):
            w.prerender_whole()
            dialog = w.prerender_dialog
            w.prerender_step()
            self.assertTrue(w._prerender_all)                        # still going
            self.assertFalse(dialog.problem.isHidden())
            self.assertIn('could not be made', dialog.problem.text())
            for _ in range(w.frame_index(1.)[1] + 10):
                w.prerender_step()
                if not w._prerender_all:
                    break
        self.assertFalse(w._prerender_all)                           # finished
        ready, total = w.ready_frames()
        self.assertEqual(ready, total - 1)                           # all but the one that failed

    def test_cancel_stops(self):
        w = self.w
        w.prerender_whole()
        w.prerender_step()
        w.prerender_dialog.reject(); self.app.processEvents()
        self.assertFalse(w._prerender_all)
        self.assertIn('stopped', w.status.text())

    def test_render_bar_red_then_green(self):
        w = self.w
        w.segment_cache.clear_disk()
        w.segment_cache._memory.clear() if hasattr(w.segment_cache, '_memory') else None
        runs, count = w.render_runs()
        self.assertGreater(count, 0)
        self.run_prerender()
        runs, count = w.render_runs()
        self.assertEqual(runs, [(0, count - 1, True)])               # all green
        w.update_render_bar()
        self.assertEqual(w.stage_timeline.render_runs, runs)
        w.thickness.setValue(w.thickness.value() + 1)                # a change: red again
        self.app.processEvents(); w.build_view() if hasattr(w, 'build_view') else None
        runs, count = w.render_runs()
        self.assertTrue(any(not ready for _, _, ready in runs))

    def test_render_is_deleted_when_closing(self):
        w = self.w
        self.run_prerender()
        self.assertTrue(any(Path(self.tmp.name).rglob('*.*')))      # on disk while open
        w.close(); self.app.processEvents()
        self.assertFalse(any(p.is_file() for p in Path(self.tmp.name).rglob('*')))

    def test_keep_render_setting(self):
        from prerender_dialog import keep_render, set_keep_render
        set_keep_render(True)
        self.assertTrue(keep_render())
        set_keep_render(False)
        self.assertFalse(keep_render())


if __name__ == '__main__':
    unittest.main()
