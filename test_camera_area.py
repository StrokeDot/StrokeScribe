"""exp.235: an element whose camera moves off its page draws in that place; Hold = way back."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication


class HoldIsWayBackTests(unittest.TestCase):
    def test_element_ends_when_the_hand_is_back(self):
        from frame_render import travel_total
        plan = (1.5, 9.0, 1.5, 10.0, {}, 0.5)        # lead, hand_end, tail, inner_total, inner, hand_start
        self.assertAlmostEqual(travel_total(plan, {}), 1.5 + 8.5 + 1.5)
        # a Pause or an eraser stage the user asked for still runs in full
        self.assertAlmostEqual(travel_total(plan, {'pause': 2.}), 10.0 - .5 + 1.5 + 1.5)
        self.assertAlmostEqual(travel_total(plan, {'erase': {'mode': 'Wipe'}}), 10.0 - .5 + 1.5 + 1.5)


class CameraAreaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_camera_off_the_page_becomes_the_area(self):
        from app import Window
        import board
        w = Window(); w.resize(1400, 860); w.show(); self.app.processEvents()
        try:
            self.assertTrue(w.add_picture())
            k = w.scene_index
            aspect = w.board_aspect()
            page = board.frames(w.scenes, aspect)[k]
            w.picture_x.setValue(40.); w.picture_y.setValue(10.); w.store_scene(thumbnail=False)
            world = (page[0] + .40 * page[2], page[1] + .10 * page[2] * aspect)
            w.scenes[k]['board'] = dict(view=[page[0] + .43 * page[2], page[1], page[2]])
            self.assertEqual(w.fit_areas_to_cameras([k]), [k])
            frame = board.frames(w.scenes, aspect)[k]
            self.assertAlmostEqual(frame[0], page[0] + .43 * page[2], places=5)
            self.assertEqual(w.scenes[k - 1]['transition'], 'Camera move')
            # the picture stays where it was on the board
            x, y = w.picture_x.value() / 100., w.picture_y.value() / 100.
            self.assertAlmostEqual(frame[0] + x * frame[2], world[0], places=2)
            self.assertAlmostEqual(frame[1] + y * frame[2] * aspect, world[1], places=2)
            # a closer look inside the page keeps the page
            w.scenes[k - 1]['board'] = dict(view=[page[0], page[1], page[2] * .5])
            self.assertEqual(w.fit_areas_to_cameras([k - 1]), [])
        finally:
            w.playing = False; w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
