"""Pencil sound that follows the drawing, made from a real recording (1.0.1-experimental.6).

The user: "make a sound that adjusts to the drawing... recreate a pencil sound without all
that noise in the background". The synthesized sound (sound_synth.py) was rejected: it was
noise. The earlier recordings mode (sound._bed) looped pieces of a recording under a loudness
envelope, so the scratching had its own rhythm, not the hand's.

Here the recording is cut into its single pencil strokes, and the hand's own strokes choose
and place them:

1. Clean: the recording's steady background (room hiss, hum) is measured in its quietest
   moments and gated out, band by band (spectral gating, like Audacity's noise reduction);
   below 150 Hz everything is removed (desk thumps, handling).
2. Strokes in the recording: each scratch starts with an attack and dies away; the recording
   is cut at the quiet moments between them into short pieces, each with a smooth start and
   end.
3. Strokes of the hand: the pen track (motion.track, the same as the hand's movement) is cut
   wherever the pen goes down, lifts, stops or turns back (every leg of a zigzag is one
   stroke). Each hand stroke gets a recorded stroke of about its length (stretched a little to
   fit, or several in a row for a long line), as loud as the hand is quick, panned with the
   hand. While the pen is up there is no sound at all.

Everything is deterministic (seeded): the preview and the export sound the same.
"""
from __future__ import annotations

import numpy as np

RATE = 44100
MIN_PIECE = .04            # s: shortest recorded stroke kept
MAX_PIECE = .7             # s: longest piece (a long scratch is cut at its quietest point)
STRETCH = (.75, 1.35)      # how much a recorded stroke may be slowed down / sped up to fit
TURN = -.2                 # cos of the angle between two moves that counts as turning back
FULL_SPEED = 900.          # pixels a second (on a 1920 wide frame) for full loudness

_PIECES = {}


