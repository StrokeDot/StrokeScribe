"""Pencil, brush and eraser sounds that follow the pen.

The sounds are YOUR recordings (or sounds made with Create sound): the
soundtrack plays them only while the pen is down and moving (louder when it
moves faster, silent during pen lifts), following the pen track (motion.py) so
it always matches the animation, and pans gently with the hand's position.
There are no built-in sounds.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 44100
TRACK_RATE = 120.


def _smooth(values, samples):
    if samples <= 1:
        return values
    kernel = np.hanning(samples * 2 + 1)
    kernel /= kernel.sum()
    return np.convolve(values, kernel, 'same')


def envelopes(samples, width, height):
    """Per-sample (time, draw_level, paint_level, pan) from motion.track() output."""
    times = np.array([t for t, _ in samples], np.float64)
    n = len(samples)
    draw = np.zeros(n); paint = np.zeros(n); rub = np.zeros(n); pan = np.zeros(n)
    last = None
    for i, (_, s) in enumerate(samples):
        if s.point is None:
            last = None
            continue
        x, y = s.point[0] / width, s.point[1] / height
        pan[i] = max(-1., min(1., (x - .5) * 2))
        if last is not None and s.kind in ('draw', 'paint', 'erase'):
            dt = max(1e-6, times[i] - times[i - 1])
            speed = np.hypot(x - last[0], y - last[1]) / dt        # frame widths per second
            if s.kind == 'draw':
                draw[i] = min(1., speed / .35) ** .6
            elif s.kind == 'erase':
                rub[i] = min(1., speed / .5) ** .5
            else:
                paint[i] = min(1., speed / .6) ** .5
        last = (x, y) if s.kind in ('draw', 'paint', 'erase') else None
    return times, draw, paint, rub, pan


def synthesize(samples, total_seconds, width, height, volume=.8, seed=11, recordings=None):
    """Stereo int16 soundtrack (n, 2) for the animation.

    recordings: {'draw'|'paint'|'rub': mono samples} — YOUR recordings (or sounds
    made with Create sound). There are no built-in sounds: a tool without a
    recording is silent.
    """
    recordings = {k: v for k, v in (recordings or {}).items() if v is not None}
    count = max(1, int(round(total_seconds * RATE)))
    if not samples or not recordings:
        return np.zeros((count, 2), np.int16)
    t_audio = np.arange(count) / RATE
    times, draw, paint, rub, pan = envelopes(samples, width, height)
    rng = np.random.default_rng(seed)
    pan_a = _smooth(np.interp(t_audio, times, pan), int(.05 * RATE))
    mono = np.zeros(count)
    for kind, level, attack, gain in (('draw', draw, .012, 1.4), ('paint', paint, .03, 1.), ('rub', rub, .02, 1.)):
        if kind in recordings:
            env = _smooth(np.interp(t_audio, times, level), int(attack * RATE))
            mono += _bed(recordings[kind], count, rng) * np.clip(env * 1.5, 0, 1) * gain
    peak = np.abs(mono).max()
    if peak > 0:
        mono = mono / peak * .7 * max(0., min(1., volume))
    left = mono * np.sqrt((1 - pan_a * .35) / 2) * 1.414
    right = mono * np.sqrt((1 + pan_a * .35) / 2) * 1.414
    stereo = np.stack([left, right], 1)
    return np.clip(stereo * 32767, -32768, 32767).astype(np.int16)


# ------------------------------------------------------------ recorded sounds
# Real recordings (pencil on paper, a brush, an eraser) chosen by the user.
# They are looped from random places with short crossfades, so a 10-second
# recording covers any length, and played only while the pen moves.

SOUND_KINDS = ('draw', 'paint', 'rub')            # pencil, brush, eraser
_RECORDINGS = {}


def load_recording(path):
    """Mono float32 samples at RATE (cached), or None if the file cannot be read."""
    import shutil
    import subprocess
    if not path:
        return None
    path = Path(path)
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if key in _RECORDINGS:
        return _RECORDINGS[key]
    data = None
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        result = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(RATE),
                                 '-f', 's16le', '-'], capture_output=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode == 0 and result.stdout:
            data = np.frombuffer(result.stdout, np.int16).astype(np.float32) / 32768
    elif path.suffix.lower() == '.wav':
        try:
            with wave.open(str(path)) as f:
                raw = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
                raw = raw.reshape(-1, f.getnchannels()).mean(1)
                if f.getframerate() != RATE:
                    n = int(len(raw) * RATE / f.getframerate())
                    raw = np.interp(np.linspace(0, len(raw) - 1, n), np.arange(len(raw)), raw)
                data = raw.astype(np.float32)
        except (wave.Error, OSError):
            data = None
    if data is not None:
        data = _trim_silence(data)
        if len(data) < RATE // 10:
            data = None
    _RECORDINGS[key] = data
    return data


def _trim_silence(data):
    """Cut quiet parts at the start and end (before and after the actual scratching)."""
    level = np.sqrt(_smooth(data.astype(np.float64) ** 2, int(.02 * RATE)))
    loud = np.nonzero(level > level.max() * .12)[0]
    if len(loud) == 0:
        return data
    return data[loud[0]:loud[-1] + 1]


def _bed(recording, count, rng):
    """A continuous sound `count` samples long made of pieces of the recording."""
    fade = int(.06 * RATE)
    piece = max(fade * 3, min(len(recording), int(1.5 * RATE)))
    out = np.zeros(count + piece, np.float32)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)
    pos = 0
    while pos < count:
        n = min(piece, len(recording))
        start = int(rng.integers(0, max(1, len(recording) - n + 1)))
        chunk = recording[start:start + n].copy()
        chunk[:fade] *= ramp; chunk[-fade:] *= ramp[::-1]
        out[pos:pos + n] += chunk
        pos += n - fade
    out = out[:count]
    rms = float(np.sqrt(np.mean(out ** 2))) or 1.
    return out / rms * .25


def normalized_copy(source, target, peak=.89):
    """A WAV of the recording at a normal level (AI sounds come out very quiet),
    with the silent start/end cut off. Returns the target path, or None."""
    data = load_recording(source)
    if data is None:
        return None
    top = float(np.abs(data).max())
    if top <= 0:
        return None
    mono = np.clip(data / top * peak, -1, 1)
    fade = min(len(mono) // 4, int(.01 * RATE))
    if fade:
        ramp = np.linspace(0, 1, fade)
        mono[:fade] *= ramp; mono[-fade:] *= ramp[::-1]
    pcm = (mono * 32767).astype(np.int16)
    return write_wav(target, np.stack([pcm, pcm], 1))


def write_wav(path, stereo):
    path = Path(path)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(np.ascontiguousarray(stereo).tobytes())
    return path


def soundtrack(drawing, options, path, volume=.8):
    """Write the pencil/brush soundtrack WAV for this animation; returns the path."""
    import motion
    from frame_render import timeline_seconds
    total = timeline_seconds(drawing, options)
    w, h = options.get('width', 1920), options.get('height', 1080)
    samples = motion.track(drawing, options, total, TRACK_RATE)
    files = options.get('sound_files') or ()
    recordings = {kind: load_recording(p) for kind, p in zip(SOUND_KINDS, files) if p}
    return write_wav(path, synthesize(samples, total, w, h, volume, recordings=recordings))
