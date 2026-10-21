"""Optional, non-destructive paper removal for artwork colour images.

This is NOT a blend mode. It only changes the QImage render copy: the original
PNG in .strokescribe remains untouched. The model is intentionally conservative:
only bright neutral paper connected to a canvas edge qualifies. Genuine white
regions fully enclosed by line art cannot be reached from the edge.
"""
from __future__ import annotations

from collections import OrderedDict
import numpy as np
from PySide6.QtGui import QImage

_CACHE = OrderedDict()
_CACHE_SIZE = 6


def clean_paper(image, tolerance=24, softness=12):
    """Return RGBA8888 QImage with edge-connected near-white paper transparent.

    tolerance 0..80 controls how far the image's background can vary from its
    sampled bright edge colour. softness 0..40 fades neighbouring antialiased
    pixels. Both preserve the original QImage and its source alpha.
    """
    if image is None or image.isNull():
        return image
    import cv2
    tolerance = max(0, min(80, int(tolerance)))
    softness = max(0, min(40, int(softness)))
    key = (image.cacheKey(), tolerance, softness)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    h, w = source.height(), source.width()
    pixels = np.frombuffer(source.constBits(), np.uint8).reshape(h, source.bytesPerLine())[:, :4*w].reshape(h,w,4).copy()
    rgb = pixels[:,:,:3].astype(np.int16)
    alpha = pixels[:,:,3]
    border = np.zeros((h,w), dtype=bool)
    ring = min(3, max(1, min(h,w)//8))
    border[:ring,:] = True; border[-ring:,:] = True
    border[:,:ring] = True; border[:,-ring:] = True
    edge = rgb[border & (alpha>=245)]
    # Photos, coloured artwork or already transparent boundaries are not paper.
    eligible = (edge.min(axis=1)>=205) & (np.ptp(edge,axis=1)<=18) if len(edge) else []
    output = image
    if len(edge)>0 and np.count_nonzero(eligible)>=0.75*border.sum():
        paper = np.median(edge[eligible], axis=0)
        # Limit the candidate itself to bright neutral pixels, even with high
        # tolerance: black strokes, shadows, saturated colours are never paper.
        delta = np.max(np.abs(rgb-paper),axis=2)
        neutral = (rgb.min(axis=2)>=190) & (np.ptp(rgb,axis=2)<=30)
        candidate = (delta<=tolerance) & neutral & (alpha>0)
        n, labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=4)
        touches = np.unique(labels[border]); touches = touches[touches!=0]
        connected = np.isin(labels,touches)
        if connected.any():
            out = pixels.copy()
            out[:,:,3][connected] = 0
            if softness:
                # Only soften the immediate neighbour of removed paper; never
                # blur lines or enclosed white areas across a dark outline.
                neighbour = cv2.dilate(connected.astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
                neighbour &= ~connected & neutral
                if neighbour.any():
                    factor = np.clip((delta-tolerance)/max(1,softness),0,1)
                    out[:,:,3][neighbour] = (alpha[neighbour]*factor[neighbour]).astype(np.uint8)
            # Fail safe for blank white pages or overwhelmingly washed-out input.
            if np.count_nonzero(out[:,:,3]) >= max(4, int(.015*w*h)):
                out[out[:,:,3]==0,:3] = 0
                output = QImage(out.tobytes(), w, h, 4*w, QImage.Format.Format_RGBA8888).copy()
    _CACHE[key] = output
    while len(_CACHE)>_CACHE_SIZE:
        _CACHE.popitem(last=False)
    return output


def prepare_image(image, enabled=False, tolerance=24, softness=12):
    return clean_paper(image, tolerance, softness) if enabled else image
