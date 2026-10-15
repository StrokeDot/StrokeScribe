"""The drawing/painting hand as its own layer, on top of the scaled artwork.

Artwork Size scales the finished frame after it is rendered. If the hand were
painted into that frame first, any part of the hand reaching past the frame
edge would be cut off there, and at sizes below 100% that edge sits inside
the video, so the hand looked sliced by an invisible box. While a capture is
active, renderers hand their hand placement to this module instead of
painting it; the caller draws it after scaling, at the matching position and
size, so it is only ever clipped by the real video frame.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

_state = threading.local()


@contextmanager
def capture():
    """Collect hand placements drawn during the block (per thread)."""
    previous = getattr(_state, 'hands', None)
    hands = []
    _state.hands = hands
    try:
        yield hands
    finally:
        _state.hands = previous


def paint(painter, rect, hand):
    """Draw the hand now, or record it while a capture is active."""
    hands = getattr(_state, 'hands', None)
    if hands is None:
        painter.drawImage(rect, hand)
    else:
        hands.append((QRectF(rect), hand))


def draw_captured(frame, hands, factor=1.0):
    """Paint the last captured hand onto `frame`, mapped through the artwork scale.

    Only one hand is ever visible; the last placement recorded for the frame
    is the one the renderer showed on top.
    """
    if not hands:
        return frame
    rect, hand = hands[-1]
    w, h = frame.width(), frame.height()
    cx, cy = w / 2, h / 2
    mapped = QRectF(cx + (rect.x() - cx) * factor, cy + (rect.y() - cy) * factor,
                    rect.width() * factor, rect.height() * factor)
    painter = QPainter(frame)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(mapped, hand)
    painter.end()
    return frame
