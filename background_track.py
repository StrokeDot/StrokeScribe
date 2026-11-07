"""exp.207 (the user, like Filmora): the Background row of the timeline.

The video's background can change along the video. The Background row is cut into pieces
(Split here), and each piece has its own background, or none at all (Hide: transparent).
A piece that was never changed follows the video's Background (the menu over the preview).

    pieces = [{'start': seconds, 'choice': None | 'Paper' | 'Custom colour…' | ...,
               'colour': '#rrggbb' | None, 'hidden': bool}, ...]

The first piece starts at 0; each piece lasts until the next one starts (the last one until
the end of the video). No pieces (the default): the whole video has the video's Background.

Plain Python except bake() (PIL), so it can be tested without a window.
"""
from __future__ import annotations

import copy

from backgrounds import BACKGROUND_ITEMS

CHOICES = tuple(c for c in BACKGROUND_ITEMS if c != 'Transparent')
MIN_PIECE = .1          # seconds: no piece shorter than this


def normalise(pieces):
    """Sorted, first one at 0, none shorter than MIN_PIECE (a clean copy)."""
    out = []
    for piece in sorted((dict(p) for p in pieces or ()), key=lambda p: float(p.get('start', 0) or 0)):
        piece['start'] = round(max(0., float(piece.get('start', 0) or 0)), 3)
        piece.setdefault('choice', None)
        piece.setdefault('colour', None)
        piece['hidden'] = bool(piece.get('hidden'))
        if out and piece['start'] - out[-1]['start'] < MIN_PIECE:
            continue
        out.append(piece)
    if out:
        out[0]['start'] = 0.
    return out


def index_at(pieces, seconds):
    """The piece shown at `seconds` (its index), or None when there are no pieces."""
    found = None
    for i, piece in enumerate(pieces or ()):
        if float(piece['start']) <= float(seconds) + 1e-9:
            found = i
    return found if found is not None or not pieces else 0


def ranges(pieces, total):
    """[(index, start, end)] of the pieces in a video of `total` seconds."""
    out = []
    for i, piece in enumerate(pieces or ()):
        end = float(pieces[i + 1]['start']) if i + 1 < len(pieces) else max(float(total), float(piece['start']))
        out.append((i, float(piece['start']), end))
    return out


def plain(piece):
    """A piece with nothing of its own (it follows the video's Background)."""
    return not piece.get('hidden') and piece.get('choice') is None


def split(pieces, seconds):
    """Cut the piece under `seconds` in two there (both keep its background)."""
    pieces = normalise(pieces) or [dict(start=0., choice=None, colour=None, hidden=False)]
    i = index_at(pieces, seconds)
    piece = pieces[i]
    end = float(pieces[i + 1]['start']) if i + 1 < len(pieces) else None
    if seconds - float(piece['start']) < MIN_PIECE or (end is not None and end - seconds < MIN_PIECE):
        return pieces
    pieces.insert(i + 1, dict(copy.deepcopy(piece), start=round(float(seconds), 3)))
    return tidy(pieces)


def set_choice(pieces, i, choice, colour=None):
    """Piece i gets this background (None: the video's Background) and is shown again."""
    pieces = normalise(pieces) or [dict(start=0., choice=None, colour=None, hidden=False)]
    if 0 <= i < len(pieces):
        pieces[i].update(choice=choice, colour=colour if choice == 'Custom colour…' else None, hidden=False)
    return tidy(pieces)


def set_hidden(pieces, i, hidden=True):
    """Piece i shows no background at all (transparent), or its background again."""
    pieces = normalise(pieces) or [dict(start=0., choice=None, colour=None, hidden=False)]
    if 0 <= i < len(pieces):
        pieces[i]['hidden'] = bool(hidden)
    return tidy(pieces)


def remove_cut(pieces, i):
    """Piece i joins the piece before it (the cut at its start goes; it takes that look)."""
    pieces = normalise(pieces)
    if 0 < i < len(pieces):
        del pieces[i]
    return tidy(pieces)


