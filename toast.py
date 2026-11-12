"""Small notices that fade (exp.239).

The user asked for small notices instead of windows that must be clicked away
(UI clean-up step 3). A notice slides in at the bottom right of the window, stacks
above older ones, stays while the mouse is over it, closes on click and fades out
on its own after a few seconds. Use it for "wait" and "do this first" messages and
finished jobs; questions and real errors stay in dialogs.
"""
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel

MARGIN = 20
GAP = 8
WIDTH = 340
MAX_SHOWN = 3


class _Mover(QObject):
    """Keeps the notices in the corner when the window is resized."""

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            _place(obj)
        return False


def _place(window):
    shown = [t for t in getattr(window, '_toasts', []) if t.isVisible()]
    y = window.height() - MARGIN
    for toast in reversed(shown):          # the newest is at the bottom
        toast.adjustSize()
        y -= toast.height()
        toast.move(window.width() - WIDTH - MARGIN, y)
        toast.raise_()
        y -= GAP


class Toast(QFrame):
    def __init__(self, window, text, kind='info', seconds=4.):
        super().__init__(window)
        self.setObjectName('toast')
        self.setProperty('kind', kind)
        self.setFixedWidth(WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to close')
        line = QHBoxLayout(self)
        line.setContentsMargins(14, 10, 14, 10)
        label = QLabel(str(text))
        label.setObjectName('toastText')
        label.setWordWrap(True)
        line.addWidget(label)
        self.text = str(text)
        self._window = window
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b'opacity', self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(max(1., float(seconds)) * 1000))
        self._timer.timeout.connect(self.close_soft)
        self._closing = False

    def appear(self):
        self.show()
        _place(self._window)
        self._fade.stop()
        self._fade.setDuration(160)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.)
        self._fade.start()
        self._timer.start()

    def close_soft(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._fade.stop()
        self._fade.setDuration(220)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.)
        self._fade.finished.connect(self._gone)
        self._fade.start()

    def _gone(self):
        toasts = getattr(self._window, '_toasts', [])
        if self in toasts:
            toasts.remove(self)
        self.hide()
        self.deleteLater()
        _place(self._window)

    def enterEvent(self, event):           # reading it: it waits
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._closing:
            self._timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.close_soft()


def notify(parent, text, kind='info', seconds=4.):
    """Show a small fading notice in the window of `parent`. Returns the notice."""
    window = parent.window() if parent is not None else None
    if window is None:
        return None
    if not hasattr(window, '_toasts'):
        window._toasts = []
        window._toast_mover = _Mover(window)
        window.installEventFilter(window._toast_mover)
    for old in list(window._toasts):       # the same notice again: show it once
        if old.text == str(text) and not old._closing:
            old._timer.start()
            return old
    toast = Toast(window, text, kind, seconds)
    window._toasts.append(toast)
    live = [t for t in window._toasts if not t._closing]
    for old in live[:-MAX_SHOWN]:
        old.close_soft()
    toast.appear()
    return toast
