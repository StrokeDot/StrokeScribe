"""1.0.1-experimental.6: a pencil sound that follows the drawing, from a real recording."""
import math
import unittest
from dataclasses import dataclass

import numpy as np

import sound_strokes as S

R = S.RATE


@dataclass(frozen=True)
class Pen:
    point: tuple | None
    kind: str | None


def recording(seed=0, hiss=.02):
    """Pencil-like scratches with a steady hiss behind them."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(R * 8).astype(np.float32) * hiss
    for k in range(12):
        n = int(R * rng.uniform(.12, .35)); s = int(R * (.3 + k * .6))
        env = np.minimum(1, np.arange(n) / 200) * np.exp(-np.arange(n) / (n * .5))
        x[s:s + n] += np.convolve(rng.standard_normal(n), np.ones(4) / 4, 'same') * env * .4
    return x


def zigzag_track(seconds=4.):
    """Drawing: a zigzag of 0.25 s legs for 2 s, the pen up for 1 s, a line, then nothing."""
    out = []
    for i in range(int(seconds * 120) + 1):
        t = i / 120
        if t < 2:
            leg, f = int(t / .25), (t % .25) / .25
            x = 500 + 300 * (f if leg % 2 == 0 else 1 - f)
            out.append((t, Pen((x, 400 + leg * 10), 'draw')))
        elif t < 3:
            out.append((t, Pen((800, 600), 'lift')))
        elif t < 3.6:
            out.append((t, Pen((300 + (t - 3) * 800, 700), 'draw')))
        else:
            out.append((t, Pen(None, None)))
    return out


class StrokeSoundTests(unittest.TestCase):
    def test_background_noise_is_cleaned_out(self):
        x = recording()
        c = S.clean(x)
        quiet = lambda a: float(np.sqrt(np.mean(a[:int(R * .25)] ** 2)))
        self.assertLess(quiet(c), quiet(x) * .1)              # at least 20 dB less hiss
        loud = slice(int(R * .3), int(R * .4))
        self.assertGreater(float(np.abs(c[loud]).max()), float(np.abs(x[loud]).max()) * .5)

    def test_the_recording_is_cut_into_its_strokes(self):
        bank = S.pieces(recording())
        self.assertGreaterEqual(len(bank), 10)
        for p in bank:
            self.assertLess(abs(float(p[0])), .05); self.assertLess(abs(float(p[-1])), .05)   # faded

    def test_every_leg_of_a_zigzag_is_a_stroke(self):
        strokes = S.hand_strokes(zigzag_track(), 'draw', 1920)
        self.assertGreaterEqual(len(strokes), 8)               # 8 legs + the line
        self.assertLessEqual(len(strokes), 10)

    def test_the_sound_follows_the_hand(self):
        track = zigzag_track()
        mono, _ = S.render(track, 4., 1920, recording(), 'draw')
        rms = lambda a, b: float(np.sqrt(np.mean(mono[int(a * R):int(b * R)] ** 2)))
        self.assertGreater(rms(.1, 1.9), .02)                  # drawing: sound
        self.assertLess(rms(2.4, 2.9), 1e-4)                   # pen up: silence
        self.assertGreater(rms(3.05, 3.55), .02)               # the line: sound
        self.assertLess(rms(3.9, 4.), 1e-4)                    # done: silence
        again, _ = S.render(track, 4., 1920, recording(), 'draw')
        self.assertTrue(np.array_equal(mono, again))           # preview and export the same

    def test_faster_hand_louder(self):
        def line(speed):
            return [(i / 120, Pen((100 + speed * i / 120, 300), 'draw')) for i in range(121)]
        slow, _ = S.render(line(150), 1., 1920, recording(), 'draw')
        fast, _ = S.render(line(900), 1., 1920, recording(), 'draw')
        self.assertGreater(float(np.sqrt(np.mean(fast ** 2))), float(np.sqrt(np.mean(slow ** 2))) * 1.5)


if __name__ == '__main__':
    unittest.main()
