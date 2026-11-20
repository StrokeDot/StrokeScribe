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

exp.9 (the user: the cache had grown to 20 GB): disk frames are compressed. An opaque
frame (the usual case) is a JPEG at quality 92: about 120 KB instead of 2 MB of raw
pixels, decoded in about 4 ms (fast enough to play from at 30 frames a second; PNG,
too slow, is not used). A frame with transparency is its raw pixels packed with fast
zlib (about a third). The disk limit is 2 GB (about 9 minutes of pre-rendered video),
and every app version has its own folder: frames of older versions (never shown again)
are deleted when the app starts.

exp.42 (the user: StrokeScribe uses a lot of memory): the frames in memory are kept
compressed the same way (JPEG 92 for opaque frames, about 66 KB instead of 2 MB; zlib for
frames with transparency), with only the last few frames used kept as pixels, so scrubbing
back and forth stays instant. Opening a compressed frame takes about 3 ms (a frame lasts
33 ms). The memory limit is a sixteenth of the computer's memory, 256 MB to 1 GB: about
eight minutes of frames, where 4 GB of raw pixels held about two.
"""
from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path

MEMORY_BUDGET = 256 * 1024 * 1024            # the least; more on computers with more memory (exp.42)
MEMORY_MOST = 1024 ** 3                      # exp.42: frames are compressed: 1 GB is about 8 minutes
HOT_FRAMES = 24                              # exp.42: the last frames used, kept as pixels
DISK_BUDGET = 2 * 1024 ** 3
RAW_MAGIC = b'SSRAW1'
ZIP_MAGIC = b'SSZIP1'
JPEG_QUALITY = 92
FRAME_SUFFIXES = ('.raw', '.zraw', '.jpg', '.png')


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
    """Memory for ready frames: a sixteenth of the computer's memory, between 256 MB and 1 GB
    (exp.42: the frames are compressed: 8 GB -> 512 MB, 16 GB or more -> 1 GB, about 15000
    frames at the preview size)."""
    total = physical_memory()
    if not total:
        return MEMORY_BUDGET
    return int(max(MEMORY_BUDGET, min(MEMORY_MOST, total // 16)))


def pack(frame):
    """exp.42: a frame made small for memory: (kind, data, width, height, line, format)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage
    fmt = int(frame.format().value) if hasattr(frame.format(), 'value') else int(frame.format())
    if _opaque(frame):
        data = QByteArray(); buf = QBuffer(data); buf.open(QIODevice.OpenModeFlag.WriteOnly)
        if frame.save(buf, 'JPG', JPEG_QUALITY):
            return ('jpg', bytes(data), frame.width(), frame.height(), 0, fmt)
    import zlib
    image = frame if frame.format() == QImage.Format.Format_ARGB32_Premultiplied else \
        frame.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    line, h = image.bytesPerLine(), image.height()
    return ('zip', zlib.compress(bytes(image.constBits())[:line * h], 1), image.width(), h, line, fmt)


def unpack(packed):
    """exp.42: the frame back from pack (in its own format)."""
    from PySide6.QtGui import QImage
    kind, data, w, h, line, fmt = packed
    if kind == 'jpg':
        image = QImage.fromData(data, 'JPG')
    else:
        import zlib
        image = QImage(zlib.decompress(data), w, h, line, QImage.Format.Format_ARGB32_Premultiplied).copy()
    if image.isNull():
        return None
    want = QImage.Format(fmt)
    return image if image.format() == want else image.convertToFormat(want)


def _packed_size(packed):
    return len(packed[1]) + 64


def default_folder():
    """%LOCALAPPDATA%/StrokeScribe/preview-cache (or STROKESCRIBE_PREVIEW_CACHE)."""
    forced = os.environ.get('STROKESCRIBE_PREVIEW_CACHE')
    if forced:
        return Path(forced)
    base = os.environ.get('LOCALAPPDATA') or os.path.join(Path.home(), '.cache')
    return Path(base) / 'StrokeScribe' / 'preview-cache'


try:
    from version import APP_VERSION as _VERSION
except Exception:                      # pragma: no cover
    _VERSION = ''


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


def _version_folder(name):
    return 'v-' + ''.join(c if c.isalnum() or c in '.-' else '_' for c in str(name or 'dev'))


