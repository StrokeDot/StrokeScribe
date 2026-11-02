"""High-quality placement of the original colored PNG on the output canvas.

QPainter's SmoothPixmapTransform is bilinear. When a large source PNG is shrunk
to fit a video frame (often to ~60% of its size) bilinear sampling skips source
pixels, which softens fine detail and leaves slightly jagged edges. Here the
PNG is resized once with Lanczos filtering on *premultiplied* color, so
transparent edges never pick up dark fringes, and drawn unscaled at a whole
pixel position. Every reveal mode and the settled final frame share this, so
painted pixels match the final frame exactly and nothing shifts at the end.
"""
from collections import OrderedDict

from PIL import Image
from PySide6.QtCore import QPoint

from adaptive_hand import pil_image, qimage

_SCALED_CACHE = OrderedDict()
_CACHE_LIMIT = 6


def pixel_rect(rect):
    """Integer x, y, width, height closest to a floating artwork rect."""
    x, y = round(rect.x()), round(rect.y())
    w = max(1, round(rect.x() + rect.width()) - x)
    h = max(1, round(rect.y() + rect.height()) - y)
    return x, y, w, h


def scaled_source(image, width, height):
    """The PNG resized to exactly width x height with Lanczos (cached)."""
    key = (image.cacheKey(), image.width(), image.height(), width, height)
    cached = _SCALED_CACHE.get(key)
    if cached is not None:
        _SCALED_CACHE.move_to_end(key)
        return cached
    source = pil_image(image)
    if source.size == (width, height):
        result = image
    else:
        # 'RGBa' is PIL's premultiplied mode: color is weighted by alpha while
        # filtering, avoiding dark or colored halos along transparent edges.
        resized = source.convert('RGBa').resize(
            (width, height), Image.Resampling.LANCZOS).convert('RGBA')
        result = qimage(resized)
    _SCALED_CACHE[key] = result
    if len(_SCALED_CACHE) > _CACHE_LIMIT:
        _SCALED_CACHE.popitem(last=False)
    return result


def draw_source(painter, rect, image):
    """Draw the colored PNG into rect at the highest available quality."""
    x, y, w, h = pixel_rect(rect)
    painter.drawImage(QPoint(x, y), scaled_source(image, w, h))
