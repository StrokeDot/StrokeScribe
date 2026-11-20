"""exp.54 (the user: a camera position as the next element, anywhere on the board, with or
without anything there; stickers should count for Match camera): + Add element → Camera
position: a step with no picture and no hand, whose camera goes where it is set."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


class CameraStep(unittest.TestCase):
    def test_a_camera_step_anywhere(self):
        import numpy as np
        from app import Window
        from engine import import_svg
        from timeline_model import state_at
        w = Window(); w.show()
        real = QDialog.exec
        seen = {}

        def fake(d):
            seen['match'] = [d.match.itemText(i) for i in range(d.match.count())]
            f = list(d.board.frame); d.board.frame = [f[0] + 3., f[1] + .4, f[2] * 1.3]   # an empty spot
            return QDialog.DialogCode.Accepted
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(20): APP.processEvents()
            w.hand_rest.setChecked(True)
            w.add_sticker('Circle')
            QDialog.exec = fake
            self.assertTrue(w.add_camera_step())
            for _ in range(20): APP.processEvents()
            QDialog.exec = real
            step = w.scenes[1]
            self.assertTrue(step['camera_step'] and step['art_off'] and step['hand_off'])
            self.assertEqual(w.scene_label(1), 'Camera')
            # exp.55: a camera in the element list, no "picture off" look, no switching it on
            self.assertEqual(step['thumb'].size().width(), 160)
            w.refresh(); APP.processEvents()
            self.assertNotIn(1, getattr(w.stage_timeline, 'element_flags', {}))
            w.switch_scene_flag(1, 'art_off', 'x')
            self.assertTrue(step['art_off'])
            self.assertTrue(any(m.startswith('Sticker · Circle') for m in seen['match']))   # stickers count
            self.assertAlmostEqual(step['board']['view'][2], seen and step['board']['view'][2])
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(20): APP.processEvents()
            w.preview_scope.setCurrentIndex(1)
            for _ in range(20): APP.processEvents()
            lay = w.timeline_layout()
            self.assertEqual(len(lay.items), 3)
            self.assertNotIn(1, [m[4] for m in w.hand_marks()])                   # no hand for it
            mid = lay.items[1].start + lay.items[1].length / 2
            img = w.timeline_frame(state_at(lay, mid), 480, 270, mid)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(270, img.bytesPerLine() // 4, 4)[:, :480]
            self.assertEqual(len(np.unique(a.reshape(-1, 4)[:, :3], axis=0)), 1)   # the empty spot, nothing drawn
            end = lay.items[2].start + lay.items[2].length - .1
            img = w.timeline_frame(state_at(lay, end), 480, 270, end)
            b = np.frombuffer(img.constBits(), np.uint8).reshape(270, img.bytesPerLine() // 4, 4)[:, :480]
            self.assertGreater(len(np.unique(b.reshape(-1, 4)[:, :3], axis=0)), 5)   # the next element shows
        finally:
            QDialog.exec = real
            w.close()



class Restore(unittest.TestCase):
    def test_restore_camera_and_picture(self):
        """exp.55 (the user, like VideoScribe): Restore camera / Restore picture in Set camera."""
        from app import Window
        from engine import import_svg
        w = Window(); w.show()
        real = QDialog.exec
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(20): APP.processEvents()
            b = dict(w.scenes[1].get('board') or {}); b['view'] = [5., 2., .4]; w.scenes[1]['board'] = b
            w.artwork_size.setValue(40); w.picture_x.setValue(-20); w.store_scene(thumbnail=False)
            from PySide6.QtWidgets import QPushButton

            def fake(d):
                buttons = {x.text(): x for x in d.findChildren(QPushButton)}
                buttons['Restore camera'].click(); buttons['Restore picture'].click()
                return QDialog.DialogCode.Accepted
            QDialog.exec = fake
            w.set_camera(1)
            self.assertNotIn('view', w.scenes[1].get('board') or {})            # its default camera
            self.assertEqual((w.artwork_size.value(), w.picture_x.value(), w.picture_y.value()), (100, 0, 0))
        finally:
            QDialog.exec = real
            w.close()



class CameraTab(unittest.TestCase):
    def test_the_buttons_are_in_the_camera_tab(self):
        """exp.56 (the user: where is Restore camera?): in the Camera tab (also in Advanced edit)."""
        from app import Window
        from engine import import_svg
        w = Window(); w.show()
        try:
            w.set_drawing(import_svg('samples/drawing.svg'))
            w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
            for _ in range(20): APP.processEvents()
            for b in (w.set_camera_here, w.restore_camera_button, w.restore_picture_button):
                self.assertTrue(w.inspector_tabs.widget(w.inspector_tabs.count() - 1) is not None)
                page = b.parentWidget()
                while page is not None and page.parentWidget() is not None and page.parentWidget() is not w.inspector_tabs:
                    page = page.parentWidget()
            board = dict(w.scenes[1].get('board') or {}); board['view'] = [5., 2., .4]; w.scenes[1]['board'] = board
            w.artwork_size.setValue(30); w.picture_x.setValue(-25); w.store_scene(thumbnail=False)
            w.restore_camera_button.click()
            self.assertNotIn('view', w.scenes[1].get('board') or {})
            w.restore_picture_button.click()
            self.assertEqual((w.artwork_size.value(), w.picture_x.value(), w.picture_y.value()), (100, 0, 0))
        finally:
            w.close()



class RestoreMeansThePage(unittest.TestCase):
    """exp.56 (the user: Restore camera showed the page, the preview kept the close camera):
    an element on the same page as one with a close camera keeps that camera when it has none
    of its own (exp.208), so Restore camera must give it the whole page as its own."""

    def setUp(self):
        from app import Window
        from engine import import_svg
        self.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(20): APP.processEvents()
        board = dict(w.scenes[0].get('board') or {}); board['view'] = [-.2, .05, .35]; w.scenes[0]['board'] = board
        w.add_picture(); w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(20): APP.processEvents()
        w.store_scene(thumbnail=False)

    def tearDown(self):
        self.w.close()

    def shown(self, k):
        import board
        return board.views(self.w.scenes, self.w.board_frames(), self.w.edited_place())[k]

    def test_before_it_keeps_the_close_camera(self):
        self.assertEqual(tuple(self.w.board_frames()[1]), tuple(self.w.board_frames()[0]))
        self.assertAlmostEqual(self.shown(1)[2], .35)

    def test_restore_in_the_window(self):
        import set_camera_dialog
        from PySide6.QtWidgets import QDialog
        old = set_camera_dialog.SetCameraDialog.exec
        def press_restore(dialog):
            dialog.reset(); return QDialog.DialogCode.Accepted
        set_camera_dialog.SetCameraDialog.exec = press_restore
        try:
            self.w.set_camera(1)
        finally:
            set_camera_dialog.SetCameraDialog.exec = old
        page = self.w.board_frames()[1]
        for a, b in zip(self.shown(1), page): self.assertAlmostEqual(a, b)

    def test_restore_in_the_camera_tab(self):
        self.w.restore_camera_button.click()
        page = self.w.board_frames()[1]
        for a, b in zip(self.shown(1), page): self.assertAlmostEqual(a, b)

    def test_an_element_on_its_own_page_stores_nothing(self):
        self.w.scene_index = 0
        board = dict(self.w.scenes[0]['board']); self.w.restore_camera(0)
        self.assertNotIn('view', self.w.scenes[0].get('board') or {})


if __name__ == '__main__':
    unittest.main()
