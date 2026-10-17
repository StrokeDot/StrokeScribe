"""Voiceover/music, fit to audio, Auto timing, camera follow and textured backgrounds."""
import math
import os
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

import auto_timing
import backgrounds

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'
HAS_FFMPEG = shutil.which('ffmpeg') is not None


def tone(path, seconds, freq=440., rate=44100, amplitude=.4):
    t = np.arange(int(seconds * rate)) / rate
    data = (np.sin(2 * math.pi * freq * t) * amplitude * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(data.tobytes())
    return path


def read_wav(path):
    with wave.open(str(path)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        return data.reshape(-1, w.getnchannels()).astype(float), w.getframerate()


class _Stroke:
    def __init__(self, points):
        self.points = points
        self.length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))


class _Drawing:
    def __init__(self, strokes):
        self.strokes = strokes


class TimingTests(unittest.TestCase):
    def test_busier_drawings_get_more_time(self):
        simple = _Drawing([_Stroke([(0, 0), (100, 100)])])
        busy = _Drawing([_Stroke([(0, y), (100, y)]) for y in range(0, 100, 4)])
        a = auto_timing.suggest(simple, paint=True)
        b = auto_timing.suggest(busy, paint=True, erase=True)
        self.assertLess(a['draw'], b['draw'])
        self.assertEqual(a['erase'], 0.)
        self.assertGreater(b['erase'], 0.)
        self.assertGreater(b['paint'], 0.)
        self.assertEqual(auto_timing.suggest(busy, paint=True, image=True, paint_only=True)['draw'], 0.)
        self.assertLessEqual(b['draw'], 20.)

    def test_fit_keeps_proportions_and_limits(self):
        times = dict(draw=4., paint=2., hold=1., erase=0.)
        out, ok = auto_timing.fit(times, 14.)
        self.assertTrue(ok)
        self.assertAlmostEqual(sum(out.values()), 14., delta=.03)
        self.assertAlmostEqual(out['draw'] / out['paint'], 2., delta=.02)
        self.assertEqual(out['erase'], 0.)
        # Hold is capped at 30 s; the rest takes up the difference.
        out, ok = auto_timing.fit(dict(draw=1., paint=1., hold=10., erase=0.), 100.)
        self.assertTrue(ok)
        self.assertEqual(out['hold'], 30.)
        self.assertAlmostEqual(out['draw'] + out['paint'], 70., delta=.03)
        out, ok = auto_timing.fit(times, 10000.)
        self.assertFalse(ok)


class BackgroundTests(unittest.TestCase):
    def test_textures_look_different(self):
        means = {}
        for name in backgrounds.CHOICES:
            rgb = backgrounds.texture_rgb(name, 160, 90)
            self.assertEqual(rgb.shape, (90, 160, 3))
            means[name] = rgb.reshape(-1, 3).mean(0)
            if name in backgrounds.TEXTURES:
                self.assertGreater(rgb.std(), .5, name)            # not a flat colour
        self.assertGreater(means['Whiteboard'].mean(), 235)
        self.assertLess(means['Chalkboard'].mean(), 90)
        self.assertGreater(means['Cork'][0], means['Cork'][2] + 40)  # warm brown
        self.assertGreater(means['Paper'][0], means['Paper'][2])     # cream


@unittest.skipUnless(HAS_FFMPEG, 'needs FFmpeg')
class AudioTrackTests(unittest.TestCase):
    def test_duration_and_mix(self):
        import audio_track
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            voice = tone(tmp / 'voice.wav', 1.5, 330)
            effects = tone(tmp / 'fx.wav', 3.0, 1200, amplitude=.1)
            self.assertAlmostEqual(audio_track.duration(voice), 1.5, delta=.02)
            out = audio_track.mix(effects, voice, 1., .5, 3., tmp / 'mix.wav')
            data, rate = read_wav(out)
            self.assertEqual(data.shape[1], 2)
            self.assertAlmostEqual(len(data) / rate, 3., delta=.02)
            rms = lambda a, b: np.sqrt((data[int(a * rate):int(b * rate)] ** 2).mean())
            self.assertGreater(rms(.7, 1.8), rms(.05, .45) * 2)      # voice starts at 0.5 s
            self.assertGreater(rms(2.3, 2.9), 300)                    # effects keep going
            # Voice only, longer than the video: cut at the end.
            out = audio_track.mix(None, voice, .5, 0, 1., tmp / 'cut.wav')
            data, rate = read_wav(out)
            self.assertAlmostEqual(len(data) / rate, 1., delta=.02)


