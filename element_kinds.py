"""What kind of element is being edited: native lettering or imported artwork.

The kind is UI and project state only. Rendering keeps reading the drawing
exactly as before; nothing here changes how a frame is drawn.

- ``lettering``: text written with the built-in pen or a font (Animate lettering).
- ``svg``: an imported SVG drawing (optionally with a matching colored PNG).
- ``image``: an imported PNG/JPG reconstructed into line art.

Older projects have no ``element_kind``; it is derived from the drawing's
``source_kind`` (saved with every drawing) or, failing that, from the scene's
``source`` field. Note that ``source`` alone cannot tell lettering from SVG:
lettering scenes were always saved with ``source: 'svg'``.
"""
from __future__ import annotations

LETTERING, SVG, IMAGE = 'lettering', 'svg', 'image'
KINDS = (LETTERING, SVG, IMAGE)
IMPORTED = (SVG, IMAGE)

_FROM_SOURCE_KIND = {'font': LETTERING, 'lettering': LETTERING, 'svg': SVG, 'image': IMAGE}


def kind_of_source(source_kind, default=SVG):
    """Map a drawing's ``source_kind`` attribute to an element kind."""
    return _FROM_SOURCE_KIND.get(source_kind, default)


def kind_of_drawing(drawing):
    """Kind of a live drawing; the bundled sample (no source_kind) is an SVG."""
    if drawing is None:
        return SVG
    return kind_of_source(getattr(drawing, 'source_kind', None))


def kind_of_state(state):
    """Kind of a saved scene state, for new and old project files alike."""
    if not isinstance(state, dict):
        return SVG
    stored = state.get('element_kind')
    if stored in KINDS:
        return stored
    attributes = ((state.get('drawing') or {}).get('attributes') or {})
    source_kind = attributes.get('source_kind')
    if isinstance(source_kind, str) and source_kind in _FROM_SOURCE_KIND:
        return _FROM_SOURCE_KIND[source_kind]
    if state.get('source') == 'image' or state.get('image'):
        return IMAGE
    return SVG


def is_imported(kind):
    return kind in IMPORTED


def lettering_title(text, limit=16):
    """'Lettering — <first words>': the only name a lettering element gets."""
    words = ' '.join(str(text or '').split())
    if len(words) > limit:
        words = words[:limit].rstrip() + '…'
    return 'Lettering — ' + (words or 'empty text')


def source_card(kind, title='', filename='', text=''):
    """(heading, detail) for the Source panel's element card.

    Lettering never shows a file name: its letters are drawn by StrokeScribe,
    not imported, so naming an .svg or image file for it would be invented.
    """
    if kind == LETTERING:
        return ('Handwriting element', lettering_title(text) +
                '. Edit its text and style in the Handwriting panel.')
    name = str(filename or '').strip()
    label = 'SVG drawing' if kind == SVG else 'Image'
    return (label, name or (str(title or '').strip() or 'Imported ' + label.lower()))
