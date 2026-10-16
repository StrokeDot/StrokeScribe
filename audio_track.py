"""Voiceover / music track: length, and mixing it with the pencil sounds (FFmpeg)."""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
AUDIO_TYPES = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.opus', '.wma')


def duration(path):
    """Length in seconds, or None if it cannot be read."""
    path = Path(path)
    probe = shutil.which('ffprobe')
    if probe:
        result = subprocess.run([probe, '-v', 'error', '-show_entries', 'format=duration',
                                 '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                                capture_output=True, text=True, creationflags=NO_WINDOW)
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass
    if path.suffix.lower() == '.wav':
        try:
            with wave.open(str(path)) as w:
                return w.getnframes() / float(w.getframerate())
        except (wave.Error, OSError):
            return None
    return None


def mix(effects, voice, volume, offset, total, output):
    """One WAV: pencil/brush/eraser effects (or None) + the voice/music track.

    The voice starts `offset` seconds into the video, at `volume` (1.0 = as
    recorded); the result is exactly `total` seconds long.
    """
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('FFmpeg is needed to add a voiceover or music track.')
    delay = max(0, int(round(float(offset) * 1000)))
    voice_chain = f'volume={float(volume):.3f},aresample=44100,aformat=channel_layouts=stereo,' \
                  f'adelay={delay}|{delay},apad'
    cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error']
    if effects:
        cmd += ['-i', str(effects), '-i', str(voice)]
        graph = (f'[1:a]{voice_chain}[v];[0:a]aresample=44100,aformat=channel_layouts=stereo,apad[f];'
                 f'[f][v]amix=inputs=2:normalize=0:duration=longest,atrim=0:{total:.3f}[a]')
    else:
        cmd += ['-i', str(voice)]
        graph = f'[0:a]{voice_chain},atrim=0:{total:.3f}[a]'
    cmd += ['-filter_complex', graph, '-map', '[a]', '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le',
            str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Could not mix the audio track: ' + result.stderr[-800:])
    return Path(output)


_ENVELOPES = {}


def envelope(path, points=600):
    """Loudness outline of an audio file (list of 0..1, `points` long) for the timeline."""
    path = Path(path)
    try:
        key = (str(path), path.stat().st_mtime, points)
    except OSError:
        return []
    if key in _ENVELOPES:
        return _ENVELOPES[key]
    import numpy as np
    data = None
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        result = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-ac', '1', '-ar', '8000', '-f', 's16le', '-'],
                                capture_output=True, creationflags=NO_WINDOW)
        if result.returncode == 0 and result.stdout:
            data = np.abs(np.frombuffer(result.stdout, np.int16).astype(np.float32))
    elif path.suffix.lower() == '.wav':
        try:
            with wave.open(str(path)) as f:
                raw = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32)
                data = np.abs(raw.reshape(-1, f.getnchannels()).mean(1))
        except (wave.Error, OSError):
            data = None
    if data is None or not len(data):
        out = []
    else:
        chunks = np.array_split(data, min(points, len(data)))
        levels = np.array([c.max() for c in chunks])
        out = (levels / max(1., levels.max())).round(3).tolist()
    _ENVELOPES[key] = out
    return out
