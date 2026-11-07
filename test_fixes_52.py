"""exp.52: deleting scenes, the log, and a calm mouse wheel."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

HERE = Path(__file__).parent


class LogTests(unittest.TestCase):
    def test_errors_are_written_with_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get('STROKESCRIBE_CONFIG_DIR')
            os.environ['STROKESCRIBE_CONFIG_DIR'] = tmp
            try:
                import applog
                applog.log.handlers.clear(); applog.log._ready = False; applog._recent.clear()
                applog.setup()
                seen = []
                applog._on_error.append(seen.append)
                try:
                    [][3]
                except IndexError as exc:
                    applog.error('Test problem', exc)
                applog.error('Test problem', IndexError('list index out of range'))   # the same: written once
                for h in applog.log.handlers:
                    h.flush()
                text = applog.log_file().read_text(encoding='utf-8')
                self.assertIn('Test problem', text)
                self.assertIn('Traceback', text)
                self.assertIn('IndexError', text)
                self.assertEqual(len(seen), 1)
                self.assertIn('Test problem', applog.tail())
                applog._on_error.remove(seen.append)
            finally:
                for h in list(applog.log.handlers):
                    h.close(); applog.log.removeHandler(h)
                applog.log._ready = False
                if old is None:
                    os.environ.pop('STROKESCRIBE_CONFIG_DIR', None)
                else:
                    os.environ['STROKESCRIBE_CONFIG_DIR'] = old


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app import Window
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); self.app.processEvents()
        from PySide6.QtWidgets import QMessageBox
        self._question = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

    def tearDown(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.question = self._question
        self.w.playing = False
        self.w.close(); self.app.processEvents()

    def test_delete_scenes_one_after_another(self):
        from engine import import_svg
        w = self.w
        w.duration.setValue(1.)
        w.add_scene(); w.set_drawing(import_svg(HERE / 'samples' / 'arthur-headset-traced.svg'))
        w.add_scene(); w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
        self.assertEqual((len(w.scenes), w.scene_index), (3, 2))
        w.delete_scene()                                   # the last one (what went wrong)
        self.assertEqual((len(w.scenes), w.scene_index), (2, 1))
        self.assertIsNone(w.scenes[1]['state'])            # scene 2 is in the editor
        self.assertIsNotNone(w.scenes[0]['state'])
        w.delete_scene()                                   # and the next one
        self.assertEqual((len(w.scenes), w.scene_index), (1, 0))
        self.assertFalse(w.scene_delete.isEnabled())
        # Playing and autosave still work.
        w.slider.setValue(500)
        self.assertFalse(w.canvas.frame.isNull())
        w.color_hold.setValue(w.color_hold.value() + .5); w.commit_history()
        self.assertNotIn('failed', w.status.text().lower())
        self.assertTrue(w.autosave_tick() in (True, False))
        self.assertNotIn('failed', w.status.text().lower())
        # Middle scene deleted from three.
        w.add_scene(); w.add_scene()
        w.scene_list.setCurrentRow(1)
        w.delete_scene()
        self.assertEqual((len(w.scenes), w.scene_index), (2, 1))
        self.assertEqual(sum(s['state'] is None for s in w.scenes), 1)

    def test_wheel_scrolls_the_panel_not_the_list(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication
        w = self.w
        box = w.reveal_mode
        before = box.currentIndex()
        self.assertEqual(box.focusPolicy(), Qt.FocusPolicy.StrongFocus)

        def wheel(widget):
            event = QWheelEvent(QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                                QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(widget, event)
        w.setFocus(); self.app.processEvents()
        wheel(box)
        self.assertEqual(box.currentIndex(), before)      # not changed by the wheel
        box.setFocus(); self.app.processEvents()
        if box.hasFocus():                                # after a click (focus) the wheel works
            wheel(box)
            self.assertNotEqual(box.currentIndex(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
