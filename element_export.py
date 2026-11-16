"""Export one element's finished picture, with no animation (exp.21).

The user lays the parts of a video out in Filmora and wants to move them on their own there, so
an element can be saved as a still:

- PNG: the finished element on a transparent background at the export resolution. By default it
  keeps its place in the video frame (it lines up with the video when stacked in Filmora); it can
  also be cropped to the picture.
- SVG: shapes that can be made any size without losing sharpness. A text is saved as its letter
  outlines, filled with its ink colour (traced from the very sharp ink the app draws); a line
  drawing as its lines. A painted picture's colours are not shapes, so they come as a PNG next to
  the SVG of its lines.
"""
from __future__ import annotations

from pathlib import Path

PNG, SVG = 'PNG (transparent background)', 'SVG (sharp at any size)'


def finished_frame(window, keep_place=True):
    """The element being edited, finished, on a transparent background (QImage) at the export
    size; cropped to the picture when keep_place is False. None when there is nothing."""
    from frame_render import compose_frame
    from PySide6.QtGui import QImage
    import numpy as np
    w = window
    if not w.drawing:
        return None
    opts = w.options()
    for key in ('erase', 'overlays', 'audio', 'fps', 'workers'):
        opts.pop(key, None)
    opts.update(layers='art', ghost=0, background=False, pause=0., entrance='draw', loop=None)
    opts.pop('hand_travel', None)
    image = compose_frame(w.drawing, 1., opts, None)
    if image is None or image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    if keep_place:
        return image
    a = np.frombuffer(bytes(image.constBits())[:image.sizeInBytes()], np.uint8).reshape(
        image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), 3]
    ys, xs = np.nonzero(a > 2)
    if not len(xs):
        return image
    pad = 4
    x0, y0 = max(0, xs.min() - pad), max(0, ys.min() - pad)
    x1, y1 = min(image.width(), xs.max() + 1 + pad), min(image.height(), ys.max() + 1 + pad)
    return image.copy(int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def save_png(window, path, keep_place=True):
    image = finished_frame(window, keep_place)
    if image is None:
        raise ValueError('There is no picture to save.')
    path = Path(path).with_suffix('.png')
    if not image.save(str(path), 'PNG'):
        raise ValueError(f'Could not write {path.name}.')
    return [path]


def _text_svg(drawing, title):
    """A text's letters as filled outlines (traced from the sharp ink, holes kept)."""
    import cv2
    import numpy as np
    from xml.sax.saxutils import quoteattr
    from svg_export import _num
    alpha = np.asarray(drawing.font_ink.convert('RGBA'))[..., 3]
    ys, xs = np.nonzero(alpha > 110)
    if not len(xs):
        raise ValueError('The text has no ink to save.')
    pad = 2
    x0, y0 = max(0, xs.min() - pad), max(0, ys.min() - pad)
    x1, y1 = min(alpha.shape[1], xs.max() + 1 + pad), min(alpha.shape[0], ys.max() + 1 + pad)
    crop = alpha[y0:y1, x0:x1]
    # The ink's soft edges say where the letter edge lies between pixels: enlarge them smoothly
    # before tracing, so the outline is a smooth curve rather than a pixel staircase.
    f = max(1, min(8, int((40_000_000 / max(1, crop.size)) ** .5)))
    big = cv2.resize(crop, (crop.shape[1] * f, crop.shape[0] * f), interpolation=cv2.INTER_CUBIC)
    big = cv2.GaussianBlur(big, (0, 0), f * .35)
    mask = (big > 127).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    parts = []
    for c in contours:
        c = cv2.approxPolyDP(c, f * .18, True).reshape(-1, 2)
        if len(c) < 3:
            continue
        parts.append('M' + ' L'.join(f'{_num((x + .5) / f - .5)} {_num((y + .5) / f - .5)}' for x, y in c) + ' Z')
    colour = getattr(drawing, 'font_color', '#25364a') or '#25364a'
    width, height = x1 - x0, y1 - y0
    return '\n'.join([
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_num(width)}" height="{_num(height)}" viewBox="0 0 {_num(width)} {_num(height)}">',
        f' <title>{title}</title>',
        ' <desc>Exported by StrokeScribe: the letters as shapes (any size stays sharp).</desc>',
        f' <path fill={quoteattr(colour)} fill-rule="evenodd" d={quoteattr(" ".join(parts))}/>',
        '</svg>', ''])


