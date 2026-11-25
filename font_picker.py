"""The font list, Filmora-style (exp.15).

The user: in Filmora every font in the list is shown in its own style while scrolling, and
the list keeps Recent and Favorites at the top. Here:

- every row shows the font's name written in that font. Google fonts come with a small picture
  (assets/font_previews, made by tools/make_font_previews.py), so nothing has to be downloaded
  to see them; Windows fonts (Ink Free) and imported fonts are drawn from their own file;
- Recent (the last fonts used to write) and Favorites (the star next to the list) sit at the top;
- group names (Handwriting, Western, ...) are small headings instead of plain lines.
"""
from pathlib import Path

from PySide6.QtCore import QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

ROLE = Qt.ItemDataRole.UserRole + 41          # 'head' (a heading) or 'quick' (Recent / Favorites)
RECENT_KEY = 'fonts/recent'
FAVOURITES_KEY = 'fonts/favorites'
MAX_RECENT = 5
BUILT_IN = 'Built-in single-line pen'
PREVIEWS = Path(__file__).resolve().parent / 'assets' / 'font_previews'
ROW = 34
HEAD = 26


def _settings():
    return QSettings('StrokeScribe', 'Studio')


def _list(key):
    value = _settings().value(key, [])
    if isinstance(value, str):
        value = [value] if value else []
    return [str(v) for v in (value or []) if str(v).strip()]


def recent():
    return _list(RECENT_KEY)


def favourites():
    return _list(FAVOURITES_KEY)


def note_recent(family):
    family = str(family or '').strip()
    if not family or family == BUILT_IN:
        return
    names = [family] + [f for f in recent() if f != family]
    _settings().setValue(RECENT_KEY, names[:MAX_RECENT])


def toggle_favourite(family):
    """Adds or removes a favourite; returns True when it is now a favourite."""
    family = str(family or '').strip()
    if not family or family == BUILT_IN:
        return False
    names = favourites()
    if family in names:
        names.remove(family); on = False
    else:
        names.append(family); on = True
    _settings().setValue(FAVOURITES_KEY, names)
    return on


# -------------------------------------------------------------- previews

_pictures = {}
_families = {}


def _family_of(path):
    """Qt's family name of a font file (loaded once)."""
    key = str(path)
    if key not in _families:
        ident = QFontDatabase.addApplicationFont(key)
        names = QFontDatabase.applicationFontFamilies(ident) if ident >= 0 else []
        _families[key] = names[0] if names else None
    return _families[key]


def _font_file(family, data=None):
    if data and Path(str(data)).is_file():
        return Path(str(data))
    try:
        from font_library import installed_font
        return installed_font(family)
    except Exception:
        return None


