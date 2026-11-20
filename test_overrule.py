"""exp.47 (the user: I cannot move the sticker's hand): a sticker's bar on the Hand row can be
dragged (exp.46's take-over of a way back was removed in exp.48: see test_motion_over_way_back)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class Overrule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg'))
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(40): APP.processEvents()
        w.hand_rest.setChecked(True)
        w.preview_scope.setCurrentIndex(1)
        for _ in range(40): APP.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def tearDown(self):
        w = self.w
        w.cameras[:] = [c for c in w.cameras if c.get('kind') != 'Hand motion']
        w.overlays[:] = [o for o in w.overlays if o.get('kind') != 'sticker']
        w.refresh(); APP.processEvents()

    def test_c_the_sticker_bar_on_the_hand_row_can_be_dragged(self):
        # exp.47 (the user: I cannot move the sticker's hand): dragging its bar moves the sticker
        import stickers
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        w = self.w
        end = max(b for a, b in w.hand_busy_spans())
        w.add_sticker('Circle'); st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        st.update(drawing='Hand: outline', start=round(end + 3., 2))
        w.refresh(); APP.processEvents()
        tl = w.stage_timeline
        tl.resize(1400, tl.height()); w.refresh(); APP.processEvents()
        mark = next(m for m in tl.sticker_hand_marks if m[4] == st['id'])
        hand_y = next(y for y in range(0, tl.height(), 2) if tl._sticker_hand_at(QPointF(tl._x(mark[0] + .1), y)))
        x = tl._x(mark[0] + .1)

        def ev(kind, px, buttons):
            p = QPointF(px, hand_y)
            return QMouseEvent(kind, p, p, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
        before = st['start']
        tl.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, x, Qt.MouseButton.LeftButton))
        target = x - (tl._x(1.) - tl._x(0.))                                        # one second left
        tl.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, target, Qt.MouseButton.LeftButton))
        tl.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton))
        APP.processEvents()
        self.assertAlmostEqual(st['start'], before - 1., delta=.15)


if __name__ == '__main__':
    unittest.main()
