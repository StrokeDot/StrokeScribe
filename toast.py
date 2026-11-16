"""Small notices that fade (exp.239).

The user asked for small notices instead of windows that must be clicked away
(UI clean-up step 3). A notice slides in at the bottom right of the window, stacks
above older ones, stays while the mouse is over it, closes on click and fades out
on its own after a few seconds. Use it for "wait" and "do this first" messages and
finished jobs; questions and real errors stay in dialogs.

exp.15 (the user: the green "Saved" notice was too wide, wanted something more refined): a
notice is as wide as its words (up to WIDTH), has a small round mark (a check when something
is done, "!" for a warning) instead of a coloured outline, and glides up as it fades in,
then sinks a little as it fades out.
"""
from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint,
                            QPropertyAnimation, QRectF, Qt, QTimer)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

MARGIN = 20
GAP = 8
WIDTH = 340            # the widest a notice gets
MIN_WIDTH = 160
RISE = 14              # how far a notice glides in
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
        target = QPoint(window.width() - toast.width() - MARGIN, y)
        toast.home = target
        if toast.gliding() and toast is shown[-1] and not toast._closing:
            toast._glide.setEndValue(target)          # the newest keeps gliding to its place
        else:
            if toast.gliding() and not toast._closing:
                toast._motion.stop(); toast._effect.setOpacity(1.)   # an older one makes room
            toast.move(target)
        toast.raise_()
        y -= GAP


class _Mark(QWidget):
    """The small round sign at the start of a notice."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(18, 18)

    def paintEvent(self, event):
        import theme
        c = theme.colors()
        colour = QColor(c['good'] if self.kind == 'done' else c['hold'] if self.kind == 'warning'
                        else c['accent'])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawEllipse(QRectF(1, 1, 16, 16))
        pen = QPen(QColor('#FFFFFF'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if self.kind == 'done':
            path = QPainterPath(); path.moveTo(5.4, 9.3); path.lineTo(8., 11.8); path.lineTo(12.6, 6.6)
            p.drawPath(path)
        elif self.kind == 'warning':
            p.drawLine(9, 5, 9, 10); p.drawPoint(9, 13)
        else:
            p.drawLine(9, 8, 9, 13); p.drawPoint(9, 5)
        p.end()


class Toast(QFrame):
    def __init__(self, window, text, kind='info', seconds=4.):
        super().__init__(window)
        self.setObjectName('toast')
        self.setProperty('kind', kind)
        self.setMinimumWidth(MIN_WIDTH)
        self.setMaximumWidth(WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to close')
        line = QHBoxLayout(self)
        line.setContentsMargins(12, 9, 16, 9)
        line.setSpacing(10)
        line.addWidget(_Mark(kind, self), 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel(str(text))
        label.setObjectName('toastText')
        # one line while it fits; long messages wrap within WIDTH
        label.setWordWrap(label.fontMetrics().horizontalAdvance(str(text)) > WIDTH - 60)
        line.addWidget(label, 1)
        self.home = None
        self.text = str(text)
        self._window = window
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b'opacity', self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide = QPropertyAnimation(self, b'pos', self)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion = QParallelAnimationGroup(self)
        self._motion.addAnimation(self._fade)
        self._motion.addAnimation(self._glide)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(max(1., float(seconds)) * 1000))
        self._timer.timeout.connect(self.close_soft)
        self._closing = False

    def gliding(self):
        return self._glide.state() == QPropertyAnimation.State.Running

    def appear(self):
        self.show()
        _place(self._window)
        self._motion.stop()
        home = self.home or self.pos()
        self._fade.setDuration(240)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.)
        self._glide.setDuration(240)
        self._glide.setStartValue(home + QPoint(0, RISE))
        self._glide.setEndValue(home)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion.start()
        self._timer.start()

    def close_soft(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._motion.stop()
        self._fade.setDuration(180)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.)
        self._glide.setDuration(180)
        self._glide.setStartValue(self.pos())
        self._glide.setEndValue(self.pos() + QPoint(0, RISE // 2))
        self._fade.setEasingCurve(QEasingCurve.Type.InCubic)
        self._glide.setEasingCurve(QEasingCurve.Type.InCubic)
        self._motion.finished.connect(self._gone)
        self._motion.start()

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