def picture(family, colour, height, data=None, ratio=2.):
    """The font's name written in the font (a QPixmap), or None (then plain text is shown)."""
    key = (family, QColor(colour).name(), height, str(data or ''))
    if key in _pictures:
        return _pictures[key]
    pix = None
    label = family[7:] if family.startswith('Local: ') else family
    try:
        from font_library import font_slug
        bundled = PREVIEWS / f'{font_slug(label)}.png'
    except Exception:
        bundled = None
    if bundled is not None and bundled.is_file():
        shape = QImage(str(bundled))
        if not shape.isNull():
            tinted = QImage(shape.size(), QImage.Format.Format_ARGB32_Premultiplied)
            tinted.fill(QColor(colour))
            p = QPainter(tinted)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            p.drawImage(0, 0, shape)
            p.end()
            pix = QPixmap.fromImage(tinted)
            pix.setDevicePixelRatio(shape.height() / float(height))
    if pix is None:
        path = _font_file(label, data)
        name = _family_of(path) if path is not None else None
        if name:
            font = QFont(name)
            font.setPixelSize(int(height * ratio * .62))
            from PySide6.QtGui import QFontMetrics
            width = min(int(520 * ratio / 2), QFontMetrics(font).horizontalAdvance(label) + 8)
            image = QImage(max(1, width), int(height * ratio), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            p = QPainter(image)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.setFont(font); p.setPen(QColor(colour))
            p.drawText(QRectF(4, 0, width - 4, image.height()),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
            p.end()
            pix = QPixmap.fromImage(image)
            pix.setDevicePixelRatio(ratio)
    _pictures[key] = pix
    return pix


# -------------------------------------------------------------- the list

class PreviewDelegate(QStyledItemDelegate):
    """Draws headings, and every font in its own style with a star for favourites."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), HEAD if index.data(ROLE) in ('head', 'quickhead') else ROW)

    def paint(self, painter, option, index):
        import theme
        c = theme.colors()
        kind = index.data(ROLE)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind in ('head', 'quickhead'):
            f = QFont(option.font); f.setBold(True); f.setPointSizeF(max(7., f.pointSizeF() * .9))
            painter.setFont(f); painter.setPen(QColor(c['muted']))
            painter.drawText(r.adjusted(10, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter), text)
            painter.restore()
            return
        if option.state & QStyle.StateFlag.State_Selected or option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c['selection']))
            painter.drawRoundedRect(QRectF(r).adjusted(3, 1, -3, -1), 6, 6)
        colour = c['text']
        pix = None if text == BUILT_IN else picture(text, colour, 22, index.data(Qt.ItemDataRole.UserRole))
        left = r.left() + 14
        if pix is not None:
            w = pix.width() / pix.devicePixelRatio(); h = pix.height() / pix.devicePixelRatio()
            room = r.width() - 44
            if w > room:                                   # a long name: keep it inside the row
                pix = pix.scaledToWidth(int(room * pix.devicePixelRatio()), Qt.TransformationMode.SmoothTransformation)
                w = pix.width() / pix.devicePixelRatio(); h = pix.height() / pix.devicePixelRatio()
            painter.drawPixmap(int(left), int(r.center().y() - h / 2 + 1), pix)
        else:
            painter.setPen(QColor(colour)); painter.setFont(option.font)
            painter.drawText(r.adjusted(14, 0, -36, 0), int(Qt.AlignmentFlag.AlignVCenter), text)
        if text in favourites():
            painter.setPen(QColor(c['accent_hover'])); painter.setFont(option.font)
            painter.drawText(r.adjusted(0, 0, -12, 0),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), '★')
        painter.restore()


def add_heading(combo, text, kind='head', at=None):
    at = combo.count() if at is None else at
    combo.insertItem(at, text)
    combo.setItemData(at, kind, ROLE)
    item = combo.model().item(at)
    if item is not None:
        item.setFlags(Qt.ItemFlag.NoItemFlags)             # a heading can't be chosen
    return at


def refresh_quick(combo):
    """Recent and Favorites at the top of the list (after the built-in pen)."""
    current = combo.currentText()
    combo.blockSignals(True)
    try:
        for i in range(combo.count() - 1, -1, -1):
            if combo.itemData(i, ROLE) in ('quick', 'quickhead'):
                combo.removeItem(i)
        at = 1 if combo.count() and combo.itemText(0) == BUILT_IN else 0
        known = {combo.itemText(i): combo.itemData(i) for i in range(combo.count())}
        for title, names in (('RECENT', recent()), ('FAVORITES', favourites())):
            names = [n for n in names if n in known]
            if not names:
                continue
            add_heading(combo, title, 'quickhead', at); at += 1
            for name in names:
                combo.insertItem(at, name, known[name])
                combo.setItemData(at, 'quick', ROLE)
                at += 1
        i = combo.findText(current)
        if i >= 0:
            combo.setCurrentIndex(i)
        elif current:
            combo.setEditText(current)
    finally:
        combo.blockSignals(False)


def font_rows(combo):
    """The list's rows that are fonts (no headings, no Recent / Favorites copies)."""
    return [i for i in range(combo.count()) if combo.itemData(i, ROLE) not in ('head', 'quick', 'quickhead')]
