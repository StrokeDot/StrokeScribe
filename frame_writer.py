"""Writing export frames without waiting for them (exp.125).

Saving a 2560 x 1440 PNG took about 80 ms, more than drawing the frame itself: a 52 s
video at 60 fps spent most of its export time compressing PNGs, one after another, while
the drawing waited. Here the compression runs on several threads (zlib lets other threads
work while it compresses), the next frame is drawn meanwhile, and a frame identical to
the one before it (a hold, a pause) is copied instead of compressed again.

    writer = FrameWriter()
    writer.write(qimage, path)      # returns at once (waits only when far ahead)
    writer.close()                  # every file written (raises the first error)
"""
from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor


def _threads():
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def _encode(rgba, width, height, path):
    from PIL import Image
    Image.frombuffer('RGBA', (width, height), rgba, 'raw', 'RGBA', 0, 1).save(
        str(path), 'PNG', compress_level=1)
    return path


class FrameWriter:
    def __init__(self, threads=None):
        self.pool = ThreadPoolExecutor(max_workers=threads or _threads(), thread_name_prefix='frames')
        self.pending = []
        self.limit = 2 * (threads or _threads())
        self.previous = None                    # (pixels, future of its file)

    def write(self, image, path):
        from PySide6.QtGui import QImage
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width, height = rgba.width(), rgba.height()
        stride = rgba.bytesPerLine()
        data = bytes(rgba.constBits())[:stride * height]
        if stride != width * 4:                  # rows with padding: keep only the pixels
            data = b''.join(data[y * stride:y * stride + width * 4] for y in range(height))
        if self.previous is not None and self.previous[0] == data:
            source = self.previous[1]
            future = self.pool.submit(lambda s=source, t=path: shutil.copyfile(s.result(), t) and t)
        else:
            future = self.pool.submit(_encode, data, width, height, path)
            self.previous = (data, future)
        self.pending.append(future)
        while len(self.pending) > self.limit:     # do not run far ahead (memory)
            self.pending.pop(0).result()

    def flush(self):
        while self.pending:
            self.pending.pop(0).result()

    def close(self):
        try:
            self.flush()
        finally:
            self.pool.shutdown(wait=True)
            self.previous = None
