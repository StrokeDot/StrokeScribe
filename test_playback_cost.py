"""exp.10 (the user: review the code for performance): playback does less work per frame,
and nothing ticks while the app is idle."""
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class PlaybackCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        cls.w = Window(); cls.w.show(); APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.playing = False
        cls.w.close()

    def test_play_timer_runs_only_while_playing(self):
        w = self.w
        w.playing = False
        self.assertFalse(w.timer.isActive())          # idle: no 30-a-second wake-ups
        w.position = 0; w.last = time.perf_counter()
        w.playing = True
        self.assertTrue(w.timer.isActive())
        w.playing = False
        self.assertFalse(w.timer.isActive())

    def test_playback_does_not_rebuild_settings_every_frame(self):
        from unittest import mock
        w = self.w
        w.playing = False
        expected = w.scene_seconds()
        w.refresh(); APP.processEvents()
        w.position = 0; w.last = time.perf_counter()
        w.playing = True
        try:
            w.tick(); APP.processEvents()               # the preview is ready
            calls = []
            real = type(w).settings_state
            with mock.patch.object(type(w), 'settings_state',
                                   lambda self: calls.append(1) or real(self)):
                for _ in range(10):
                    w.tick(); APP.processEvents()
                self.assertAlmostEqual(w.scene_seconds(), expected, places=6)
            self.assertLess(len(calls), 10)             # was about 7 a frame
        finally:
            w.playing = False


class CheckerTests(unittest.TestCase):
    def test_checker_looks_like_before(self):
        from studio_workspace import _checker_brush
        img = QImage(40, 20, QImage.Format.Format_RGB32)
        img.fill(QColor('white'))
        p = QPainter(img)
        r = QRectF(3, 2, 30, 14)
        p.setBrushOrigin(3, 2)
        p.fillRect(r, _checker_brush())
        p.end()
        dark, light = QColor('#a9a9b2'), QColor('#d9d9de')
        self.assertEqual(img.pixelColor(3, 2), dark)       # first square dark, as before
        self.assertEqual(img.pixelColor(9, 2), light)
        self.assertEqual(img.pixelColor(9, 8), dark)
        self.assertEqual(img.pixelColor(2, 2), QColor('white'))   # nothing outside


if __name__ == '__main__':
    unittest.main()
