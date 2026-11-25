"""exp.42 (the user: StrokeScribe uses a lot of memory): ready frames are kept packed in memory
(JPEG for opaque frames, zlib for transparent ones); the last ones used stay as pixels."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


def picture(seed, alpha=255):
    img = QImage(960, 540, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255, alpha))
    p = QPainter(img)
    p.setPen(QColor(20, 60, 90)); p.setBrush(QColor(200, 120 + seed % 100, 40))
    for i in range(30):
        p.drawEllipse(30 * i + seed, 15 * i, 80, 50)
    p.end()
    return img


class Packed(unittest.TestCase):
    def test_opaque_frames_are_small_and_come_back_close(self):
        from preview_cache import pack, unpack
        f = picture(3)
        packed = pack(f)
        self.assertEqual(packed[0], 'jpg')
        self.assertLess(len(packed[1]), f.sizeInBytes() // 8)
        back = unpack(packed)
        self.assertEqual(back.size(), f.size()); self.assertEqual(back.format(), f.format())
        a, b = f.pixelColor(400, 200), back.pixelColor(400, 200)
        self.assertLess(abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()), 30)

    def test_transparent_frames_come_back_exactly(self):
        from preview_cache import pack, unpack
        f = picture(5, alpha=0).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        packed = pack(f)
        self.assertEqual(packed[0], 'zip')
        back = unpack(packed)
        self.assertEqual(back, f)

    def test_many_frames_fit_and_the_last_ones_stay_as_pixels(self):
        import preview_cache
        from preview_cache import SegmentCache
        with tempfile.TemporaryDirectory() as tmp:
            budget = 40 * 2 ** 20                         # 40 MB: 20 raw frames before exp.42
            cache = SegmentCache(tmp, memory_budget=budget)
            frames = [picture(i) for i in range(120)]
            for i, f in enumerate(frames):
                cache.put(('s',), i, 960, f)
            self.assertLessEqual(cache._memory_bytes, budget)
            kept = sum(cache.has(('s',), i, 960) for i in range(120))
            self.assertEqual(kept, 120)                    # every one (packed)
            self.assertLessEqual(len(cache._hot), preview_cache.HOT_FRAMES)
            self.assertIs(cache.get(('s',), 119, 960), frames[119])      # recent: the same pixels
            old = cache.get(('s',), 3, 960)                 # packed: comes back
            self.assertEqual(old.size(), frames[3].size())
            self.assertFalse(cache.memory_full(960 * 540 * 4) and cache._memory_bytes < budget * .5)

    def test_jpeg_from_disk_is_kept_as_it_is(self):
        from preview_cache import SegmentCache
        with tempfile.TemporaryDirectory() as tmp:
            cache = SegmentCache(tmp)
            cache.put(('d',), 0, 960, picture(1), disk=True)
            fresh = SegmentCache(tmp)
            back = fresh.get(('d',), 0, 960)
            self.assertIsNotNone(back)
            key = fresh.name(('d',), 0, 960)
            self.assertEqual(fresh._memory[key][1], next(p for p in os.scandir(tmp) if p.name.endswith('.jpg')) and
                             open(os.path.join(tmp, key + '.jpg'), 'rb').read())


if __name__ == '__main__':
    unittest.main()
