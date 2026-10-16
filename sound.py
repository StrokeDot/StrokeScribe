"""Pencil and brush sounds that follow the pen.

The soundtrack is synthesised from the pen track (motion.py), so it always
matches the animation: a scratchy pencil sound only while the pen is down and
moving (louder when it moves faster, silent during pen lifts), and a soft brush
sound while the colours are painted. Sounds pan gently with the hand's left /
right position. Generated with numpy; no sound files or extra packages.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 44100
TRACK_RATE = 120.


def _band(noise, low, high, rate=RATE):
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(len(noise), 1 / rate)
    # Soft-edged band so the sound is not 'ringing'.
    gain = 1 / (1 + (low / np.maximum(freqs, 1)) ** 4) / (1 + (freqs / high) ** 4)
    return np.fft.irfft(spectrum * gain, len(noise))


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
    draw = np.zeros(n); paint = np.zeros(n); pan = np.zeros(n)
    last = None
    for i, (_, s) in enumerate(samples):
        if s.point is None:
            last = None
            continue
        x, y = s.point[0] / width, s.point[1] / height
        pan[i] = max(-1., min(1., (x - .5) * 2))
        if last is not None and s.kind in ('draw', 'paint'):
            dt = max(1e-6, times[i] - times[i - 1])
            speed = np.hypot(x - last[0], y - last[1]) / dt        # frame widths per second
            if s.kind == 'draw':
                draw[i] = min(1., speed / .35) ** .6
            else:
                paint[i] = min(1., speed / .6) ** .5
        last = (x, y) if s.kind in ('draw', 'paint') else None
    return times, draw, paint, pan


def synthesize(samples, total_seconds, width, height, volume=.8, seed=11):
    """Stereo int16 soundtrack (n, 2) for the animation."""
    count = max(1, int(round(total_seconds * RATE)))
    t_audio = np.arange(count) / RATE
    if not samples:
        return np.zeros((count, 2), np.int16)
    times, draw, paint, pan = envelopes(samples, width, height)
    rng = np.random.default_rng(seed)
    # Envelopes at audio rate, with ~12 ms attack/release.
    env_draw = _smooth(np.interp(t_audio, times, draw), int(.012 * RATE))
    env_paint = _smooth(np.interp(t_audio, times, paint), int(.03 * RATE))
    pan_a = _smooth(np.interp(t_audio, times, pan), int(.05 * RATE))
    # Pencil: bright grainy scratch over a little paper body.
    noise = rng.standard_normal(count)
    scratch = _band(noise, 1200, 5500)
    body = _band(rng.standard_normal(count), 250, 1000) * .45
    grain = _band(rng.standard_normal(count), 15, 70)
    grain = 1 + .9 * np.abs(grain) / (np.abs(grain).max() + 1e-9)
    variation = 1 + .25 * _band(rng.standard_normal(count), .5, 3) / (1e-9 + np.abs(_band(rng.standard_normal(count), .5, 3)).max())
    pencil = (scratch * grain + body) * env_draw * variation
    # Brush: soft, darker swish with a slow bristle flutter.
    swish = _band(rng.standard_normal(count), 250, 2200)
    flutter = 1 + .3 * np.sin(2 * np.pi * 7 * t_audio + rng.uniform(0, 6))
    brush = swish * flutter * env_paint * .8
    mono = pencil + brush
    peak = np.abs(mono).max()
    if peak > 0:
        mono = mono / peak * .7 * max(0., min(1., volume))
    left = mono * np.sqrt((1 - pan_a * .35) / 2) * 1.414
    right = mono * np.sqrt((1 + pan_a * .35) / 2) * 1.414
    stereo = np.stack([left, right], 1)
    return np.clip(stereo * 32767, -32768, 32767).astype(np.int16)


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
    return write_wav(path, synthesize(samples, total, w, h, volume))
