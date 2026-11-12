"""Built-in drawing sounds, made from the pen's own movement (1.0.1-experimental).

The user (after 1.0.0): "reproduce the exact sound of the pencil drawing... a sound in
paper", to save the time of finding and adding recordings.

Nothing is downloaded and nothing is looped: the sound is synthesized for the animation from
where the pen actually is at every moment (motion.track, the same pen track that moves the
hand). A pencil on paper sounds the way it does because the tip rubs over the paper's grain:
the faster it moves, the quicker the bumps of the grain pass under it, so the sound gets
louder and brighter with speed, and it stops the moment the pen stops or lifts. That is what
is modelled (procedural friction sound, after A. Farnell, "Designing Sound"):

* the paper grain: a fixed bumpy surface (several layers of roughness, from paper fibres of a
  hundredth of a millimetre to the tooth of the sheet), read along the pen's path at its real
  speed; the grain belongs to the paper, so the same spot sounds the same;
* graphite crackle: tiny stick-slip clicks as grains of graphite break off, more of them the
  faster the pen moves;
* a soft tick when the tip touches the paper;
* the tone of a sheet on a desk: no rumble, a scratchy presence around 3-5 kHz, the highest
  hiss rolled off; the loudness follows the pen's speed, with a slowly changing hand pressure.

The soft brush (a dry swish: coarser grain, no crackle, darker) and the eraser (rubber
rubbing: low and rough) use the same model with their own settings. Everything is
deterministic (seeded), so the preview and the export sound the same.
"""
from __future__ import annotations

import numpy as np

RATE = 44100
PAPER_MM = 297.          # the frame's width is a sheet this wide (A4 across)

# grain: (wavelength mm, weight) layers; crackle: (clicks per mm, loudness against the grain);
# tone: (high-pass Hz, presence Hz, presence gain, low-pass Hz); full: mm/s for full loudness;
# tick: loudness of the touch-down
TYPES = {
    'pencil': dict(grain=((.012, .30), (.03, .28), (.08, .22), (.25, .12), (1.2, .08)),
                   crackle=(4., .9), tone=(450., 3400., 2.4, 8500.), full=60., tick=.8),
    'brush': dict(grain=((.05, .25), (.15, .35), (.5, .25), (2., .15)),
                  crackle=(0., 0.), tone=(200., 1600., 1.6, 5000.), full=110., tick=.2),
    'eraser': dict(grain=((.08, .3), (.3, .35), (1., .25), (3., .1)),
                   crackle=(1.2, .5), tone=(150., 850., 1.9, 3600.), full=80., tick=.15),
}
TOOL_SAMPLES = {'draw': 'draw', 'paint': 'paint', 'rub': 'erase'}   # tool: motion sample kind