def remove_old_frames(base, keep):
    """Deletes ready frames of other app versions (and of versions before exp.9, kept directly
    in the cache folder): their names include the version, so they are never shown again."""
    base = Path(base)
    try:
        entries = list(base.iterdir())
    except OSError:
        return
    import shutil
    for entry in entries:
        try:
            if entry.is_dir() and entry.name.startswith('v-') and entry.name != keep:
                shutil.rmtree(entry, ignore_errors=True)
            elif entry.is_file() and (entry.suffix.lower() in FRAME_SUFFIXES or entry.name.endswith('.part')):
                entry.unlink()
        except OSError:
            pass


class SegmentCache:
    def __init__(self, folder=None, memory_budget=None, disk_budget=DISK_BUDGET):
        self.memory_budget = memory_budget if memory_budget is not None else memory_budget_default()
        self.disk_budget = disk_budget
        if folder:
            self.folder = Path(folder)
        else:
            # exp.9: one folder for this app version; older versions' frames are removed
            base = default_folder()
            keep = _version_folder(_VERSION)
            remove_old_frames(base, keep)
            self.folder = base / keep
        self._memory = OrderedDict()          # exp.42: key -> packed frame (see pack)
        self._hot = OrderedDict()             # exp.42: key -> the last frames used, as pixels
        self._memory_bytes = 0                # both together
        self._packed_bytes = 0                # exp.42: the packed ones alone
        self._disk = None                     # name -> bytes, read lazily
        self._disk_bytes = 0

    # ---------------------------------------------------------------- keys
    @staticmethod
    def name(segment, index, width):
        # exp.150: the app version is part of the name: frames made by an older version
        # (an older way of drawing, e.g. the hand inside the picture) are never shown again.
        return f'{digest((_VERSION, segment))}-{int(width)}-{int(index):06d}'

    # -------------------------------------------------------------- memory
    def get(self, segment, index, width):
        key = self.name(segment, index, width)
        frame = self._hot.get(key)
        if frame is not None:
            self._hot.move_to_end(key)
            return frame
        packed = self._memory.get(key)
        if packed is not None:
            self._memory.move_to_end(key)
            frame = unpack(packed)
            if frame is not None:
                self._warm(key, frame)
                return frame
            self._forget(key)
        return self._from_disk(key)

    def has(self, segment, index, width):
        key = self.name(segment, index, width)
        return key in self._hot or key in self._memory or key in self._disk_index()

    def put(self, segment, index, width, frame, disk=False):
        key = self.name(segment, index, width)
        self.put_memory_only(key, frame)
        if disk:
            self._to_disk(key, frame)

    def _warm(self, key, frame):
        """exp.42: a frame used now, kept as pixels for a while (packed when it gets old)."""
        if key in self._hot:
            self._hot.move_to_end(key); return
        self._hot[key] = frame
        self._memory_bytes += frame.sizeInBytes()
        # at most HOT_FRAMES, and at most a quarter of the memory limit (the rest is packed)
        while len(self._hot) > HOT_FRAMES or (len(self._hot) > 2
                                              and self._memory_bytes - self._packed_bytes > self.memory_budget / 4):
            old_key, old = self._hot.popitem(last=False)
            self._memory_bytes -= old.sizeInBytes()
            if old_key not in self._memory:
                try:
                    packed = pack(old)
                except Exception:
                    packed = None
                if packed is not None:
                    self._memory[old_key] = packed
                    self._memory_bytes += _packed_size(packed); self._packed_bytes += _packed_size(packed)
        self._trim()

    def _trim(self):
        while self._memory and self._memory_bytes > self.memory_budget:
            old_key, packed = self._memory.popitem(last=False)
            self._memory_bytes -= _packed_size(packed); self._packed_bytes -= _packed_size(packed)
            frame = self._hot.pop(old_key, None)
            if frame is not None:
                self._memory_bytes -= frame.sizeInBytes()
        while self._hot and self._memory_bytes > self.memory_budget:   # a tiny budget
            _, frame = self._hot.popitem(last=False)
            self._memory_bytes -= frame.sizeInBytes()

    def _forget(self, key):
        packed = self._memory.pop(key, None)
        if packed is not None:
            self._memory_bytes -= _packed_size(packed); self._packed_bytes -= _packed_size(packed)
        frame = self._hot.pop(key, None)
        if frame is not None:
            self._memory_bytes -= frame.sizeInBytes()

    def memory_full(self, frame_bytes):
        """Would one more frame (frame_bytes as pixels) go over the memory limit? exp.42: it is
        kept packed, about as small as the packed frames so far."""
        if self._memory:
            packed = self._packed_bytes / len(self._memory)
        else:
            packed = frame_bytes / 8.
        return self._memory_bytes + min(frame_bytes, packed) > self.memory_budget

    def forget_memory(self):
        self._memory.clear()
        self._hot.clear()
        self._memory_bytes = 0
        self._packed_bytes = 0

    # ---------------------------------------------------------------- disk
    def _disk_index(self):
        if self._disk is None:
            self._disk = OrderedDict()
            self._disk_bytes = 0
            try:
                # Only ready frames: nothing else in the folder is ever counted or deleted.
                files = sorted((p for p in self.folder.glob('*.*') if p.suffix.lower() in FRAME_SUFFIXES),
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
        if path.suffix in ('.raw', '.zraw'):
            frame = _read_raw(path)
        elif path.suffix == '.jpg' and key not in self._memory:
            # exp.42: a JPEG frame is kept in memory as it is on disk (not packed again)
            from PySide6.QtGui import QImage as _Q
            try:
                data = path.read_bytes()
            except OSError:
                data = b''
            frame = QImage.fromData(data, 'JPG') if data else None
            if frame is not None and not frame.isNull():
                frame = frame.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                packed = ('jpg', data, frame.width(), frame.height(), 0,
                          int(_Q.Format.Format_ARGB32_Premultiplied.value))
                self._memory[key] = packed
                self._memory_bytes += _packed_size(packed); self._packed_bytes += _packed_size(packed)
                self._warm(key, frame)
                return frame
            self._drop(key)
            return None
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
        if key in self._memory or key in self._hot:
            return
        self._warm(key, frame)

    def _to_disk(self, key, frame):
        index = self._disk_index()
        if key in index:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = _write_frame(self.folder, key, frame)
            if path is None:
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


def _write_frame(folder, key, frame):
    """exp.9: an opaque frame as JPEG, one with transparency as zlib-packed pixels; the path
    written, or None."""
    from PySide6.QtGui import QImage
    if _opaque(frame):
        path = Path(folder) / (key + '.jpg')
        temp = path.with_name(path.name + '.part')
        try:
            if frame.save(str(temp), 'JPG', JPEG_QUALITY):
                os.replace(temp, path)
                return path
        except OSError:
            pass
        try:
            temp.unlink()
        except OSError:
            pass
    path = Path(folder) / (key + '.zraw')
    return path if _write_raw(path, frame, packed=True) else None


def _write_raw(path, frame, packed=False):
    """The frame's pixels as they are (ARGB32 premultiplied), with its size in front."""
    try:
        import struct
        from PySide6.QtGui import QImage
        image = frame if frame.format() == QImage.Format.Format_ARGB32_Premultiplied else \
            frame.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        w, h, line = image.width(), image.height(), image.bytesPerLine()
        temp = path.with_name(path.name + '.part')
        pixels = bytes(image.constBits())[:line * h]
        with open(temp, 'wb') as f:
            if packed:
                import zlib
                f.write(ZIP_MAGIC + struct.pack('<III', w, h, line))
                f.write(zlib.compress(pixels, 1))
            else:
                f.write(RAW_MAGIC + struct.pack('<III', w, h, line))
                f.write(pixels)
        os.replace(temp, path)
        return True
    except Exception:
        return False


def _read_raw(path):
    try:
        import struct
        from PySide6.QtGui import QImage
        data = Path(path).read_bytes()
        magic = data[:len(RAW_MAGIC)]
        if magic not in (RAW_MAGIC, ZIP_MAGIC):
            return None
        w, h, line = struct.unpack('<III', data[len(RAW_MAGIC):len(RAW_MAGIC) + 12])
        pixels = data[len(RAW_MAGIC) + 12:]
        if magic == ZIP_MAGIC:
            import zlib
            pixels = zlib.decompress(pixels)
        if len(pixels) < line * h:
            return None
        return QImage(pixels, w, h, line, QImage.Format.Format_ARGB32_Premultiplied).copy()
    except Exception:
        return None
