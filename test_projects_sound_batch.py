"""Projects, pencil/brush sound and batch export."""
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import sound


@dataclass(frozen=True)
class Pen:
    point: tuple | None
    kind: str | None


class SoundTests(unittest.TestCase):
    def test_scratch_only_while_drawing_softer_brush_when_painting(self):
        samples = []
        for i in range(6 * 120 + 1):
            t = i / 120
            if t < 2:
                s = Pen((960 + 300 * math.cos(t * 3), 540 + 300 * math.sin(t * 3)), 'draw')
            elif t < 2.5:
                s = Pen((1200, 300), 'lift')
            elif t < 4:
                s = Pen((600 + 400 * (t - 2.5), 700), 'draw')
            elif t < 5.5:
                s = Pen((800 + 200 * math.sin(t * 8), 500), 'paint')
            else:
                s = Pen(None, None)
            samples.append((t, s))
        audio = sound.synthesize(samples, 6, 1920, 1080)
        self.assertEqual(audio.shape, (6 * sound.RATE, 2))
        mono = audio.astype(float).mean(1)
        rms = lambda a, b: float(np.sqrt((mono[int(a * sound.RATE):int(b * sound.RATE)] ** 2).mean()))
        self.assertGreater(rms(.2, 1.8), 1000)               # pencil
        self.assertLess(rms(2.1, 2.4), 5)                    # pen lift: silent
        self.assertGreater(rms(4.2, 5.3), 200)               # brush
        self.assertLess(rms(4.2, 5.3), rms(.2, 1.8))         # brush is softer
        self.assertLess(rms(5.7, 5.95), 5)                   # after painting: silent
        quiet = sound.synthesize(samples, 6, 1920, 1080, volume=.25)
        self.assertLess(np.abs(quiet).max(), np.abs(audio).max())

    def test_recorded_pencil_sound_is_used(self):
        import os
        old_path = os.environ.get('PATH', '')
        with tempfile.TemporaryDirectory() as tmp:
            # A 'recording': silence, 2 s of a 900 Hz tone, silence (the silence gets trimmed).
            t = np.arange(int(2 * sound.RATE)) / sound.RATE
            tone = (np.sin(2 * np.pi * 900 * t) * 12000).astype(np.int16)
            quiet = np.zeros(sound.RATE // 2, np.int16)
            mono = np.concatenate([quiet, tone, quiet])
            path = sound.write_wav(Path(tmp) / 'pencil.wav', np.stack([mono, mono], 1))
            rec = sound.load_recording(path)
            self.assertIsNotNone(rec)
            self.assertAlmostEqual(len(rec) / sound.RATE, 2., delta=.1)       # silence trimmed
            samples = [(i / 120, Pen((900 + 300 * i / 120, 500), 'draw') if i < 240 else Pen(None, None))
                       for i in range(361)]
            audio = sound.synthesize(samples, 3, 1920, 1080, recordings={'draw': rec})
            mono_out = audio.astype(float).mean(1)
            part = mono_out[int(.5 * sound.RATE):int(1.5 * sound.RATE)]
            spectrum = np.abs(np.fft.rfft(part))
            peak_hz = np.argmax(spectrum) * sound.RATE / len(part)
            self.assertAlmostEqual(peak_hz, 900, delta=15)                    # the recording, not noise
            self.assertLess(np.sqrt((mono_out[int(2.3 * sound.RATE):] ** 2).mean()), 5)   # pen up: silent
            self.assertIsNone(sound.load_recording(Path(tmp) / 'missing.wav'))

    def test_wav_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = sound.write_wav(Path(tmp) / 'a.wav', np.zeros((441, 2), np.int16))
            with wave.open(str(path)) as w:
                self.assertEqual((w.getnchannels(), w.getframerate(), w.getnframes()), (2, 44100, 441))


@unittest.skipIf(os.environ.get('STROKESCRIBE_SKIP_QT') == '1', 'needs Qt')
class StudioFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
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

    def colour_image(self, name='art.png'):
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (320, 240), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((40, 30, 280, 210), fill=(230, 120, 40, 255), outline=(20, 20, 20, 255), width=5)
        d.rectangle((120, 90, 200, 150), fill=(40, 90, 200, 255))
        path = self.dir / name
        img.save(path)
        return path

    def test_window_options_match_settings_function(self):
        from export_job import options_from_settings
        w = self.window()
        a = w.options()
        b = options_from_settings(w.settings_state(), w.drawing, color_image=None, hand=w.hand)
        self.assertEqual({k: v for k, v in a.items() if k not in ('hand', 'painting_hand')},
                         {k: v for k, v in b.items() if k not in ('hand', 'painting_hand')})

    def test_svg_project_round_trip(self):
        w = self.window()
        names = [s.name for s in w.drawing.strokes]
        w.order.setCurrentRow(0)
        w.move(1)                                   # change the stroke order
        w.duration.setValue(6.5)
        w.thickness.setValue(2.2)
        w.reveal_mode.setCurrentIndex(w.reveal_mode.findText('Zigzag sweep'))
        w.sound_volume.setValue(35)
        w.res.setCurrentIndex(1)
        from PySide6.QtWidgets import QFileDialog
        target = self.dir / 'my project'
        original = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(target), ''))
        try:
            saved = w.save_project()
        finally:
            QFileDialog.getSaveFileName = original
        self.assertEqual(saved.suffix, '.strokescribe')
        self.assertTrue(json.loads(saved.read_text())['format'] == 'strokescribe-project')
        other = self.window()
        self.assertTrue(other.open_project(str(saved)))
        self.assertEqual([s.name for s in other.drawing.strokes], [s.name for s in w.drawing.strokes])
        self.assertNotEqual([s.name for s in other.drawing.strokes], names)
        np.testing.assert_allclose(other.drawing.strokes[0].points, w.drawing.strokes[0].points, atol=1e-3)
        self.assertAlmostEqual(other.duration.value(), 6.5)
        self.assertAlmostEqual(other.thickness.value(), 2.2)
        self.assertEqual(other.reveal_mode.currentText(), 'Zigzag sweep')
        self.assertEqual(other.sound_volume.value(), 35)
        self.assertEqual(other.res.currentIndex(), 1)
        self.assertTrue(other.hand_builtin)
        self.assertIn('my project', other.windowTitle())
        # Saving again goes to the same file without asking.
        other.thickness.setValue(3.)
        self.assertEqual(other.save_project(), saved)

    def test_image_project_round_trip_and_bad_files(self):
        w = self.window()
        path = self.colour_image()
        w.source_type.setCurrentIndex(1)
        w.build_image(str(path))
        w.builder.wait(60000)
        self.app.processEvents()
        self.assertTrue(w.builder.success)
        w.image_animation.setCurrentIndex(1)              # Paint Only
        import projects
        saved = projects.save(self.dir / 'img', w.project_state())
        other = self.window()
        self.assertTrue(other.open_project(str(saved)))
        self.assertEqual(other.source_type.currentIndex(), 1)
        self.assertEqual(other.image_animation.currentText(), 'Paint Only')
        self.assertEqual(len(other.drawing.strokes), len(w.drawing.strokes))
        self.assertEqual(other.image_result.image.size(), w.image_result.image.size())
        self.assertIsNotNone(other.options()['final_image'])
        other.slider.setValue(600)
        self.assertFalse(other.canvas.frame.isNull())
        bad = self.dir / 'bad.strokescribe'
        bad.write_text('{"format": "other"}')
        from PySide6.QtWidgets import QMessageBox
        original = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        try:
            self.assertFalse(other.open_project(str(bad)))
        finally:
            QMessageBox.warning = original

    def test_choose_sound_recording(self):
        w = self.window()
        self.assertFalse(w.sound_on.isChecked())                 # off until you choose a sound
        t = np.arange(sound.RATE) / sound.RATE
        mono = (np.sin(2 * np.pi * 700 * t) * 9000).astype(np.int16)
        path = sound.write_wav(self.dir / 'my pencil.wav', np.stack([mono, mono], 1))
        w.set_sound_file('sound_pencil_file', str(path))
        self.assertTrue(w.sound_on.isChecked())
        self.assertIn('my pencil', w.sound_file_buttons['sound_pencil_file'][0].text())
        self.assertEqual(w.options()['sound_files'][0], str(path))
        import projects
        saved = projects.save(self.dir / 'snd', w.project_state())
        other = self.window()
        self.assertTrue(other.open_project(str(saved)))
        self.assertEqual(other.sound_files['sound_pencil_file'], str(path))
        w.set_sound_file('sound_pencil_file', None)
        self.assertEqual(w.options()['sound_files'][0], '')

    def test_soundtrack_follows_the_animation(self):
        from sound import soundtrack
        w = self.window()
        options = w.options()
        options.pop('fps')
        options.update(width=480, height=270, duration=2.)
        path = soundtrack(w.drawing, options, self.dir / 's.wav', .8)
        with wave.open(str(path)) as f:
            frames = f.getnframes()
            data = np.frombuffer(f.readframes(frames), np.int16)
        self.assertEqual(frames, 2 * sound.RATE)
        self.assertGreater(np.abs(data).max(), 1000)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'needs FFmpeg')
    def test_batch_export_with_sound(self):
        from batch_export import BatchWorker, matching_color
        from engine import Drawing, Stroke
        w = self.window()
        # An SVG with a matching colour PNG, an image and a project.
        svg = self.dir / 'house.svg'
        shutil.copy(Path(__file__).parent / 'samples' / 'drawing.svg', svg)
        from PIL import Image
        Image.new('RGBA', (200, 150), (200, 60, 60, 255)).save(self.dir / 'house_color.png')
        self.assertEqual(matching_color(svg).name, 'house_color.png')
        image = self.colour_image('photo.png')
        import projects
        w.fps.setValue(6); w.duration.setValue(.6)        # keep the saved project quick to export
        w.sound_on.setChecked(True)                      # projects keep their own sound setting
        project = projects.save(self.dir / 'saved', w.project_state())
        settings = w.settings_state()
        settings.update(res='1920 × 1080', fps=6, duration=.6, speed=1., color_fade=.4, color_hold=.2,
                        image_duration=.6, mp4=True, webm=False, mov=False, keep_png=False,
                        sound_on=True, sound_volume=80, image_detail='Low')
        out = self.dir / 'out'; out.mkdir()
        states = {}
        worker = BatchWorker([str(svg), str(image), str(project)], out, settings, w.hand)
        worker.item_state.connect(lambda row, text: states.__setitem__(row, text))
        totals = []
        worker.finished_all.connect(lambda d, f: totals.append((d, f)))
        worker.run()                                     # synchronously, for the test
        self.assertEqual(totals, [(3, 0)], states)
        folders = sorted(p for p in out.iterdir() if p.is_dir())
        self.assertEqual(len(folders), 3)
        for folder in folders:
            self.assertTrue((folder / 'soundtrack.wav').is_file(), folder)
            mp4 = next(folder.glob('*.mp4'), None)
            if folder.name.startswith('saved'):
                continue                                  # the project keeps its own formats
            self.assertIsNotNone(mp4, folder)
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
                                    '-of', 'json', str(mp4)], capture_output=True, text=True)
            kinds = {s['codec_type'] for s in json.loads(probe.stdout)['streams']}
            self.assertEqual(kinds, {'video', 'audio'})
            self.assertFalse(list(folder.glob('frame_*.png')))   # removed after encoding

    def test_batch_window(self):
        from batch_export import BatchExportDialog
        w = self.window()
        d = BatchExportDialog(w, w.settings_state(), w.hand)
        self.addCleanup(d.close)
        self.assertFalse(d.start_button.isEnabled())
        path = self.colour_image()
        d.add_paths([str(path), str(path), str(self.dir / 'notes.txt')])
        self.assertEqual(d.table.rowCount(), 1)                 # duplicates and unknown types skipped
        self.assertEqual(d.destination, str(path.parent))
        self.assertTrue(d.start_button.isEnabled())
        d.table.selectRow(0); d.remove_selected()
        self.assertEqual(d.paths, [])

    def test_camera_path_and_crop(self):
        import camera
        from frame_render import compose_frame, camera_for
        w = self.window()
        options = w.options(); options.pop('fps')
        options.update(width=480, height=270)
        path = camera_for(w.drawing, options, camera.ZOOMS['gentle'])
        self.assertIsNotNone(path)
        z0, _, _ = path.at(0.)
        zm, x, y = path.at(.5)
        self.assertLess(z0, 1.05)
        self.assertGreater(zm, 1.2)
        self.assertTrue(0 < x < 1 and 0 < y < 1)
        frame = compose_frame(w.drawing, .5, options, path)
        self.assertEqual((frame.width(), frame.height()), (480, 270))


if __name__ == '__main__':
    unittest.main(verbosity=2)