def _fir(tone, taps=1025):
    """A linear-phase filter kernel for a tone (frequency sampling + window), peak gain 1."""
    hp, peak, gain, lp = tone
    n = 4096
    f = np.maximum(np.fft.rfftfreq(n, 1. / RATE), 1.)
    high = 1. / np.sqrt(1. + (hp / f) ** 4)                 # 2nd-order high-pass
    low = 1. / np.sqrt(1. + (f / lp) ** 6)                  # 3rd-order low-pass
    bell = 1. + (gain - 1.) * np.exp(-.5 * (np.log2(f / peak) / .7) ** 2)
    h = np.fft.irfft(high * low * bell, n)
    h = np.roll(h, taps // 2)[:taps] * np.hanning(taps)
    return h / max(1e-9, float(np.abs(np.fft.rfft(h, n)).max()))


def _convolve(x, kernel, block=1 << 16):
    """Overlap-add FFT convolution, centred (same length as x), a block at a time."""
    m = len(kernel)
    size = 1
    while size < block + m - 1:
        size <<= 1
    K = np.fft.rfft(kernel, size)
    out = np.zeros(len(x) + m - 1)
    for start in range(0, len(x), block):
        chunk = x[start:start + block]
        y = np.fft.irfft(np.fft.rfft(chunk, size) * K, size)[:len(chunk) + m - 1]
        out[start:start + len(y)] += y
    half = m // 2
    return out[half:half + len(x)]


def _smooth(values, samples):
    if samples <= 1:
        return values
    kernel = np.hanning(samples * 2 + 1)
    return _convolve(values, kernel / kernel.sum())


def _grain_slope(distance, grain, rng):
    """How steep the paper is under the tip (per mm), read along the path (distance in mm)."""
    top = float(distance.max()) if distance.size else 0.
    out = np.zeros_like(distance)
    for wavelength, weight in grain:
        points = rng.standard_normal(int(top / wavelength) + 3)
        pos = distance / wavelength
        i = np.minimum(pos.astype(np.int64), points.size - 2)
        out += weight * (points[i + 1] - points[i]) / wavelength     # slope of the layer
        # (piecewise linear between the bumps: the slope steps at every bump)
    return out


def tool_sound(kind, distance, speed, down, rng):
    """Mono sound of one kind ('pencil', 'brush', 'eraser'): distance (mm along the path),
    speed (mm/s) and down (0/1) at every audio sample."""
    spec = TYPES[kind]
    n = distance.size
    if n == 0 or not down.any():
        return np.zeros(n)
    on = down > .5
    # the grain passing under the tip (faster pen: the bumps pass quicker, a brighter sound)
    # (the slope changes at every bump, as often as speed / bump size: its sound reaches up to
    # about that frequency, a few kHz for a pencil at a normal speed)
    excite = _grain_slope(distance, spec['grain'], rng)
    excite = excite - _smooth(excite, int(.01 * RATE))      # no drift
    level = float(np.sqrt(np.mean(excite[on] ** 2))) or 1.
    excite /= level
    # the fine hiss of the tip
    excite += rng.standard_normal(n) * .25 * np.clip(speed / spec['full'], 0, 1.5)
    # graphite crackle: stick-slip clicks, a random rain whose rate follows the speed
    rate, loud = spec['crackle']
    if rate > 0:
        p = np.clip(rate * speed / RATE, 0, .3) * down
        hits = (rng.random(n) < p) * rng.lognormal(0., .5, n) * loud * 3.
        click = rng.standard_normal(64) * np.exp(-np.arange(64) / 9.)
        excite += _convolve(hits, click / np.abs(click).max())
    # the tip touching the paper
    touch = np.flatnonzero(np.diff(on.astype(np.int8), prepend=0) > 0)
    if touch.size and spec['tick'] > 0:
        tick = np.zeros(n)
        tick[touch] = spec['tick'] * 6.
        burst = rng.standard_normal(200) * np.exp(-np.arange(200) / 30.)
        excite += _convolve(tick, burst / np.abs(burst).max())
    sound = _convolve(excite, _fir(spec['tone']))
    # loudness: the pen's speed and a slowly changing hand pressure, only while it is down
    amount = np.clip(speed / spec['full'], 0, 1.4) ** .55
    pressure = np.clip(1. + 1.2 * _smooth(rng.standard_normal(n), int(.3 * RATE)) * 9., .55, 1.45)
    env = _smooth(amount * down, int(.004 * RATE)) * pressure
    return sound * env


def from_track(samples, total_seconds, width, tools, seed=11):
    """{tool: mono} for tools {'draw'|'paint'|'rub': 'pencil'|'brush'|'eraser'}, from
    motion.track output [(time, sample with .point (pixels) and .kind)]."""
    count = max(1, int(round(total_seconds * RATE)))
    if not samples:
        return {tool: np.zeros(count) for tool in tools}
    t_audio = np.arange(count) / RATE
    times = np.array([t for t, _ in samples], np.float64)
    mm = PAPER_MM / max(1., float(width))
    xs = np.array([s.point[0] if s.point is not None else np.nan for _, s in samples]) * mm
    ys = np.array([s.point[1] if s.point is not None else np.nan for _, s in samples]) * mm
    names = [s.kind for _, s in samples]
    out = {}
    for index, (tool, kind) in enumerate(sorted(tools.items())):
        rng = np.random.default_rng((seed, index, sorted(TYPES).index(kind)))
        want = TOOL_SAMPLES.get(tool, tool)
        on = np.array([k == want and not np.isnan(x) for k, x in zip(names, xs)])
        moving = on & np.concatenate([[False], on[:-1]])
        step = np.hypot(np.diff(xs, prepend=xs[:1]), np.diff(ys, prepend=ys[:1]))
        step = np.where(moving & np.isfinite(step), step, 0.)
        travelled = np.cumsum(step)
        dt = np.maximum(1e-6, np.diff(times, prepend=times[:1] - 1e-6))
        speed = np.where(moving, step / dt, 0.)
        speed_a = np.maximum(0., np.interp(t_audio, times, speed))
        # the grain is read at the pen's speed, but a very quick scribble does not keep getting
        # brighter (the tip skips over the finest grain): the reading speed levels off
        top = TYPES[kind]['full'] * 2.
        distance = np.cumsum(top * np.tanh(speed_a / top)) / RATE
        down = (np.interp(t_audio, times, on.astype(np.float64)) > .5).astype(np.float64)
        out[tool] = tool_sound(kind, distance, speed_a, down, rng)
    return out
