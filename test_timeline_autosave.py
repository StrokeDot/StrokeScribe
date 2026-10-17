"""exp.44: timeline dragging, the audio lane, autosave/recovery, recent projects,
the update banner and the export-finished sound option."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True

import autosave
import updater


def make_wav(path, seconds=2.0, rate=8000):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(b''.join(struct.pack('<h', int(9000 * math.sin(i / 7) * (i / (rate * seconds))))
                               for i in range(int(rate * seconds))))
    return path


class ConfigDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._old = os.environ.get('STROKESCRIBE_CONFIG_DIR')
        os.environ['STROKESCRIBE_CONFIG_DIR'] = str(self.dir)

    def tearDown(self):
        if self._old is None:
            os.environ.pop('STROKESCRIBE_CONFIG_DIR', None)
        else:
            os.environ['STROKESCRIBE_CONFIG_DIR'] = self._old
        self._tmp.cleanup()


class AutosaveTests(ConfigDir):
    def test_backup_pending_and_clear(self):
        self.assertIsNone(autosave.pending())
        autosave.save({'settings': {'fps': 30}}, project_path='C:/x.strokescribe', title='My video')
        info = autosave.pending()
        self.assertEqual(info['title'], 'My video')
        self.assertEqual(info['project_path'], 'C:/x.strokescribe')
        self.assertTrue(Path(info['path']).is_file())
        import projects
        self.assertEqual(projects.load(info['path'])['settings']['fps'], 30)
        autosave.clear()
        self.assertIsNone(autosave.pending())

    def test_recent_projects_newest_first_without_missing_files(self):
        files = []
        for name in ('a', 'b', 'c'):
            p = self.dir / f'{name}.strokescribe'; p.write_text('{}'); files.append(p)
        for p in files:
            autosave.add_recent(p)
        autosave.add_recent(files[0])                      # opened again: back to the top
        names = [Path(p).stem for p in autosave.recent()]
        self.assertEqual(names, ['a', 'c', 'b'])
        files[2].unlink()
        self.assertEqual([Path(p).stem for p in autosave.recent()], ['a', 'b'])
        for i in range(15):
            p = self.dir / f'n{i}.strokescribe'; p.write_text('{}'); autosave.add_recent(p)
        self.assertEqual(len(autosave.recent()), autosave.MAX_RECENT)


class WhatsNewTests(unittest.TestCase):
    def test_notes_for_version(self):
        readme = ('# StrokeScribe\n\n## Timeline (v0.5.3-experimental.44)\n\n- **Drag** clip edges.\n'
                  '- Audio lane.\n\n## Older (v0.5.3-experimental.43)\n\n- old\n')
        notes = updater.notes_for(readme, '0.5.3-experimental.44')
        self.assertIn('Timeline', notes)
        self.assertIn('Drag clip edges', notes)
        self.assertNotIn('old', notes)
        self.assertEqual(updater.notes_for(readme, '9.9'), '')


@unittest.skipIf(SKIP, 'needs Qt')
class WindowTests(ConfigDir):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app import Window
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); self.app.processEvents()

    def tearDown(self):
        self.w.playing = False
        self.w.close(); self.app.processEvents()
        super().tearDown()

    def test_layout_has_draggable_divider_above_timeline(self):
        from PySide6.QtWidgets import QSplitter
        w = self.w
        v = w.findChild(QSplitter, 'timelineSplit')
        self.assertIsNotNone(v)
        self.assertEqual(v.count(), 2)
        self.assertIs(v.widget(0), w.findChild(QSplitter, 'workspaceSplit'))
        top, bottom = v.sizes()
        v.setSizes([top - 120, bottom + 120]); self.app.processEvents()
        self.assertGreater(v.sizes()[1], bottom)          # timeline area can be made taller

    def test_dragging_clip_edges_changes_times(self):
        w = self.w
        tl = w.stage_timeline
        self.assertIn('hold', tl.editable)
        w.set_stage_seconds('hold', 2.5)
        if w.options().get('final_image') is not None:
            self.assertAlmostEqual(w.color_hold.value(), 2.5)
        else:                                             # no colours: the hold clip is the pause
            self.assertAlmostEqual(w.pause_after.value(), 2.5)
        w.set_stage_seconds('erase', 4.0)
        self.assertAlmostEqual(w.erase_time.value(), 4.0)
        if w.duration.isEnabled():
            w.set_stage_seconds('draw', 6.0)
            self.assertAlmostEqual(w.duration.value() / w.speed.value(), 6.0, places=1)
        # The real mouse drag on the Draw clip's right edge.
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        self.app.processEvents()
        edges = {k: x for k, x, _ in tl._edges()}
        if 'draw' in edges and 'draw' in tl.editable:
            got = []
            tl.stage_dragged.connect(lambda key, secs: got.append((key, secs)))
            _, clips, _ = tl._rows()
            y = int(clips.center().y()); x = int(edges['draw'])
            self.assertEqual(tl._edge_at(QPoint(x, y).toPointF()), 'draw')
            QTest.mousePress(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
            QTest.mouseMove(tl, QPoint(x + 40, y))
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QEvent, QPointF
            move = QMouseEvent(QEvent.Type.MouseMove, QPointF(x + 40, y), QPointF(x + 40, y),
                               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            tl.mouseMoveEvent(move)
            QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x + 40, y))
            self.assertTrue(got)
            self.assertEqual(got[-1][0], 'draw')

    def test_audio_lane_add_move_remove(self):
        w = self.w
        tl = w.stage_timeline
        self.assertIsNone(tl.audio)
        path = make_wav(self.dir / 'voice.wav')
        w.audio_dropped(str(path))
        self.app.processEvents()
        self.assertIsNotNone(w.audio_path)
        if w.audio_seconds:                                # ffprobe is there
            self.assertIsNotNone(tl.audio)
            self.assertAlmostEqual(tl.audio['seconds'], 2.0, places=1)
            self.assertIsNotNone(tl._audio_rect())
            tl.audio_moved.emit(1.5)
            self.assertAlmostEqual(w.audio_offset.value(), 1.5)
            self.assertAlmostEqual(tl.audio['start'], 1.5)
        tl.audio_remove.emit()
        self.assertIsNone(w.audio_path)
        self.assertIsNone(tl.audio)
        self.assertTrue(tl.acceptDrops())

    def test_export_finished_sound_option_and_autosave(self):
        w = self.w
        self.assertTrue(hasattr(w, 'export_done_sound'))
        self.assertIn('export_done_sound', w.PROJECT_SETTINGS)
        w.color_hold.setValue(w.color_hold.value() + 1); w.commit_history()
        self.assertTrue(w.autosave_tick())
        self.assertFalse(w.autosave_tick())               # nothing changed since
        self.assertIsNotNone(autosave.pending())
        # Normal close removes the backup.
        calls = []
        original = autosave.clear
        autosave.clear = lambda: (calls.append(1), original())[1]
        try:
            closed = w.close(); self.app.processEvents()
        finally:
            autosave.clear = original
        self.assertIsNone(autosave.pending(), f'closed={closed} visible={w.isVisible()} cleared={len(calls)} '
                          f'busy={w.busy} builder={bool(w.builder and w.builder.isRunning())} '
                          f'font={bool(w.font_worker and w.font_worker.isRunning())}')

    def test_update_banner(self):
        w = self.w
        self.assertFalse(w.update_banner.isVisibleTo(w))
        w.update_found('0.5.3-experimental.999')
        self.assertTrue(w.update_banner.isVisibleTo(w))
        self.assertIn('0.5.3-experimental.999', w.update_banner_text.text())
        self.assertEqual(w.banner_update.text(), 'Update now')
        w.banner_later.click()
        self.assertFalse(w.update_banner.isVisibleTo(w))


if __name__ == '__main__':
    unittest.main(verbosity=2)
