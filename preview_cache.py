"""Ready-made preview frames, kept per segment of the video.

A segment is one element (its own frames, counted from the element's own
start) or one camera move between two elements. Every frame is stored under
the segment's *fingerprint* (everything that changes how that segment looks)
plus the frame number inside the segment. So:

- changing one element only makes that element's frames (and the moves next
  to it, or later elements drawn over it) unusable; the rest stay ready;
- making an element longer or shorter moves the later elements in the video,
  but their frames are still found, because they are counted from their own
  start, not from the start of the video.

Two tiers: recent frames in memory (fast, bounded), and frames made by
"Pre-render" on disk (bounded, oldest removed first) so a long video does not
have to fit in memory. Disk frames are JPEG when fully opaque (much smaller),
PNG when they have transparency.
"""
from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path

MEMORY_BUDGET = 600 * 1024 * 1024
DISK_BUDGET = 20 * 1024 ** 3


def default_folder():
    """%LOCALAPPDATA%/StrokeScribe/preview-cache (or STROKESCRIBE_PREVIEW_CACHE)."""
    forced = os.environ.get('STROKESCRIBE_PREVIEW_CACHE')
    if forced:
        return Path(forced)
    base = os.environ.get('LOCALAPPDATA') or os.path.join(Path.home(), '.cache')
    return Path(base) / 'StrokeScribe' / 'preview-cache'


def digest(value):
    """A short, stable name for a fingerprint (any repr-able value)."""
    return hashlib.sha1(repr(value).encode('utf-8', 'replace')).hexdigest()[:24]


def _opaque(image):
    """True when every pixel is fully opaque (JPEG keeps it exactly enough)."""
    try:
        import numpy as np
        from PySide6.QtGui import QImage
        if not image.hasAlphaChannel():
            return True
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        view = np.frombuffer(rgba.constBits(), np.uint8, rgba.sizeInBytes())
        return bool(view[3::4].min() == 255)
    except Exception:
        return False


class SegmentCache:
    def __init__(self, folder=None, memory_budget=MEMORY_BUDGET, disk_budget=DISK_BUDGET):
        self.memory_budget = memory_budget
        self.disk_budget = disk_budget
        self.folder = Path(folder) if folder else default_folder()
        self._memory = OrderedDict()
        self._memory_bytes = 0
        self._disk = None                     # name -> bytes, read lazily
        self._disk_bytes = 0

    # ---------------------------------------------------------------- keys
    @staticmethod
    def name(segment, index, width):
        return f'{digest(segment)}-{int(width)}-{int(index):06d}'

    # -------------------------------------------------------------- memory
    def get(self, segment, index, width):
        key = self.name(segment, index, width)
        frame = self._memory.get(key)
        if frame is not None:
            self._memory.move_to_end(key)
            return frame
        return self._from_disk(key)

    def has(self, segment, index, width):
        key = self.name(segment, index, width)
        return key in self._memory or key in self._disk_index()

    def put(self, segment, index, width, frame, disk=False):
        key = self.name(segment, index, width)
        if key not in self._memory:
            size = frame.sizeInBytes()
            while self._memory and self._memory_bytes + size > self.memory_budget:
                _, old = self._memory.popitem(last=False)
                self._memory_bytes -= old.sizeInBytes()
            self._memory[key] = frame
            self._memory_bytes += size
        if disk:
            self._to_disk(key, frame)

    def memory_full(self, frame_bytes):
        return self._memory_bytes + frame_bytes > self.memory_budget

    def forget_memory(self):
        self._memory.clear()
        self._memory_bytes = 0

    # ---------------------------------------------------------------- disk
    def _disk_index(self):
        if self._disk is None:
            self._disk = OrderedDict()
            self._disk_bytes = 0
            try:
                files = sorted(self.folder.glob('*.*'), key=lambda p: p.stat().st_mtime)
                for path in files:
                    size = path.stat().st_size
                    self._disk[path.stem] = (path, size)
                    self._disk_bytes += size
            except OSError:
                pass
        return self._disk

    def _from_disk(self, key):
        entry = self._disk_index().get(key)
        if entry is None:
            return None
        from PySide6.QtGui import QImage
        frame = QImage(str(entry[0]))
        if frame.isNull():
            self._drop(key)
            return None
        frame = frame.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.put_memory_only(key, frame)
        return frame

    def put_memory_only(self, key, frame):
        if key in self._memory:
            return
        size = frame.sizeInBytes()
        while self._memory and self._memory_bytes + size > self.memory_budget:
            _, old = self._memory.popitem(last=False)
            self._memory_bytes -= old.sizeInBytes()
        self._memory[key] = frame
        self._memory_bytes += size

    def _to_disk(self, key, frame):
        index = self._disk_index()
        if key in index:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            if _opaque(frame):
                path = self.folder / (key + '.jpg')
                ok = frame.save(str(path), 'JPG', 95)
            else:
                path = self.folder / (key + '.png')
                ok = frame.save(str(path), 'PNG', 80)
            if not ok:
                return
            size = path.stat().st_size
        except OSError:
            return
        index[key] = (path, size)
        self._disk_bytes += size
        while index and self._disk_bytes > self.disk_budget:
            old = next(iter(index))
            self._drop(old)

    def _drop(self, key):
        index = self._disk_index()
        entry = index.pop(key, None)
        if entry is None:
            return
        self._disk_bytes -= entry[1]
        try:
            entry[0].unlink()
        except OSError:
            pass

    def disk_bytes(self):
        self._disk_index()
        return self._disk_bytes

    def clear_disk(self):
        for key in list(self._disk_index()):
            self._drop(key)
