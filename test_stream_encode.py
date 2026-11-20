"""exp.26: the WebM made while the frames are drawn is the same video as the one made from PNGs."""
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

FFMPEG = shutil.which('ffmpeg')


def decoded(path):
    return subprocess.run([FFMPEG, '-loglevel', 'error', '-c:v', 'libvpx-vp9', '-i', str(path),
                           '-pix_fmt', 'rgba', '-f', 'rawvideo', '-'], capture_output=True).stdout


@unittest.skipIf(FFMPEG is None, 'needs FFmpeg')
class Stream(unittest.TestCase):
    def frames(self, folder, n=12, w=96, h=64):
        from PIL import Image
        rng = np.random.default_rng(3)
        out = []
        for i in range(n):
            a = np.zeros((h, w, 4), np.uint8)
            a[8:40, 4 + i * 4:40 + i * 4] = (200, 40, 30, 255)
            a[30:60, 50:90, :3] = rng.integers(0, 255, (30, 40, 3)); a[30:60, 50:90, 3] = 128
            Image.fromarray(a, 'RGBA').save(folder / f'frame_{i:06d}.png')
            out.append(a.tobytes())
        (folder / 'sequence.json').write_text(json.dumps(dict(width=w, height=h)))
        return out

    def test_the_same_video_as_from_pngs_with_its_transparency(self):
        from engine import encode_webm
        from stream_encode import WebmStream
        old, new = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        data = self.frames(old)
        stream = WebmStream.start(new, 30, 96, 64, 18)
        for d in data:
            stream.feed(d)
        made = stream.finish()
        self.assertEqual(made.name, 'animation_vp9_alpha.webm')
        self.assertEqual(decoded(made), decoded(encode_webm(old, 30, 18)))
        alpha = np.frombuffer(decoded(made), np.uint8).reshape(-1, 64, 96, 4)[0, 45, 70, 3]
        self.assertTrue(100 <= alpha <= 160)          # half-transparent stays half-transparent
        self.assertEqual(list(new.glob('*.png')), [])  # no PNG written

    def test_the_sound_is_added_and_the_transparency_kept(self):
        from engine import verify_webm
        from stream_encode import WebmStream
        folder = Path(tempfile.mkdtemp())
        data = self.frames(Path(tempfile.mkdtemp()))
        sound = folder / 'soundtrack.wav'
        with wave.open(str(sound), 'wb') as f:
            f.setnchannels(2); f.setsampwidth(2); f.setframerate(44100)
            f.writeframes((np.sin(np.arange(17640) / 9) * 8000).astype(np.int16).repeat(2).tobytes())
        stream = WebmStream.start(folder, 30, 96, 64, 18)
        for d in data:
            stream.feed(d)
        made = stream.finish(sound)
        verify_webm(made)
        kinds = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0',
                                str(made)], capture_output=True, text=True).stdout.split()
        self.assertEqual(kinds, ['video', 'audio'])
        alpha = np.frombuffer(decoded(made), np.uint8).reshape(-1, 64, 96, 4)[0, 45, 70, 3]
        self.assertTrue(100 <= alpha <= 160)


if __name__ == '__main__':
    unittest.main()