def move_cut(pieces, i, seconds):
    """The cut at the start of piece i moves to `seconds` (between its neighbours)."""
    pieces = normalise(pieces)
    if 0 < i < len(pieces):
        low = float(pieces[i - 1]['start']) + MIN_PIECE
        high = float(pieces[i + 1]['start']) - MIN_PIECE if i + 1 < len(pieces) else float('inf')
        pieces[i]['start'] = round(min(high, max(low, float(seconds))), 3)
    return pieces


def tidy(pieces):
    """Clean pieces; a single piece with nothing of its own: no pieces at all. Cuts stay
    (like Filmora) even when the pieces on both sides look the same, until joined."""
    out = normalise(pieces)
    if len(out) == 1 and plain(out[0]):
        return []
    return out


def _same(a, b):
    return (bool(a.get('hidden')) == bool(b.get('hidden')) and a.get('choice') == b.get('choice')
            and (a.get('colour') if a.get('choice') == 'Custom colour…' else None)
            == (b.get('colour') if b.get('choice') == 'Custom colour…' else None))


def spec_of(piece, main):
    """backgrounds.spec of a piece; `main`: the video's Background spec."""
    from backgrounds import spec
    if piece is None:
        return main
    if piece.get('hidden'):
        return 'transparent'
    if piece.get('choice') is None:
        return main
    return spec(piece['choice'], piece.get('colour'))


def spec_at(pieces, seconds, main):
    i = index_at(pieces, seconds)
    return spec_of(pieces[i] if i is not None else None, main)


def label(piece, main_label):
    if piece.get('hidden'):
        return 'Hidden (transparent)'
    if piece.get('choice') is None:
        return f'Video background ({main_label})'
    if piece['choice'] == 'Custom colour…':
        return f'Colour {piece.get("colour") or ""}'.strip()
    return piece['choice']


# Swatches for the timeline (close to what each background looks like).
SWATCH = {'white': '#ffffff', 'dark': '#242d3b', 'black': '#000000', 'whiteboard': '#eef0f3',
          'paper': '#efe6d0', 'chalkboard': '#2f3d34', 'cork': '#b98c5c'}


def swatch(spec_value):
    """A colour for a background spec on the timeline (None: transparent)."""
    if spec_value == 'transparent':
        return None
    return SWATCH.get(spec_value, spec_value if str(spec_value).startswith('#') else '#cccccc')


def used(pieces):
    return bool(pieces)


# ------------------------------------------------------------ export

def bake(folder, fps, pieces, main, frames=None):
    """exp.207: the frames of `folder` put on the background of their moment (the hidden
    pieces stay transparent), in a new folder next to them, ready to be encoded without a
    single background. Returns that folder."""
    import json
    import shutil
    from pathlib import Path

    from PIL import Image

    from backgrounds import picture_png
    folder = Path(folder)
    out = folder / '_with_background'
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    info = json.loads((folder / 'sequence.json').read_text())
    (out / 'sequence.json').write_text(json.dumps(info))
    width, height = int(info['width']), int(info['height'])
    cache = {}

    def under(spec_value):
        if spec_value not in cache:
            path = out / f'_bg_{len(cache)}.png'
            picture_png(spec_value, width, height, path)
            cache[spec_value] = Image.open(path).convert('RGBA')
            path.unlink(missing_ok=True)
        return cache[spec_value]

    for i, frame in enumerate(sorted(frames or folder.glob('frame_*.png'))):
        target = out / frame.name
        spec_value = spec_at(pieces, i / float(fps), main)
        if spec_value == 'transparent':
            shutil.copyfile(frame, target)
            continue
        image = Image.open(frame).convert('RGBA')
        base = under(spec_value)
        if base.size != image.size:
            base = base.resize(image.size)
        Image.alpha_composite(base, image).save(target, compress_level=1)
    return out
