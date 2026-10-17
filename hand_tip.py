"""Find the pen tip in a hand PNG automatically.

The pen tip is the sharpest point of the hand-with-pen silhouette that lies
farthest from where the arm enters the picture (the arm usually leaves the
image at an edge). Every outline point gets a "pointiness" score (how little
of a small circle around it is covered by the hand) and a distance from the
arm; the best pointy, far point is the tip. Manual X/Y adjustment remains
available for unusual hands.
"""
from __future__ import annotations

import cv2
import numpy as np


def _pil(image):
    from PIL import Image
    if not isinstance(image, Image.Image):
        from adaptive_hand import pil_image
        image = pil_image(image)
    return image.convert('RGBA')


def _mask(image):
    from PIL import Image
    rgba = _pil(image)
    w, h = rgba.size
    scale = min(1., 420 / max(w, h))
    small = rgba.resize((max(8, round(w * scale)), max(8, round(h * scale))), Image.BILINEAR)
    mask = (np.asarray(small.getchannel('A')) > 64).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = (labels == biggest).astype(np.uint8)
    return mask, (w, h)


def find_tip(image):
    """(x, y, confidence): pen tip as fractions of the hand image, or None."""
    mask, (w, h) = _mask(image)
    mh, mw = mask.shape
    if mask.sum() < 50:
        return None
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = max(contours, key=len).reshape(-1, 2).astype(np.float64)
    # Where the arm enters: hand pixels touching the image border.
    border = np.zeros_like(mask)
    border[0, :] = border[-1, :] = 1
    border[:, 0] = border[:, -1] = 1
    touching = np.argwhere(mask & border)
    if len(touching) >= 3:
        ay, ax = touching.mean(0)
    else:
        ay, ax = np.argwhere(mask).mean(0)
    # Pointiness: share of a small disk around the point covered by the hand.
    radius = max(3, int(max(mw, mh) * .03))
    disk = np.zeros((2 * radius + 1, 2 * radius + 1), np.float32)
    cv2.circle(disk, (radius, radius), radius, 1, -1)
    disk /= disk.sum()
    fill = cv2.filter2D(mask.astype(np.float32), -1, disk, borderType=cv2.BORDER_CONSTANT)
    xs = outline[:, 0].astype(int); ys = outline[:, 1].astype(int)
    on_edge = (xs <= 1) | (ys <= 1) | (xs >= mw - 2) | (ys >= mh - 2)
    cover = fill[ys, xs]
    distance = np.hypot(xs - ax, ys - ay) / max(mw, mh)
    score = distance * np.clip(.5 - cover, 0, None) ** .7
    score[on_edge] = 0                              # the cut-off arm is not a tip
    if score.max() <= 0:
        return None
    best = int(np.argmax(score))
    bx, by = xs[best], ys[best]
    # Refine: the hand pixel farthest from the arm near that point (the very tip).
    y0, y1 = max(0, by - radius), min(mh, by + radius + 1)
    x0, x1 = max(0, bx - radius), min(mw, bx + radius + 1)
    near = np.argwhere(mask[y0:y1, x0:x1])
    if len(near):
        ny = near[:, 0] + y0; nx = near[:, 1] + x0
        far = int(np.argmax(np.hypot(nx - ax, ny - ay)))
        bx, by = nx[far], ny[far]
    confidence = float(min(1., (.5 - cover[best]) * 2.5) * min(1., distance[best] * 2.5))
    tx, ty = (bx + .5) / mw, (by + .5) / mh
    # Full-resolution refinement: include the faint, anti-aliased graphite point.
    alpha = np.asarray(_pil(image).getchannel('A'))
    fx, fy, fr = tx * w, ty * h, max(4, radius * w / mw)
    x0, x1 = int(max(0, fx - fr)), int(min(w, fx + fr + 1))
    y0, y1 = int(max(0, fy - fr)), int(min(h, fy + fr + 1))
    near = np.argwhere(alpha[y0:y1, x0:x1] > 24)
    if len(near):
        ny = near[:, 0] + y0; nx = near[:, 1] + x0
        far = int(np.argmax(np.hypot(nx - ax * w / mw, ny - ay * h / mh)))
        tx, ty = (nx[far] + .5) / w, (ny[far] + .5) / h
    return float(tx), float(ty), confidence
