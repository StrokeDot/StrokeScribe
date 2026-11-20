"""Make a picture's transparency complete.

Many PNGs, especially AI-made ones, are not really transparent:
  * fake transparency: the grey-and-white checkerboard was painted INTO the
    picture, so it is solid;
  * a solid sheet behind the artwork (white, or any plain colour);
  * faint leftovers of background removal (pixels under ~25 % visible).

clean_background() finds the background from the picture's edges and removes
only what is connected to the edges, so white or grey parts INSIDE the artwork
(eyes, highlights, a white shirt surrounded by an outline) are kept.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

FAINT_ALPHA = 64          # under ~25 % visible: background-removal leftovers
TOLERANCE = 22            # colour distance that still counts as background


def _edge_pixels(rgb, alpha, ring=3):
    h, w = alpha.shape
    mask = np.zeros((h, w), bool)
    mask[:ring, :] = mask[-ring:, :] = True
    mask[:, :ring] = mask[:, -ring:] = True
    return rgb[mask], alpha[mask]


def background_colours(rgb, alpha):
    """The 1-3 colours of a solid or checkerboard background, or [] when the edges
    are already transparent or too varied to be a background."""
    colours, edge_alpha = _edge_pixels(rgb, alpha)
    opaque = edge_alpha > 250
    if opaque.mean() < .9:
        return []                                   # really transparent already
    colours = colours[opaque].astype(np.int32)
    keys = (colours // 8).astype(np.int32)
    flat = keys[:, 0] * 1024 + keys[:, 1] * 32 + keys[:, 2]
    values, counts = np.unique(flat, return_counts=True)
    order = np.argsort(counts)[::-1]
    chosen, covered = [], 0
    for index in order[:6]:
        members = colours[flat == values[index]]
        centre = members.mean(0)
        if any(np.abs(centre - c).max() < TOLERANCE for c in chosen):
            covered += counts[index]; continue
        chosen.append(centre)
        covered += counts[index]
        if covered >= .9 * len(flat) or len(chosen) == 3:
            break
    if covered < .85 * len(flat):
        return []                                   # busy edges: a photo, not a background
    # Backgrounds are white, grey or black (a sheet or a checkerboard); a coloured
    # edge belongs to the artwork.
    if any(np.ptp(c) > 24 for c in chosen):
        return []
    return [np.array(c) for c in chosen]


def clean_background(image, faint=True, fake=True):
    """RGBA copy with fake/solid backgrounds and faint leftovers made transparent."""
    import cv2
    image = image.convert('RGBA')
    data = np.asarray(image).copy()
    rgb, alpha = data[..., :3].astype(np.int32), data[..., 3]
    if fake:
        colours = background_colours(rgb, alpha)
        if colours:
            close = np.zeros(alpha.shape, bool)
            for c in colours:
                close |= np.abs(rgb - c).max(-1) <= TOLERANCE
            close &= alpha > 0
            count, labels = cv2.connectedComponents(close.astype(np.uint8), connectivity=4)
            edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
            edge = edge[edge > 0]
            background = np.isin(labels, edge)
            # Soft edge: antialiased pixels next to the removed background that are
            # still close to it become partly transparent instead of a light halo.
            near = cv2.dilate(background.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~background
            if near.any():
                distance = np.min([np.abs(rgb - c).max(-1) for c in colours], axis=0)
                fade = np.clip((distance - TOLERANCE) / (3 * TOLERANCE), 0, 1)
                data[..., 3] = np.where(near, (alpha * fade).astype(np.uint8), data[..., 3])
            data[..., 3][background] = 0
            if (data[..., 3] > 0).sum() < .03 * max(1, (alpha > 0).sum()):
                data = np.asarray(image).copy()    # nothing would be left: it is not a background
    if faint:
        data[..., 3][data[..., 3] < FAINT_ALPHA] = 0
    data[..., :3][data[..., 3] == 0] = 0           # no hidden colour in transparent pixels
    return Image.fromarray(data, 'RGBA')


def report(before, after):
    """Plain-language summary of what was cleaned (for the status line)."""
    a = np.asarray(before.convert('RGBA'))[..., 3] > 0
    b = np.asarray(after.convert('RGBA'))[..., 3] > 0
    removed = int((a & ~b).sum())
    if not removed:
        return 'nothing to clean'
    return f'cleaned the background ({100 * removed / max(1, a.size):.0f}% of the picture made transparent)'
