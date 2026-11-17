"""The WebM made while the frames are drawn (exp.26).

The user: a 26 s video at 2560 x 1440, 60 fps, WebM quality 18 took 5 minutes. Half of it was
drawing the frames and saving them as PNGs, the other half FFmpeg reading those PNGs back and
encoding, one after the other. Here each frame goes straight to FFmpeg (the same pixels: a PNG
is lossless), which encodes it while the next frame is drawn, and no PNG is written unless
something still needs it (Keep PNG frames, MOV, MP4). The encoder settings are the same as
engine.encode_webm, so the video is the same quality.

    stream = WebmStream.start(folder, fps, width, height, quality)   # None: not possible here
    stream.feed(rgba_bytes)       # per frame, in order
    path = stream.finish(audio)   # animation_vp9_alpha.webm (sound added without re-encoding)
"""
from __future__ import annotations

import queue
import shutil
import subprocess
import threading
from pathlib import Path

NAME = 'animation_vp9_alpha.webm'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def wanted(formats):
    """Streaming fits: a WebM is wanted, on a transparent background, with no Background row."""
    return bool(formats.get('webm')) and not formats.get('background') and not formats.get('background_pieces')


class WebmStream:
    def __init__(self, process, folder, video):
        self.process = process
        self.folder = Path(folder)
        self.video = video
        self.frames = queue.Queue(maxsize=4)      # a few frames ahead (memory), then the drawing waits
        self.error = None
        self.thread = threading.Thread(target=self._pump, name='webm-stream', daemon=True)
        self.thread.start()

    @classmethod
    def start(cls, folder, fps, width, height, quality):
        ffmpeg = shutil.which('ffmpeg')
        quality = int(quality)
        if not ffmpeg or not 18 <= quality <= 42:
            return None
        video = Path(folder) / '_video_vp9_alpha.webm'
        cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
               '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{int(width)}x{int(height)}',
               '-framerate', str(fps), '-i', '-', '-an',
               '-c:v', 'libvpx-vp9', '-deadline', 'good', '-cpu-used', '4',
               '-row-mt', '1', '-b:v', '0', '-crf', str(quality),
               '-auto-alt-ref', '0', '-pix_fmt', 'yuva420p', str(video)]
        try:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        except OSError:
            return None
        return cls(process, folder, video)

    def _pump(self):
        while True:
            data = self.frames.get()
            if data is None:
                break
            if self.error is not None:
                continue
            try:
                self.process.stdin.write(data)
            except (OSError, ValueError) as exc:          # FFmpeg stopped: read why in finish()
                self.error = exc

    def feed(self, data):
        if self.error is not None:
            raise RuntimeError(self._why())
        self.frames.put(data)

    def _why(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            err = self.process.stderr.read().decode('utf-8', 'replace')
        except Exception:
            err = ''
        return 'WebM encoding failed: ' + (err[-2000:] or str(self.error))

    def cancel(self):
        self.frames.put(None)
        self.thread.join(timeout=5)
        try:
            self.process.kill()
        except Exception:
            pass
        self.video.unlink(missing_ok=True)

    def finish(self, audio=None):
        """Waits for the encoder; adds the sound (copied video, Opus sound, like encode_webm)."""
        from engine import verify_webm
        self.frames.put(None)
        self.thread.join()
        try:
            self.process.stdin.close()
        except Exception:
            pass
        err = self.process.stderr.read().decode('utf-8', 'replace')
        if self.process.wait() or self.error is not None or not self.video.is_file():
            self.video.unlink(missing_ok=True)
            raise RuntimeError('WebM encoding failed: ' + (err[-2000:] or str(self.error)))
        output = self.folder / NAME
        if audio:
            cmd = [shutil.which('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'error',
                   '-i', str(self.video), '-i', str(audio), '-map', '0:v', '-map', '1:a',
                   '-c:v', 'copy', '-c:a', 'libopus', '-b:a', '128k', str(output)]
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
            if result.returncode:
                output.unlink(missing_ok=True)
                raise RuntimeError('Adding the sound to the WebM failed: ' + result.stderr[-2000:])
            self.video.unlink(missing_ok=True)
        else:
            self.video.replace(output)
        if output.stat().st_size <= 0:
            raise RuntimeError('WebM encoder did not produce a nonempty video.')
        verify_webm(output)
        return output
