"""Use an AI-made line drawing as the guide for the pen strokes.

The AI redraws the image as clean black line art. That drawing is cleaner to
trace than the colour image (one smooth line per edge, no texture), but the
model may shift or scale it slightly, so before tracing we line it up with the
original (an affine alignment of the line art onto the original's edges) and
keep only lines over the artwork. The original image still supplies the
colours for painting.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def _ink(gray):
    """Dark-line strength 0..1 of a line drawing (lines dark on light)."""
    g = gray.astype(np.float32) / 255.
    return np.clip((.85 - g) / .6, 0, 1)


def _edges(rgba):
    rgb = np.asarray(rgba.convert('RGB'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 110).astype(np.float32) / 255.
    alpha = np.asarray(rgba.getchannel('A'))
    if alpha.min() < 250:                         # transparent artwork: its outline is an edge too
        edges = np.maximum(edges, cv2.Canny(alpha, 50, 150).astype(np.float32) / 255.)
    return edges


def _refine(edges, ink, start, start_scale, w, h, max_side):
    """Coarse-to-fine affine ECC from a starting warp; (warp at full size, score)."""
    warp = start.copy()
    previous = start_scale
    score = 0.
    for side in (128, 256, max_side):
        scale = min(1., side / max(w, h))
        size = (max(16, round(w * scale)), max(16, round(h * scale)))
        warp[:, 2] *= scale / previous
        previous = scale
        blur = max(1., side / 128.)
        target = cv2.GaussianBlur(cv2.resize(edges, size, interpolation=cv2.INTER_AREA), (0, 0), blur)
        moving = cv2.GaussianBlur(cv2.resize(ink, size, interpolation=cv2.INTER_AREA), (0, 0), blur)
        try:
            criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-6)
            score, warp = cv2.findTransformECC(target.astype(np.float32), moving.astype(np.float32),
                                               warp, cv2.MOTION_AFFINE, criteria, None, 5)
        except cv2.error:
            return None, 0.
    a, b, c, d = warp[0, 0], warp[0, 1], warp[1, 0], warp[1, 1]
    if not (.8 < a < 1.25 and .8 < d < 1.25 and abs(b) < .15 and abs(c) < .15
            and abs(warp[0, 2]) < size[0] * .2 and abs(warp[1, 2]) < size[1] * .2):
        return None, 0.
    full = warp.copy()
    full[:, 2] /= previous                         # translation back to full-size pixels
    return full, float(score)


def align(original, guide, max_side=512):
    """Affine matrix (2x3, guide -> original pixels) and a match score 0..1.

    Coarse to fine: small blurry versions find the rough shift, larger ones
    refine it. Starts from no shift and from the phase-correlation estimate
    (both directions) and keeps the best match, so offsets of several percent
    of the image are found. Wild results (a reshaped drawing) are rejected.
    """
    w, h = original.size
    edges = _edges(original)
    ink = _ink(np.asarray(guide.convert('L').resize((w, h), Image.LANCZOS)))
    scale0 = min(1., 128 / max(w, h))
    size0 = (max(16, round(w * scale0)), max(16, round(h * scale0)))
    t0 = cv2.GaussianBlur(cv2.resize(edges, size0, interpolation=cv2.INTER_AREA), (0, 0), 2.)
    m0 = cv2.GaussianBlur(cv2.resize(ink, size0, interpolation=cv2.INTER_AREA), (0, 0), 2.)
    (sx, sy), _ = cv2.phaseCorrelate(t0.astype(np.float64), m0.astype(np.float64))
    best = (np.eye(2, 3, dtype=np.float32), 0.)
    for tx, ty in ((0., 0.), (sx, sy), (-sx, -sy)):
        start = np.eye(2, 3, dtype=np.float32)
        start[:, 2] = (tx, ty)
        warp, score = _refine(edges, ink, start, scale0, w, h, max_side)
        if warp is not None and score > best[1]:
            best = (warp, score)
    return best


def guide_image(original, guide):
    """The AI line drawing, aligned to `original` and limited to the artwork.

    Returns (RGBA image the same size as `original`, alignment score). The
    alpha of the result is the original's, so lines the AI drew outside the
    artwork disappear and the outer outline still comes from the artwork.
    """
    w, h = original.size
    if guide.mode in ('RGBA', 'LA', 'P'):
        guide = guide.convert('RGBA')
        flat = Image.new('RGB', guide.size, 'white')
        flat.paste(guide, mask=guide.getchannel('A'))      # transparent paper is white
        guide = flat
    guide = guide.convert('RGB').resize((w, h), Image.LANCZOS)
    warp, score = align(original, guide)
    rgb = cv2.warpAffine(np.asarray(guide), warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    alpha = np.asarray(original.getchannel('A'))
    out = Image.fromarray(rgb).convert('RGBA')
    out.putalpha(Image.fromarray(alpha))
    return out, score
