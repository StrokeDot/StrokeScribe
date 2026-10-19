"""StrokeScribe project files (.strokescribe).

One self-contained JSON file: the drawing (every stroke in its current order),
the colour image, the hand and every setting. Images are embedded (PNG,
base64), so a project still opens after the original files are moved or
deleted, and can be copied to another computer.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

FORMAT = 'strokescribe-project'
VERSION = 1
SUFFIX = '.strokescribe'
SKIP_ATTRIBUTES = {'strokes', 'bounds', 'warnings', 'image_regions', 'artwork_assets'}


# ---------------------------------------------------------------- values

def _encode(value):
    from PIL import Image
    if isinstance(value, Image.Image):
        import io
        buffer = io.BytesIO()
        value.save(buffer, 'PNG')
        return {'__pil_png__': base64.b64encode(buffer.getvalue()).decode('ascii')}
    if isinstance(value, tuple):
        items = [_encode(v) for v in value]
        return _SKIP if any(i is _SKIP for i in items) else {'__tuple__': items}
    if isinstance(value, list):
        items = [_encode(v) for v in value]
        return _SKIP if any(i is _SKIP for i in items) else items
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                return _SKIP
            e = _encode(v)
            if e is _SKIP:
                return _SKIP
            out[k] = e
        return out
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return _SKIP


class _Skip:
    pass


_SKIP = _Skip()


def _decode(value):
    if isinstance(value, dict):
        if '__pil_png__' in value:
            import io
            from PIL import Image
            image = Image.open(io.BytesIO(base64.b64decode(value['__pil_png__'])))
            image.load()
            return image
        if '__tuple__' in value:
            return tuple(_decode(v) for v in value['__tuple__'])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def qimage_to_b64(image):
    if image is None or image.isNull():
        return None
    from PySide6.QtCore import QBuffer, QIODevice
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return base64.b64encode(bytes(buffer.data())).decode('ascii')


def qimage_from_b64(text):
    if not text:
        return None
    from PySide6.QtGui import QImage
    image = QImage()
    image.loadFromData(base64.b64decode(text), 'PNG')
    return None if image.isNull() else image


# ---------------------------------------------------------------- drawings

def drawing_to_dict(drawing):
    attributes = {}
    for name, value in vars(drawing).items():
        if name in SKIP_ATTRIBUTES or name.endswith('_cache') or name.startswith('_'):
            continue
        encoded = _encode(value)
        if encoded is not _SKIP:
            attributes[name] = encoded
    return {
        'strokes': [{'name': s.name, 'points': [[round(x, 3), round(y, 3)] for x, y in s.points],
                     'color': s.color, 'width': s.width, 'pace': getattr(s, 'pace', 1.),
                     'pause': getattr(s, 'pause', 0.), 'reversed': bool(getattr(s, 'reversed', False))}
                    for s in drawing.strokes],
        'bounds': list(drawing.bounds),
        'warnings': list(drawing.warnings),
        'attributes': attributes,
    }


def drawing_from_dict(data):
    from engine import Drawing, Stroke
    strokes = [Stroke(s['name'], [tuple(p) for p in s['points']], s.get('color', '#153c54'),
                      s.get('width', 3), s.get('pace', 1.)) for s in data['strokes']]
    for stroke, s in zip(strokes, data['strokes']):
        stroke.pause = float(s.get('pause', 0.) or 0.)
        stroke.reversed = bool(s.get('reversed', False))
    drawing = Drawing(strokes, tuple(data['bounds']), list(data.get('warnings', [])))
    for name, value in data.get('attributes', {}).items():
        setattr(drawing, name, _decode(value))
    return drawing


# ---------------------------------------------------------------- files

def save(path, project):
    """Write a project dict (see Window.project_state) atomically."""
    path = Path(path)
    if path.suffix.lower() != SUFFIX:
        path = path.with_suffix(SUFFIX)
    data = dict(project, format=FORMAT, version=VERSION)
    temp = path.with_name(path.name + '.saving')
    temp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    temp.replace(path)
    return path


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('This file could not be read as a StrokeScribe project.') from exc
    if data.get('format') != FORMAT:
        raise ValueError('This is not a StrokeScribe project file.')
    if int(data.get('version', 0)) > VERSION:
        raise ValueError('This project was saved by a newer StrokeScribe. Update the app to open it.')
    from artwork_assets import validate_assets
    records=[data]+[s.get('state') for s in data.get('scenes',[]) if isinstance(s,dict) and s.get('state')]
    for record in records:
        if record.get('artwork') is not None:
            record['artwork']=validate_assets(record['artwork'])
    return data


# ---------------------------------------------------------------- settings

def widget_value(widget):
    from PySide6.QtWidgets import QAbstractSpinBox, QCheckBox, QComboBox
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, QAbstractSpinBox):
        return widget.value()
    return None


def set_widget_value(widget, value):
    from PySide6.QtWidgets import QAbstractSpinBox, QCheckBox, QComboBox
    if value is None:
        return
    if isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QComboBox):
        index = widget.findText(str(value))
        if index >= 0:
            widget.setCurrentIndex(index)
    elif isinstance(widget, QAbstractSpinBox):
        widget.setValue(value)
