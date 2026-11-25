"""exp.68 (the user: a resting hand, the left hand of a right-handed artist: on top of the page,
or holding the book from below; the writing hand is always on top of everything).

A resting hand is a clip on the timeline, like a picture on top (kind 'rest_hand'): your own
photo of the hand, its white background taken out, mirrored by default (photos of a right hand
become the left hand). Its layer:
  'under' - under every element and sticker (over the background);
  'over'  - over every element and sticker, still under the writing hand.
The photo is kept inside the project (nothing is added to the program).
"""
from __future__ import annotations

import base64
import uuid

KIND = 'rest_hand'
LAYERS = (('Under the pictures', 'under'), ('Over the pictures (under the writing hand)', 'over'))
POSES = ('On top of the page', 'Holding from below')


def is_rest_hand(item):
    return bool(item) and item.get('kind') == KIND


def cut_out(image):
    """The photo with its white background taken out (the white that touches the photo's
    edges; whites inside the hand stay), the edge softened, trimmed to the hand. QImage in,
    QImage (ARGB32) out."""
    import cv2
    import numpy as np
    from PySide6.QtGui import QImage
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w].copy()
    rgb = a[..., :3].astype(np.int16)
    lo, hi = rgb.min(axis=2), rgb.max(axis=2)
    whiteish = ((lo > 222) & (hi - lo < 28)).astype(np.uint8)
    count, labels = cv2.connectedComponents(whiteish, connectivity=4)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    edge.discard(0)
    background = np.isin(labels, list(edge)) if edge else np.zeros((h, w), bool)
    alpha = np.where(background, 0, a[..., 3]).astype(np.float32)
    # a soft edge: the pixels next to the background fade by how white they are
    keep = (~background).astype(np.uint8)
    dist = cv2.distanceTransform(keep, cv2.DIST_L2, 3)
    near = (dist > 0) & (dist < 2.5)
    soft = np.clip((250. - lo.astype(np.float32)) / 45., 0., 1.)
    alpha[near] = alpha[near] * soft[near]
    # take the white out of the soft edge (no light halo on a dark background)
    k = np.clip(alpha / 255., 1e-3, 1.)[..., None]
    col = a[..., :3].astype(np.float32)
    fixed = np.clip((col - (1 - k) * 255.) / k, 0, 255)
    col = np.where(near[..., None], fixed, col)
    out = np.dstack([col, alpha]).astype(np.uint8)
    ys, xs = np.nonzero(alpha > 8)
    if len(xs):
        pad = 2
        out = out[max(0, ys.min() - pad):ys.max() + pad + 1, max(0, xs.min() - pad):xs.max() + pad + 1]
    out = np.ascontiguousarray(out)
    result = QImage(out.data, out.shape[1], out.shape[0], out.shape[1] * 4, QImage.Format.Format_RGBA8888).copy()
    return result.convertToFormat(QImage.Format.Format_ARGB32)


def png_data(image):
    """QImage → base64 PNG text (how pictures on top keep their image in the project)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    raw = QByteArray(); buf = QBuffer(raw); buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, 'PNG'); buf.close()
    return base64.b64encode(bytes(raw)).decode('ascii')


def load_photo(path):
    """(base64 PNG, name) of a hand photo, cut out; raises ValueError when it cannot be read."""
    from pathlib import Path
    from PySide6.QtGui import QImage
    image = QImage(str(path))
    if image.isNull():
        raise ValueError('That file is not a picture StrokeScribe can read.')
    longest = max(image.width(), image.height())
    if longest > 1600:                                  # plenty for a hand; keeps the project small
        from PySide6.QtCore import Qt
        image = image.scaled(int(image.width() * 1600 / longest), int(image.height() * 1600 / longest),
                             Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return png_data(cut_out(image)), Path(path).stem


def new(data, name, start=0., duration=4., pose=POSES[0], layer='under'):
    """A resting hand clip. On top of the page: the back of the hand from the lower left;
    holding from below: the palm, lower down. Mirrored (flip) by default."""
    below = pose == POSES[1]
    return dict(id=uuid.uuid4().hex[:10], kind=KIND, name='Resting hand', photo_name=name, data=data,
                format='png', pose=pose, layer=layer, flip=True,
                x=.2 if not below else .22, y=.78 if not below else .9, size=.34 if not below else .3,
                start=float(start), duration=float(duration),
                effect_in='Slide from bottom', in_seconds=.6, effect_out='Slide from bottom', out_seconds=.6,
                track=0)


def layer_key(item):
    """Where a picture on top goes among the elements (exp.68): a resting hand under every
    element, or over every element (still under the writing hand); others by their track."""
    if is_rest_hand(item):
        return -10 ** 6 if item.get('layer', 'under') == 'under' else 10 ** 6
    return int(item.get('track', 0) or 0)
