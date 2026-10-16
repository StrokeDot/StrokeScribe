"""Scenes: several drawings in one video with camera moves between them."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'

import scenes


class TimingTests(unittest.TestCase):
    def test_locate(self):
        lengths, joins = [4., 3.], [1., 0.]
        self.assertEqual(scenes.locate(lengths, joins, 0.), ('scene', 0, 0.))
        self.assertEqual(scenes.locate(lengths, joins, 2.), ('scene', 0, .5))
        kind, k, t = scenes.locate(lengths, joins, 4.5)
        self.assertEqual((kind, k), ('join', 0)); self.assertAlmostEqual(t, .5)
        kind, k, f = scenes.locate(lengths, joins, 6.5)
        self.assertEqual((kind, k), ('scene', 1)); self.assertAlmostEqual(f, .5)
        self.assertEqual(scenes.locate(lengths, joins, 99.)[:2], ('scene', 1))
        self.assertEqual(scenes.transition_seconds('Cut', 2.), 0.)

    def test_project_round_trip(self):
        a, b = {'title': 'A', 'drawing': 1}, {'title': 'B', 'drawing': 2}
        listed = [dict(state=a, transition='Pan left', transition_seconds=.8),
                  dict(state=b, transition='Cut', transition_seconds=1.)]
        data = scenes.scenes_to_project(b, listed, 1)
        self.assertEqual(data['title'], 'B')                   # main body = edited scene
        self.assertIsNone(data['scenes'][1]['state'])
        back = scenes.scenes_from_project(data)
        self.assertEqual([s['state']['title'] for s in back], ['A', 'B'])
        self.assertEqual(back[0]['transition'], 'Pan left')
        single = scenes.scenes_to_project(a, listed[:1], 0)
        self.assertNotIn('scenes', single)                     # one scene: same file as before
        self.assertEqual(len(scenes.scenes_from_project(single)), 1)


@unittest.skipIf(SKIP, 'needs Qt')
class SceneWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def window(self):
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        return w

    def test_transition_frames(self):
        from PySide6.QtGui import QColor, QImage
        a = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied); a.fill(QColor('red'))
        b = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied); b.fill(QColor('blue'))
        mid = scenes.transition_frame(a, b, 'Pan right', .5)
        self.assertEqual(QColor(mid.pixel(20, 50)).name(), '#ff0000')       # old picture leaving left
        self.assertEqual(QColor(mid.pixel(180, 50)).name(), '#0000ff')      # new one coming from right
        start = scenes.transition_frame(a, b, 'Camera move', 0.)
        self.assertEqual(QColor(start.pixel(100, 50)).name(), '#ff0000')
        middle = scenes.transition_frame(a, b, 'Camera move', .5)
        self.assertEqual(middle.pixelColor(100, 5).alpha(), 0)              # zoomed out: board edge visible
        end = scenes.transition_frame(a, b, 'Fade', .99)
        self.assertEqual(QColor(end.pixel(100, 50)).name(), '#0000ff')

    def two_scenes(self):
        from engine import import_svg
        w = self.window()
        w.duration.setValue(1.)
        w.add_scene()
        self.assertEqual(len(w.scenes), 2)
        self.assertEqual(w.scene_index, 1)
        w.set_drawing(import_svg(Path(__file__).parent / 'samples' / 'arthur-headset-traced.svg'))
        w.duration.setValue(1.5)
        w.scene_transition.setCurrentText('Pan left')        # (last scene: unused)
        return w

    def test_scenes_keep_their_own_drawing_and_settings(self):
        w = self.two_scenes()
        headset = len(w.drawing.strokes)
        w.scene_list.setCurrentRow(0)
        self.assertEqual(w.scene_index, 0)
        self.assertAlmostEqual(w.duration.value(), 1.)
        sample = len(w.drawing.strokes)
        self.assertNotEqual(sample, headset)
        w.scene_transition.setCurrentText('Camera move'); w.scene_transition_changed()
        w.scene_list.setCurrentRow(1)
        self.assertAlmostEqual(w.duration.value(), 1.5)
        self.assertEqual(len(w.drawing.strokes), headset)
        self.assertEqual(w.scene_list.count(), 2)
        # Save and reopen: both scenes, the edited one, and the transition.
        import projects
        saved = projects.save(self.dir / 'two', w.project_state())
        other = self.window()
        self.assertTrue(other.open_project(str(saved)))
        self.assertEqual(len(other.scenes), 2)
        self.assertEqual(other.scene_index, 1)
        self.assertEqual(len(other.drawing.strokes), headset)
        self.assertEqual(other.scenes[0]['transition'], 'Camera move')
        other.scene_list.setCurrentRow(0)
        self.assertEqual(len(other.drawing.strokes), sample)
        # Move and delete.
        other.move_scene(1)
        self.assertEqual(other.scene_index, 1)
        from PySide6.QtWidgets import QMessageBox
        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        try:
            other.delete_scene()
        finally:
            QMessageBox.question = original
        self.assertEqual(len(other.scenes), 1)
        self.assertEqual(len(other.drawing.strokes), headset)
        self.assertFalse(other.scene_delete.isEnabled())

    def test_preview_all_scenes(self):
        w = self.two_scenes()
        w.preview_scope.setCurrentIndex(1)
        lengths, joins = w.scene_timeline()
        self.assertEqual(len(lengths), 2)
        self.assertAlmostEqual(w.timeline_length(), sum(lengths) + sum(joins))
        self.assertEqual([k for _, _, k in w.stage_timeline.scene_segments], ['scene', 'join', 'scene'])
        for value in (100, 500, 900):
            w.slider.setValue(value)
            self.assertFalse(w.canvas.frame.isNull())
        w.preview_scope.setCurrentIndex(0)
        self.assertIsNone(w.stage_timeline.scene_segments)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'needs FFmpeg')
    def test_export_all_scenes_with_sound(self):
        w = self.two_scenes()
        w.scene_list.setCurrentRow(0)
        w.scene_transition_time.setValue(.5)
        w.scene_transition.setCurrentText('Camera move'); w.scene_transition_changed()
        w.fps.setValue(6); w.mp4.setChecked(True); w.webm.setChecked(False); w.mov.setChecked(False)
        w.sound_on.setChecked(True)
        w._leave_scene()
        scene_list = [dict(state=s['state'], transition=s['transition'],
                           transition_seconds=s['transition_seconds']) for s in w.scenes]
        w.scenes[w.scene_index]['state'] = None
        states = []
        out = self.dir / 'video'
        message = scenes.export_scenes(scene_list, out, w.settings_state(), w.hand,
                                       progress=lambda i, n: states.append((i, n)))
        self.assertIn('.mp4', message)
        info = json.loads((out / 'sequence.json').read_text())
        self.assertEqual(len(info['scenes']), 2)
        first, second = info['scenes']
        self.assertEqual(second['first_frame'] - first['frames'], 3)      # 0.5 s move at 6 fps
        self.assertEqual(info['frames'], first['frames'] + 3 + second['frames'])
        mp4 = next(out.glob('*.mp4'))
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type:format=duration',
                                '-of', 'json', str(mp4)], capture_output=True, text=True)
        data = json.loads(probe.stdout)
        self.assertEqual({s['codec_type'] for s in data['streams']}, {'video', 'audio'})
        self.assertAlmostEqual(float(data['format']['duration']), info['frames'] / 6, delta=.4)
        self.assertFalse((out / '_scenes').exists())
        # Batch export of the saved two-scene project: one video with both scenes.
        import projects
        from batch_export import BatchWorker
        saved = projects.save(self.dir / 'story', w.project_state())
        dest = self.dir / 'batch'; dest.mkdir()
        totals = []
        worker = BatchWorker([str(saved)], dest, w.settings_state(), w.hand)
        worker.finished_all.connect(lambda d, f: totals.append((d, f)))
        worker.run()
        self.assertEqual(totals, [(1, 0)])
        folder = next(p for p in dest.iterdir() if p.is_dir())
        self.assertEqual(len(json.loads((folder / 'sequence.json').read_text())['scenes']), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