def save_svg(window, path):
    """The element as SVG; returns the files written (a painted picture adds its colour PNG)."""
    from svg_export import svg_document
    w = window
    d = w.drawing
    if not d:
        raise ValueError('There is no picture to save.')
    path = Path(path).with_suffix('.svg')
    title = f'{path.stem} — StrokeScribe'
    kind = getattr(d, 'source_kind', None)
    if kind == 'font' and getattr(d, 'font_ink', None) is not None:
        path.write_text(_text_svg(d, title), encoding='utf-8')
        return [path]
    if kind == 'image' and getattr(w, 'image_result', None) is not None:
        from svg_export import export_drawing
        from adaptive_hand import pil_image
        svg, png = export_drawing([(s.name, s.points, s.color, s.width) for s in d.strokes],
                                  pil_image(w.image_result.image), path.parent, path.stem)
        return [svg, png]
    left, top, right, bottom = d.bounds
    strokes = [(s.name, [(x - left, y - top) for x, y in s.points], s.color, s.width) for s in d.strokes]
    colour = (d.strokes[0].color if d.strokes else '#303946') or '#303946'
    path.write_text(svg_document(strokes, right - left, bottom - top, color=colour, title=title),
                    encoding='utf-8')
    return [path]


def export_dialog(window):
    """Ask PNG / SVG (and for PNG: keep its place or crop), then where; save. Files or None."""
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                                   QFormLayout, QLabel, QMessageBox)
    w = window
    if not w.drawing:
        from toast import notify
        notify(w, 'Choose an element first.', 'warning'); return None
    dialog = QDialog(w); dialog.setWindowTitle('Export picture')
    form = QFormLayout(dialog)
    k = w.scene_index
    form.addRow(QLabel(f'Element {k + 1}: {w.scene_label(k)} — finished, with no animation.'))
    fmt = QComboBox(); fmt.addItems([PNG, SVG])
    form.addRow('Format', fmt)
    keep = QCheckBox('Keep its place in the video frame')
    keep.setChecked(True)
    keep.setToolTip('The PNG is the size of the video with the picture where it is in the video, so it '
                    'lines up when stacked in Filmora. Off: cropped to the picture.')
    form.addRow('', keep)
    note = QLabel(); note.setWordWrap(True); note.setObjectName('caption')
    form.addRow(note)

    def changed(*_):
        png = fmt.currentText() == PNG
        keep.setVisible(png)
        image = getattr(w.drawing, 'source_kind', None) == 'image'
        note.setText(f'PNG at {w.res.currentText()} with a transparent background.' if png else
                     ('Its lines as shapes; the painted colours are not shapes, so they are saved as a '
                      'PNG next to it.' if image else 'Shapes: any size stays sharp. Effects such as '
                      'shadows are not part of the SVG.'))
    fmt.currentIndexChanged.connect(changed); changed()
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    png = fmt.currentText() == PNG
    stem = ''.join(ch if ch.isalnum() or ch in ' -_' else '_' for ch in w.scene_label(k)).strip() or 'element'
    start = str(Path(getattr(w, 'last_export_folder', None) or Path.home()) / (stem + ('.png' if png else '.svg')))
    name, _ = QFileDialog.getSaveFileName(w, 'Save picture', start,
                                          'PNG picture (*.png)' if png else 'SVG picture (*.svg)')
    if not name:
        return None
    try:
        files = save_png(w, name, keep.isChecked()) if png else save_svg(w, name)
    except Exception as exc:
        QMessageBox.warning(w, 'Export picture', str(exc)); return None
    from toast import notify
    notify(w, 'Saved ' + ', '.join(p.name for p in files), 'done', 4)
    return files
