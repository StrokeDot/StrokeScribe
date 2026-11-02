"""exp.186: Eraser clips on the timeline."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class EraserClipTests(unittest.TestCase):
    def test_progress_and_target(self):
        import eraser_clips, overlays
        item = overlays.new_eraser('u2', 1, 'Erase 2', start=10., duration=2.)
        elements = [dict(uid='u1'), dict(uid='u2')]
        self.assertEqual(eraser_clips.target_of(item, elements), 1)
        self.assertEqual(eraser_clips.at([item], elements, 9.), {})
        self.assertAlmostEqual(eraser_clips.at([item], elements, 11.)[1][0], .5)
        self.assertEqual(eraser_clips.at([item], elements, 20.)[1][0], 1.)       # stays erased
        moved = [dict(uid='u2'), dict(uid='u1')]                                 # order changed
        self.assertEqual(eraser_clips.target_of(item, moved), 0)

    def test_hand_goes_down_only_when_the_page_is_shown(self):
        import eraser_clips, overlays
        item = overlays.new_eraser('u2', 1, 'Erase 2', start=10., duration=2.)
        elements = [dict(uid='u1'), dict(uid='u2')]
        frames = [(0, 0, 1), (5, 0, 1)]
        shown = eraser_clips.hand_leaves([item], elements, frames, lambda s: 1)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0]['kind'], 'Hand leaves')
        self.assertLess(shown[0]['start'], 10.)
        self.assertEqual(eraser_clips.hand_leaves([item], elements, frames, lambda s: 0), [])

    def test_not_drawn_as_a_text(self):
        import overlays
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage
        QApplication.instance() or QApplication([])
        item = overlays.new_eraser('u', 0, 'Erase 1', start=0., duration=2.)
        frame = QImage(100, 60, QImage.Format.Format_ARGB32_Premultiplied); frame.fill(0)
        overlays.paint(frame, [item], 1.)
        self.assertEqual(overlays.box(item, 100, 60), (0., 0., 0., 0.))


if __name__ == '__main__':
    unittest.main()
