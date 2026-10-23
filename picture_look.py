"""How the element's picture looks: Colour and Light adjustments (like Filmora's
Color / Light panels) and "Ink on the page".

Ink on the page turns the picture into ink with transparency: the picture's own
paper tone becomes see-through, its lines become ink. On any page (in StrokeScribe
or later in Filmora with the normal blend mode) it then looks printed on that page,
with the page's grain showing through, and no square around it. Its edges can fade
softly (a soft rectangle) or in an oval around the middle.

Order: Colour -> Light -> Ink on the page. Applied to the colour picture that is
painted (the PNG of an image element, the matching colours of an SVG), in the
preview, the pre-render and the export alike (export_job.options_from_settings).
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np

COLOUR = (('look_temperature', 'Temperature'), ('look_tint', 'Tint'), ('look_saturation', 'Saturation'))
LIGHT = (('look_exposure', 'Exposure'), ('look_brightness', 'Brightness'), ('look_contrast', 'Contrast'),
         ('look_highlights', 'Highlight'), ('look_shadows', 'Shadow'), ('look_whites', 'White'),
         ('look_blacks', 'Black'))
EDGES = {'Soft edges': 'soft', 'Oval fade': 'oval', 'No fading': 'none'}
INK_COLOURS = {'Dark grey (like printed text)': (41, 41, 44), 'Black': (12, 12, 12),
               'Sepia': (74, 52, 34), "The picture's own colours": None}

DEFAULTS = dict(look_colour_on=False, look_light_on=False, ink_on=False,
                look_temperature=0., look_tint=0., look_saturation=0.,
                look_exposure=0., look_brightness=0., look_contrast=0., look_highlights=0.,
                look_shadows=0., look_whites=0., look_blacks=0.,
                ink_edges='Soft edges', ink_removal=50., ink_strength=100., ink_colour='Dark grey (like printed text)',
                ink_edge_size=15.)


def _smooth(a, b, x):
    t = np.clip((x - a) / max(1e-6, b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _lum(rgb):
    return rgb[..., 0] * .299 + rgb[..., 1] * .587 + rgb[..., 2] * .114


def colour(rgb, temperature=0., tint=0., saturation=0.):
    """rgb: float 0..1. Values -100..100, 0 = unchanged."""
    out = rgb.copy()
    t, g = temperature / 100., tint / 100.
    out[..., 0] += .15 * t + .075 * g
    out[..., 2] += -.15 * t + .075 * g
    out[..., 1] += -.15 * g
    lum = _lum(out)[..., None]
    out = lum + (out - lum) * (1 + saturation / 100.)
    return np.clip(out, 0, 1)


def light(rgb, exposure=0., brightness=0., contrast=0., highlights=0., shadows=0., whites=0., blacks=0.):
    """rgb: float 0..1. Values -100..100, 0 = unchanged."""
    out = rgb * (2. ** (exposure / 50.))                          # up to ±2 stops
    out = out + brightness / 100. * .35 * (1 - np.abs(2 * np.clip(out, 0, 1) - 1))
    out = (out - .5) * (1 + contrast / 100.) + .5
    lum = _lum(np.clip(out, 0, 1))[..., None]
    out = out + highlights / 100. * .5 * _smooth(.45, 1., lum)
    out = out + shadows / 100. * .5 * (1 - _smooth(0., .55, lum))
    white = 1 - whites / 100. * .45                               # White +: the bright end reaches white sooner
    black = -blacks / 100. * .35                                  # Black -: the dark end reaches black sooner
    out = (out - black) / max(1e-3, white - black)
    return np.clip(out, 0, 1)


def ink(rgba, removal=50., strength=100., colour_rgb=(41, 41, 44), edges='soft', edge_size=15.):
    """Ink with transparency: paper tone -> see-through, lines -> ink. rgba: float 0..1."""
    rgb, alpha = rgba[..., :3], rgba[..., 3]
    lum = _lum(rgb)
    seen = alpha > .25
    values = lum[seen] if seen.any() else lum.ravel()
    # The picture's own paper: the bright end of its tones. More removal = a darker tone counts as paper.
    white = np.percentile(values, 99. - .6 * float(removal))
    black = np.percentile(values, 1.)
    t = np.clip((lum - black) / max(1e-3, white - black), 0, 1)
    amount = (1 - t) * (float(strength) / 100.)
    h, w = lum.shape
    if edges in ('soft', 'oval') and edge_size > 0:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        if edges == 'soft':
            d = np.minimum.reduce([xx, w - 1 - xx, yy, h - 1 - yy])
            f = np.clip(d / max(1., edge_size / 100. * min(w, h)), 0, 1)
        else:
            r = np.sqrt(((xx - (w - 1) / 2) / (w / 2)) ** 2 + ((yy - (h - 1) / 2) / (h / 2)) ** 2)
            f = np.clip((1 - r) / max(.02, edge_size / 100. * 3), 0, 1)
        amount = amount * (f * f * (3 - 2 * f))
    out = np.empty_like(rgba)
    if colour_rgb is None:
        out[..., :3] = rgb                                        # the picture's own colours, as ink
    else:
        out[..., :3] = np.asarray(colour_rgb, np.float32) / 255.
    out[..., 3] = np.clip(amount, 0, 1) * alpha
    return out


def active(s):
    return bool(s.get('look_colour_on') or s.get('look_light_on') or s.get('ink_on'))


def _params(s):
    get = lambda k: s.get(k, DEFAULTS[k])
    return tuple((k, get(k)) for k in sorted(DEFAULTS))


def adjust_array(rgba, s):
    """The look applied to a float RGBA array (0..1) with settings dict `s`."""
    get = lambda k: s.get(k, DEFAULTS[k])
    out = rgba.copy()
    if get('look_colour_on'):
        out[..., :3] = colour(out[..., :3], *(float(get(k)) for k, _ in COLOUR))
    if get('look_light_on'):
        out[..., :3] = light(out[..., :3], *(float(get(k)) for k, _ in LIGHT))
    if get('ink_on'):
        out = ink(out, float(get('ink_removal')), float(get('ink_strength')),
                  INK_COLOURS.get(get('ink_colour'), INK_COLOURS['Dark grey (like printed text)']),
                  EDGES.get(get('ink_edges'), 'soft'), float(get('ink_edge_size')))
    return out


_CACHE = OrderedDict()


def adjusted(image, s):
    """The element's colour picture (QImage) with its look; the same object for the same input
    (frame caches compare pictures), or `image` itself when no look is on."""
    if image is None or image.isNull() or not active(s):
        return image
    key = (image.cacheKey(), _params(s))
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    from PySide6.QtGui import QImage
    q = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = q.width(), q.height()
    a = np.frombuffer(q.constBits(), np.uint8, q.bytesPerLine() * h).reshape(h, q.bytesPerLine())
    a = a[:, :w * 4].reshape(h, w, 4).astype(np.float32) / 255.
    out = adjust_array(a, s)
    data = np.ascontiguousarray((np.clip(out, 0, 1) * 255 + .5).astype(np.uint8))
    result = QImage(data.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
    while len(_CACHE) >= 12:
        _CACHE.popitem(last=False)
    _CACHE[key] = result
    return result
