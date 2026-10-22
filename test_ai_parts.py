"""exp.89: AI parts for the Painter mode (Segment Anything finds the real parts)."""
import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    import PySide6  # noqa: F401
    SKIP = False
except ImportError:
    SKIP = True


class CatalogTests(unittest.TestCase):
    def test_model_files(self):
        import ai_parts
        files = ai_parts.model_files()
        self.assertEqual([f.name for f in files], ['config.json', 'preprocessor_config.json', 'model.safetensors'])
        self.assertTrue(all('/resolve/' in f.url and f.folder == ai_parts.FOLDER for f in files))
        self.assertGreater(ai_parts.download_size_gb(), 2)

    def test_installed_needs_full_size(self):
        import tempfile
        import ai_parts
        from ai_engine import Paths
        with tempfile.TemporaryDirectory() as tmp:
            paths = Paths(tmp)
            self.assertFalse(ai_parts.model_ready(paths))
            for f in ai_parts.model_files()[:2]:
                target = paths.model_path(f); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'x' * f.size)
            self.assertFalse(ai_parts.model_ready(paths))                     # the big file is missing


@unittest.skipIf(SKIP, 'needs Qt')
class PainterPartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def scene(self):
        import numpy as np
        from PIL import Image, ImageDraw
        from adaptive_hand import qimage
        from engine import Drawing, Stroke
        im = Image.new('RGBA', (160, 120), (0, 0, 0, 0))
        p = ImageDraw.Draw(im)
        p.rectangle((4, 4, 155, 115), fill=(200, 190, 160, 255))
        # Shading that colour areas would split into two parts; the AI sees one object.
        p.rectangle((4, 4, 80, 115), fill=(150, 140, 110, 255))
        labels = np.zeros((120, 160), np.uint16); labels[4:116, 4:156] = 1
        labels[40:80, 100:140] = 2                                          # one detail part
        d = Drawing([Stroke('outline', [(4, 4), (156, 4), (156, 116), (4, 116), (4, 4)], width=2),
                     Stroke('last', [(150, 110), (152, 110)], width=2)], (0, 0, 160, 120), [])
        return d, qimage(im), Image.fromarray(labels)

    def test_painter_uses_the_ai_parts(self):
        import hashlib
        from painter_paint import build_painter_plan
        d, image, labels = self.scene()
        colour = build_painter_plan(d, image, .1, .5)
        d.ai_parts_image = labels
        d.ai_parts_digest = hashlib.sha1(labels.tobytes()).hexdigest()
        ai = build_painter_plan(d, image, .1, .5)
        self.assertEqual(ai.region_count, 2)                                # the object and its detail
        gw = ai.size[0]
        dark, light = 30 * gw + 20, 30 * gw + 90                           # grid cells left and right of the shading edge
        self.assertEqual(ai.labels[dark], ai.labels[light])                # one object, whatever its shading
        self.assertNotEqual(colour.labels[dark], colour.labels[light])     # colour areas split it

    def test_plan_cache_knows_the_parts(self):
        import hashlib
        from adaptive_hand import _plan_key
        d, image, labels = self.scene()
        d.paint_method = 'painter'
        before = _plan_key(d, image, .1, .5)
        d.ai_parts_image = labels
        d.ai_parts_digest = hashlib.sha1(labels.tobytes()).hexdigest()
        self.assertNotEqual(before, _plan_key(d, image, .1, .5))

    def test_parts_are_saved_with_the_project(self):
        import numpy as np
        from projects import drawing_from_dict, drawing_to_dict
        d, image, labels = self.scene()
        d.ai_parts_image = labels; d.ai_parts_digest = 'x'; d.ai_parts_count = 2
        back = drawing_from_dict(drawing_to_dict(d))
        self.assertEqual(back.ai_parts_count, 2)
        from ai_parts import regions_of
        self.assertEqual(regions_of(back.ai_parts_image, (16, 12)), regions_of(labels, (16, 12)))
        self.assertTrue(np.array_equal(np.asarray(back.ai_parts_image.convert('I')), np.asarray(labels.convert('I'))))

    def test_parts_row_only_for_painter(self):
        from app import Window
        w = Window()
        try:
            w.show(); self.app.processEvents()
            w.reveal_mode.setCurrentText('Adaptive Hand Painting'); self.app.processEvents()
            self.assertFalse(w.find_parts_button.isVisible())
            w.reveal_mode.setCurrentText(w.PAINTER_TEXT); w.show_right_panel('animation')
            w.section_painting.set_expanded(True); self.app.processEvents()
            self.assertTrue(w.find_parts_button.isVisible())
            self.assertIn('colour areas', w.painter_parts_note.text())
        finally:
            w.close()

    def test_set_and_forget_parts(self):
        from app import Window
        from engine import import_svg
        here = Path(__file__).parent
        w = Window()
        try:
            w.set_drawing(import_svg(here / 'samples' / 'drawing.svg'))
            _, _, labels = self.scene()
            labels.info['parts'] = 2
            w.set_ai_parts(labels)
            self.assertIn('2 real parts', w.painter_parts_note.text())
            self.assertTrue(w.colour_parts_button.isEnabled())
            w.forget_ai_parts()
            self.assertFalse(hasattr(w.drawing, 'ai_parts_image'))
            self.assertFalse(w.colour_parts_button.isEnabled())
        finally:
            w.close()


if __name__ == '__main__':
    unittest.main()
