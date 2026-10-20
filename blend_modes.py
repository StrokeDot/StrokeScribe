"""Non-destructive per-element compositing modes (normal is the default).

Blend modes combine the image with an existing destination. On fully
transparent output they cannot magically produce a transparent white sheet:
use source background cleanup when real alpha is required.
"""
MODES = ('Normal', 'Multiply', 'Darken', 'Color Burn',
         'Screen', 'Lighten', 'Color Dodge', 'Overlay')
_ENUM = {
    'Normal': 'CompositionMode_SourceOver',
    'Multiply': 'CompositionMode_Multiply',
    'Darken': 'CompositionMode_Darken',
    'Color Burn': 'CompositionMode_ColorBurn',
    'Screen': 'CompositionMode_Screen',
    'Lighten': 'CompositionMode_Lighten',
    'Color Dodge': 'CompositionMode_ColorDodge',
    'Overlay': 'CompositionMode_Overlay',
}


def composition_mode(name):
    from PySide6.QtGui import QPainter
    return getattr(QPainter.CompositionMode, _ENUM.get(name, _ENUM['Normal']))
