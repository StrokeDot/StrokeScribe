"""exp.86: the whole video and the export use the same colour picture as the element
view: cleaned and cropped to its content, so colours sit exactly on the lines.

Before, a colour PNG with transparent margins was cropped when editing the element
but used whole in the whole video / export, so there the colours came out smaller
and shifted against the lines (the TV in the user's project)."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


@unittest.skipIf(SKIP, 'needs Qt')
class SceneColourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def state(self, clean=True):
        from PIL import Image, ImageDraw
        from adaptive_hand import qimage
        from engine import Drawing, Stroke
        from projects import drawing_to_dict, qimage_to_b64
        im = Image.new('RGBA', (300, 200), (0, 0, 0, 0))          # wide transparent margins
        ImageDraw.Draw(im).rectangle((60, 40, 239, 159), fill=(150, 90, 40, 255))
        d = Drawing([Stroke('box', [(60, 40), (240, 40), (240, 160), (60, 160), (60, 40)], width=2)],
                    (60, 40, 240, 160), [])
        return {'source': 'svg', 'drawing': drawing_to_dict(d), 'color_png': qimage_to_b64(qimage(im)),
                'svg_color_override': True,
                'settings': {'use_color': True, 'clean_color': clean, 'reveal_mode': 'Adaptive Hand Painting'}}

    def test_whole_video_uses_the_cropped_colours(self):
        from scenes import job_from_state
        from color_reveal import project_color
        state = self.state()
        _, options, _ = job_from_state(state)
        picture = options['final_image']
        self.assertEqual((picture.width(), picture.height()), (180, 120))     # cropped to the content
        self.assertIs(picture, project_color(state)[1])                        # the very picture the element view uses

    def test_without_cleaning_the_picture_is_kept(self):
        from scenes import job_from_state
        _, options, _ = job_from_state(self.state(clean=False))
        self.assertEqual((options['final_image'].width(), options['final_image'].height()), (300, 200))

    def test_window_and_whole_video_agree(self):
        from app import Window
        from scenes import job_from_state
        state = self.state()
        w = Window()
        try:
            w.apply_scene_state(state)
            element = w.final_image
            _, options, _ = job_from_state(state)
            self.assertEqual((element.width(), element.height()),
                             (options['final_image'].width(), options['final_image'].height()))
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
