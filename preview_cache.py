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
have to fit in memory. The memory tier grows with the computer's memory.

Disk frames are stored as raw pixels (exp.101): reading one back is a plain file
read, a few milliseconds. PNG frames (older versions) took tens of milliseconds
to decode each, too slow to play from at 30 frames a second. Older .png / .jpg
frames are still read.
"""
from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path

MEMORY_BUDGET = 600 * 1024 * 1024            # the least; more on computers with more memory
DISK_BUDGET = 20 * 1024 ** 3
RAW_MAGIC = b'SSRAW1'


def physical_memory():
    """Bytes of memory in this computer, or None when unknown."""
    try:
        if os.name == 'nt':
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                            ('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong),
                            ('page_total', ctypes.c_ulonglong), ('page_free', ctypes.c_ulonglong),
                            ('virtual_total', ctypes.c_ulonglong), ('virtual_free', ctypes.c_ulonglong),
                            ('extended', ctypes.c_ulonglong)]
            status = Status(); status.length = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total)
            return None
        return int(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'))
    except Exception:
        return None


def memory_budget():
    """Memory for ready frames: a sixth of the computer's memory, between 600 MB and 4 GB
    (16 GB -> 2.7 GB, about 1300 frames at the preview size; 64 GB -> 4 GB)."""
    total = physical_memory()
    if not total:
        return MEMORY_BUDGET
    return int(max(MEMORY_BUDGET, min(4 * 1024 ** 3, total // 6)))


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


memory_budget_default = memory_budget


class SegmentCache:
    def __init__(self, folder=None, memory_budget=None, disk_budget=DISK_BUDGET):
        self.memory_budget = memory_budget if memory_budget is not None else memory_budget_default()
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
                # Only ready frames: nothing else in the folder is ever counted or deleted.
                files = sorted((p for p in self.folder.glob('*.*') if p.suffix.lower() in ('.raw', '.png', '.jpg')),
                               key=lambda p: p.stat().st_mtime)
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
        path = entry[0]
        if path.suffix == '.raw':
            frame = _read_raw(path)
        else:
            frame = QImage(str(path))
            if not frame.isNull():
                frame = frame.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        if frame is None or frame.isNull():
            self._drop(key)
            return None
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
            path = self.folder / (key + '.raw')
            if not _write_raw(path, frame):
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


def _write_raw(path, frame):
    """The frame's pixels as they are (ARGB32 premultiplied), with its size in front."""
    try:
        import struct
        from PySide6.QtGui import QImage
        image = frame if frame.format() == QImage.Format.Format_ARGB32_Premultiplied else \
            frame.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        w, h, line = image.width(), image.height(), image.bytesPerLine()
        temp = path.with_name(path.name + '.part')
        with open(temp, 'wb') as f:
            f.write(RAW_MAGIC + struct.pack('<III', w, h, line))
            f.write(bytes(image.constBits())[:line * h])
        os.replace(temp, path)
        return True
    except Exception:
        return False


def _read_raw(path):
    try:
        import struct
        from PySide6.QtGui import QImage
        data = Path(path).read_bytes()
        if data[:len(RAW_MAGIC)] != RAW_MAGIC:
            return None
        w, h, line = struct.unpack('<III', data[len(RAW_MAGIC):len(RAW_MAGIC) + 12])
        pixels = data[len(RAW_MAGIC) + 12:]
        if len(pixels) < line * h:
            return None
        return QImage(pixels, w, h, line, QImage.Format.Format_ARGB32_Premultiplied).copy()
    except Exception:
        return None