def _stft(x, n=1024, hop=256):
    win = np.hanning(n).astype(np.float32)
    pad = np.concatenate([np.zeros(n // 2, np.float32), x.astype(np.float32), np.zeros(n, np.float32)])
    frames = 1 + (len(pad) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    return np.fft.rfft(pad[idx] * win, axis=1), win


def _istft(spec, win, length, n=1024, hop=256):
    frames = np.fft.irfft(spec, n=n, axis=1).astype(np.float32) * win
    out = np.zeros(hop * (len(frames) - 1) + n, np.float32)
    norm = np.zeros_like(out)
    for i, f in enumerate(frames):
        out[i * hop:i * hop + n] += f
        norm[i * hop:i * hop + n] += win ** 2
    out = out / np.maximum(norm, 1e-6)
    return out[n // 2:n // 2 + length]


def clean(recording):
    """The recording without its steady background noise and without rumble (float32)."""
    x = np.asarray(recording, np.float32)
    if x.size < 2048:
        return x
    spec, win = _stft(x)
    mag = np.abs(spec)
    energy = mag.sum(1)
    quiet = energy <= np.percentile(energy, 15)            # the quietest moments: background only
    noise = np.median(mag[quiet], axis=0) if quiet.sum() >= 4 else np.percentile(mag, 10, axis=0)
    # a soft gate per band: what stands clearly above the background stays, the rest goes
    ratio = mag / np.maximum(noise[None, :] * 2.2, 1e-9)
    gain = np.clip((ratio - 1.) / 1.5, 0, 1) ** 1.5
    # smooth the gate a little over time and frequency (no "musical noise" chirps)
    import cv2
    gain = cv2.GaussianBlur(gain.astype(np.float32), (5, 3), 0)
    freqs = np.fft.rfftfreq(1024, 1. / RATE)
    gain *= (1. / np.sqrt(1. + (150. / np.maximum(freqs, 1.)) ** 6))[None, :]   # rumble out
    return _istft(spec * gain, win, x.size)


def _level(x, ms=8):
    n = max(1, int(ms / 1000 * RATE))
    k = np.ones(n) / n
    return np.sqrt(np.convolve(x.astype(np.float64) ** 2, k, mode='same'))


def pieces(recording, key=None):
    """The recording's single strokes: a list of float32 arrays (cleaned, faded in and out,
    each at the same loudness)."""
    if key is not None and key in _PIECES:
        return _PIECES[key]
    x = clean(recording)
    level = _level(x)
    top = float(np.percentile(level, 99)) or 1.
    loud = level > top * .12
    out = []
    i, n = 0, len(x)
    fade = int(.006 * RATE)
    while i < n:
        if not loud[i]:
            i += 1
            continue
        j = i
        while j < n and (loud[j] or (j - i) < MIN_PIECE * RATE * .5):
            j += 1
        start, end = max(0, i - fade), min(n, j + fade)
        # a long scratch: cut at its quietest points into pieces of at most MAX_PIECE
        while end - start > MAX_PIECE * RATE:
            lo, hi = start + int(.15 * RATE), start + int(MAX_PIECE * RATE)
            cut = lo + int(np.argmin(level[lo:hi]))
            out.append(x[start:cut + fade].copy())
            start = cut - fade
        if end - start >= MIN_PIECE * RATE:
            out.append(x[start:end].copy())
        i = j + 1
    shaped = []
    for p in out:
        f = min(fade, len(p) // 4)
        if f > 0:
            ramp = np.linspace(0, 1, f, dtype=np.float32)
            p[:f] *= ramp
            p[-f:] *= ramp[::-1]
        rms = float(np.sqrt(np.mean(p ** 2)))
        if rms > 1e-6:
            shaped.append((p / rms * .25).astype(np.float32))
    if key is not None:
        while len(_PIECES) >= 8:
            _PIECES.pop(next(iter(_PIECES)))
        _PIECES[key] = shaped
    return shaped


def hand_strokes(samples, want, width):
    """The hand's strokes for one tool: [(start s, end s, speed px/s, x share)]; a stroke ends
    where the pen lifts, stops, or turns back."""
    strokes = []
    scale = 1920. / max(1., float(width))
    cur = None
    prev_v = None
    last = None
    for t, s in samples:
        on = s.kind == want and s.point is not None
        if not on:
            if cur is not None:
                strokes.append(cur)
            cur, prev_v, last = None, None, None
            continue
        if last is None:
            last = (t, s.point)
            continue
        dt = max(1e-6, t - last[0])
        v = ((s.point[0] - last[1][0]) * scale / dt, (s.point[1] - last[1][1]) * scale / dt)
        speed = float(np.hypot(*v))
        moving = speed > 15.
        turned = (prev_v is not None and moving and
                  (v[0] * prev_v[0] + v[1] * prev_v[1]) / max(1e-9, speed * np.hypot(*prev_v)) < TURN)
        if cur is not None and (not moving or turned):
            strokes.append(cur)
            cur = None
        if moving:
            if cur is None:
                cur = [last[0], t, 0., 0., 0]
            cur[1] = t
            cur[2] += speed
            cur[3] += s.point[0] / max(1., float(width))
            cur[4] += 1
            prev_v = v
        else:
            prev_v = None
        last = (t, s.point)
    if cur is not None:
        strokes.append(cur)
    return [(a, b, sp / max(1, k), x / max(1, k)) for a, b, sp, x, k in strokes if b - a > .015 and k]


def _fit(piece, seconds):
    """The piece resampled to last `seconds` (within STRETCH)."""
    want = max(1, int(seconds * RATE))
    factor = np.clip(want / max(1, len(piece)), *STRETCH)
    n = max(1, int(len(piece) * factor))
    return np.interp(np.linspace(0, len(piece) - 1, n), np.arange(len(piece)), piece).astype(np.float32)


def render(samples, total_seconds, width, recording, want='draw', seed=11, key=None):
    """(mono, pan) float arrays: the recording's strokes placed on the hand's strokes."""
    count = max(1, int(round(total_seconds * RATE)))
    mono = np.zeros(count + RATE, np.float32)
    pan = np.zeros(count + RATE, np.float32)
    weight = np.zeros(count + RATE, np.float32)
    bank = pieces(recording, key)
    if not bank:
        return mono[:count], pan[:count]
    lengths = np.array([len(p) / RATE for p in bank])
    rng = np.random.default_rng(seed)
    last_pick = -1
    for start, end, speed, x in hand_strokes(samples, want, width):
        seconds = end - start
        gain = float(np.clip(speed / FULL_SPEED, .08, 1.3) ** .5)
        pos = int(start * RATE)
        left = seconds
        while left > .02:
            # a recorded stroke of about the right length (several for a long line), never the
            # same one twice in a row
            close = np.argsort(np.abs(lengths - min(left, MAX_PIECE)))[:4]
            choices = [int(c) for c in close if int(c) != last_pick] or [int(close[0])]
            pick = choices[int(rng.integers(0, len(choices)))]
            last_pick = pick
            part = _fit(bank[pick], min(left, MAX_PIECE * STRETCH[1]))
            part = part * gain * float(rng.uniform(.85, 1.1))
            stop = min(len(mono), pos + len(part))
            mono[pos:stop] += part[:stop - pos]
            pan[pos:stop] += (x * 2 - 1) * np.abs(part[:stop - pos])
            weight[pos:stop] += np.abs(part[:stop - pos])
            used = len(part) / RATE
            left -= used * .92                         # a little overlap between pieces
            pos += int(used * .92 * RATE)
    pan = np.where(weight > 1e-6, pan / np.maximum(weight, 1e-6), 0.)
    return mono[:count], pan[:count]