@unittest.skipIf(SKIP, 'needs Qt')
class WindowMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ['STROKESCRIBE_CONFIG_DIR'] = str(self.dir / 'config')
        import library
        settings = library.load_settings()
        settings['root'] = str(self.dir / 'Lib')
        library.save_settings(settings)

    def tearDown(self):
        del os.environ['STROKESCRIBE_CONFIG_DIR']
        self.tmp.cleanup()

    def window(self):
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        return w

    def test_settings_carry_camera_and_audio(self):
        from export_job import options_from_settings
        o = options_from_settings({'camera': 'Close-up zoom', 'audio_path': 'v.mp3', 'audio_volume': 50,
                                   'audio_offset': 1.5}, None)
        self.assertAlmostEqual(o['camera_zoom'], 1.65)
        self.assertEqual(o['audio'], dict(path='v.mp3', volume=.5, offset=1.5))
        o = options_from_settings({}, None)
        self.assertEqual(o['camera_zoom'], 1.)
        self.assertIsNone(o['audio'])

    def test_camera_follow_in_preview(self):
        w = self.window()
        w.slider.setValue(450)
        plain = w.canvas.frame.copy()
        w.camera.setCurrentIndex(2)
        self.assertIsNotNone(w._camera_path)
        zoomed = w.canvas.frame.copy()
        self.assertEqual((plain.width(), plain.height()), (zoomed.width(), zoomed.height()))
        self.assertNotEqual(plain, zoomed)
        self.assertEqual(w.settings_state()['camera'], 'Close-up zoom')
        self.assertGreater(w._camera_path.at(.45)[0], 1.2)
        # At the very end the camera has pulled back to the whole picture.
        z, cx, cy = w._camera_path.at(1.)
        self.assertAlmostEqual(z, 1., delta=.02)

    def test_auto_timing_buttons(self):
        w = self.window()
        w.duration.setValue(60)
        w.auto_timing()
        self.assertLess(w.duration.value(), 60)
        self.assertGreaterEqual(w.duration.value(), 2)

    @unittest.skipUnless(HAS_FFMPEG, 'needs FFmpeg')
    def test_voiceover_fit_save_and_export(self):
        w = self.window()
        voice = tone(self.dir / 'narration.wav', 9., 300)
        w.set_audio(w.keep_in_library('audio', str(voice)))
        self.assertEqual(Path(w.audio_path).parent, self.dir / 'Lib' / 'Audio')
        self.assertIn('9.0 s', w.audio_note.text())
        self.assertTrue(w.fit_audio_button.isEnabled())
        w.audio_offset.setValue(1.)
        w.fit_to_audio()
        self.assertAlmostEqual(w.timeline_length(), 10., delta=.1)
        # Auto timing with a voiceover also lands on the audio length.
        w.duration.setValue(1.)
        w.auto_timing()
        self.assertAlmostEqual(w.timeline_length(), 10., delta=.1)
        # Projects remember the track.
        state = w.project_state()
        self.assertEqual(state['audio'], w.audio_path)
        self.assertEqual(state['settings']['audio_offset'], 1.)
        w.remove_audio()
        self.assertIsNone(w.settings_state()['audio_path'])
        w.apply_project(state)
        self.assertEqual(w.audio_path, state['audio'])
        # Short export with the voiceover mixed in, on a cork MP4 background.
        from export_job import options_from_settings, run_export
        s = dict(w.settings_state(), res='1920 × 1080', fps=4, duration=1., speed=1., use_color=False,
                 erase_mode='Off', audio_offset=0.)
        o = options_from_settings(s, w.drawing, hand=w.hand)
        o.update(width=320, height=180)
        folder = self.dir / 'export'
        run_export(w.drawing, folder, o, mp4=True, mp4_background='cork', sound_volume=.8, keep_png=True)
        data, rate = read_wav(folder / 'soundtrack.wav')
        self.assertAlmostEqual(len(data) / rate, 1., delta=.05)
        self.assertTrue((folder / 'background.png').is_file())
        mp4 = next(folder.glob('*.mp4'))
        import subprocess
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
                                '-of', 'csv=p=0', str(mp4)], capture_output=True, text=True).stdout
        self.assertIn('audio', probe)
        self.assertIn('video', probe)

    def test_audio_in_the_library(self):
        import library
        from library_dialog import LibraryDialog
        lib = library.Library()
        lib.add('audio', tone(self.dir / 'music.wav', .3))
        with self.assertRaises(ValueError):
            lib.add('audio', self.dir / 'notes.txt')
        used = []
        d = LibraryDialog(None, 'audio', lambda c, i: used.append((c, i.file)))
        self.addCleanup(d.close)
        self.assertEqual(d.grid.count(), 1)
        d.grid.setCurrentRow(0)
        d.use()
        self.assertEqual(used, [('audio', 'music.wav')])


if __name__ == '__main__':
    unittest.main(verbosity=2)
