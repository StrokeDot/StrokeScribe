"""exp.67 (the user: the sticker's animation and the hand are not together): the hand's pen tip
is where the sticker's new ink appears, for every shape (the rich ones of exp.52/53 too)."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class PenOnTheInk(unittest.TestCase):
    def test_every_shape(self):
        import numpy as np
        import overlays
        import stickers
        from PySide6.QtGui import QImage
        saved = dict(stickers._HAND)
        stickers._HAND.clear(); stickers._HAND.update(corner='Bottom right')
        W, H = 640, 360

        def colours(s, t):
            img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied); img.fill(0)
            overlays.paint(img, [s], t, hands=False)
            return np.frombuffer(img.constBits(), np.uint8).reshape(H, img.bytesPerLine() // 4, 4)[:, :W].astype(int)
        try:
            for shape in stickers.SHAPES:
                with self.subTest(shape=shape):
                    s = stickers.new(shape, 0., 6.); s.update(x=.5, y=.5, size=.4, drawing='Hand: everything')
                    start, seconds = float(s['start']), float(s.get('draw_seconds', .8))
                    gaps, prev = [], None
                    for t in np.linspace(start, start + seconds, 36):
                        cur = colours(s, t)
                        if prev is not None:
                            ys, xs = np.nonzero(np.abs(cur - prev).sum(axis=2) > 60)
                            tip = stickers.hand_tip(s, t, W, H)
                            if len(xs) > 10 and tip is not None:
                                gaps.append(float(np.hypot(xs - tip[0], ys - tip[1]).min()))
                        prev = cur
                    self.assertGreater(len(gaps), 5)
                    self.assertLess(float(np.median(gaps)), 3.)          # the pen is on the new ink
        finally:
            stickers._HAND.clear(); stickers._HAND.update(saved)

    def test_without_a_hand_they_animate_as_before(self):
        import sticker_art
        item = {'shape': 'Double arrow', 'drawing': 'Animated'}
        self.assertFalse(sticker_art.by_hand(item))


if __name__ == '__main__':
    unittest.main()
