"""Built-in drawing/painting tools and the separate painting hand.

Built-in tools (original artwork, assets/default_*.png, made by
tools/make_tool_assets.py) are plain hand images with a known tip, so they work
everywhere a hand works.

The painting hand can differ from the drawing hand. Renderers place every hand
with the drawing hand's pen tip (anchor) and size (hand_scale); a PaintingTool
carries its own tip and size, and hand_layer.paint re-places it so its brush
tip lands exactly where the pen tip would be. Nothing else needs to know.
"""
from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent / 'assets'

# name: (file, tip (x, y) as fractions of the image, suggested width as a share of the video width)
BUILTIN = {
    'hand': ('default_hand.png', (.08, .13), .75),
    'pencil': ('default_pencil.png', (.054, .077), .3),
    'marker': ('default_marker.png', (.068, .088), .26),
    'brush': ('default_brush.png', (.054, .081), .3),
}
LABELS = {'hand': 'StrokeScribe built-in hand', 'pencil': 'built-in pencil', 'marker': 'built-in marker',
          'brush': 'built-in paint brush'}

# Painting hand menu (Hand tab).
PAINT_SAME, PAINT_BRUSH, PAINT_LIBRARY = 'Same as drawing hand', 'Built-in paint brush', 'From Hands library'
PAINT_CHOICES = (PAINT_SAME, PAINT_BRUSH, PAINT_LIBRARY)


def builtin_path(name):
    return ASSETS / BUILTIN[name][0]


def builtin_image(name):
    from PySide6.QtGui import QImage
    path = builtin_path(name)
    return QImage(str(path)) if path.is_file() else QImage()


def _tool_class():
    from PySide6.QtGui import QImage

    class PaintingTool(QImage):
        """A hand/tool image that brings its own tip and size (see hand_layer.paint)."""
        own_tip = (.1, .1)          # tip in this image, fractions
        base_anchor = (.1, .1)      # anchor the renderers use (drawing hand's pen tip)
        relative = 1.               # width relative to the drawing hand's width

    return PaintingTool


_PaintingTool = None


def painting_tool(image, tip, width_share, hand_scale, base_anchor):
    """Wrap `image` so it is drawn `width_share` x video width wide with its tip at the pen tip."""
    global _PaintingTool
    if image is None or image.isNull():
        return None
    if _PaintingTool is None:
        _PaintingTool = _tool_class()
    tool = _PaintingTool(image)
    tool.own_tip = (float(tip[0]), float(tip[1]))
    tool.base_anchor = (float(base_anchor[0]), float(base_anchor[1]))
    tool.relative = float(width_share) / max(1e-6, float(hand_scale))
    return tool


def place(rect, hand):
    """Where a PaintingTool really goes, given the rect computed for the drawing hand."""
    own = getattr(hand, 'own_tip', None)
    if own is None:
        return rect
    from PySide6.QtCore import QRectF
    ax, ay = hand.base_anchor
    tip_x = rect.x() + ax * rect.width()
    tip_y = rect.y() + ay * rect.height()
    w = rect.width() * hand.relative
    h = w * hand.height() / max(1, hand.width())
    return QRectF(tip_x - own[0] * w, tip_y - own[1] * h, w, h)


_CACHE = {}


_MIRRORED = {}


def mirrored(image):
    """The picture flipped left ↔ right (left-handed), cached (same result object every time)."""
    if image is None or image.isNull():
        return image
    key = image.cacheKey()
    out = _MIRRORED.get(key)
    if out is None:
        from PySide6.QtCore import Qt
        try:
            out = image.flipped(Qt.Orientation.Horizontal)
        except (AttributeError, TypeError):
            out = image.mirrored(True, False)
        if len(_MIRRORED) > 24:
            _MIRRORED.clear()
        _MIRRORED[key] = out
    return out


def painting_hand(settings, hand):
    """The painting hand chosen in the Hand tab (None: hidden while painting).

    Results are cached, so the same settings give the very same image object
    (frame caches compare images by cacheKey)."""
    s = settings
    if not s.get('show_paint_hand', True):
        return None
    choice = str(s.get('paint_hand') or PAINT_SAME)
    if choice == PAINT_SAME:
        return hand
    hand_scale = float(s.get('handsize', .75))
    anchor = (float(s.get('ax', .08)), float(s.get('ay', .13)))
    share = float(s.get('paint_hand_size', 30)) / 100.
    if choice == PAINT_LIBRARY:
        path = str(s.get('paint_hand_path') or '')
        known = s.get('paint_hand_tip')
    else:
        path, known = str(builtin_path('brush')), BUILTIN['brush'][1]
    try:
        stamp = Path(path).stat().st_mtime if path else None
    except OSError:
        stamp = None
    if stamp is None:
        return hand                                  # file gone: fall back to the drawing hand
    left = bool(s.get('left_handed'))
    key = (path, stamp, tuple(known) if known else None, share, hand_scale, anchor, left)
    tool = _CACHE.get(key)
    if tool is None:
        from PySide6.QtGui import QImage
        image = QImage(path)
        if image.isNull():
            return hand
        if left:                                     # the brush in the left hand
            image = mirrored(image)
            known = (1 - float(known[0]), float(known[1])) if known else None
        tool = painting_tool(image, tip_for_image(image, known), share, hand_scale, anchor)
        if len(_CACHE) > 16:
            _CACHE.clear()
        _CACHE[key] = tool
    return tool


def tip_for_image(image, known=None):
    """A saved tip, or one found automatically, or the image's upper-left area."""
    if known:
        return tuple(known)
    try:
        from hand_tip import find_tip
        found = find_tip(image)
        if found:
            return found[:2]
    except Exception:
        pass
    return (.1, .1)


# ------------------------------------------------------------- projects

def hand_to_project(hand_builtin, hand):
    """'builtin', 'builtin:pencil' … or the hand PNG as base64."""
    from projects import qimage_to_b64
    if hand_builtin is True or hand_builtin == 'hand':
        return 'builtin'
    if isinstance(hand_builtin, str) and hand_builtin in BUILTIN:
        return 'builtin:' + hand_builtin
    return qimage_to_b64(hand)


def hand_from_project(value):
    """(image or None, built-in name or None) from a project's 'hand' value."""
    if not value:
        return None, None
    if value == 'builtin' or (isinstance(value, str) and value.startswith('builtin:')):
        name = value.split(':', 1)[1] if ':' in value else 'hand'
        if name not in BUILTIN:
            name = 'hand'
        image = builtin_image(name)
        return (None if image.isNull() else image), name
    from projects import qimage_from_b64
    return qimage_from_b64(value), None


def restore_paint_hand(path, png_b64):
    """The project's painting hand file; re-created in the Hands library if it was moved."""
    if path and Path(path).is_file():
        return path
    if not png_b64:
        return None
    import base64
    import tempfile
    try:
        import library
        name = Path(path).name if path else 'painting hand.png'
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp) / name
            temp.write_bytes(base64.b64decode(png_b64))
            return str(library.Library().add('hands', temp).path)
    except Exception:
        return None
