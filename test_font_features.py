"""Font and artwork-size tests; network is mocked and no fonts are bundled."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from engine import import_svg, export_frames, scale_animation_frame, render
from font_library import (STARTER_FONTS, font_slug, installed_font, download_google_font, make_font_text)
from app import Window

APP=QApplication.instance() or QApplication([])

def sample_font():
    for p in ('C:/Windows/Fonts/arial.ttf',
              'C:/Windows/Fonts/segoeui.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'):
        if Path(p).is_file():return Path(p)
    return None

class FontAndScaleTests(unittest.TestCase):
    def test_ten_handwriting_choices(self):
        self.assertGreaterEqual(len(STARTER_FONTS),50)
        self.assertEqual(len(set(STARTER_FONTS)),len(STARTER_FONTS))
        self.assertEqual(font_slug('Indie Flower'),'indieflower')
        with self.assertRaises(ValueError):font_slug('../')

    def test_install_includes_original_font_license(self):
        sample=sample_font()
        if sample is None:self.skipTest('System TTF unavailable')
        entries=[{'name':'Demo-Regular.ttf','download_url':
                  'https://raw.githubusercontent.com/google/fonts/main/ofl/demo/Demo-Regular.ttf'},
                 {'name':'OFL.txt','download_url':
                  'https://raw.githubusercontent.com/google/fonts/main/ofl/demo/OFL.txt'}]
        def respond(url,binary=False):
            if url.endswith('?ref=main'):return json.dumps(entries).encode()
            if url.endswith('/OFL.txt'):return b'SIL Open Font License test notice'
            if url.endswith('/Demo-Regular.ttf'):return sample.read_bytes()
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ,{'LOCALAPPDATA':d}):
                with patch('font_library._read_url',side_effect=respond):
                    saved=download_google_font('Demo')
                self.assertTrue(saved.exists())
                self.assertTrue((saved.parent/'OFL.txt').exists())
                self.assertEqual(installed_font('Demo'),saved)

    def test_font_centerline_lettering(self):
        sample=sample_font()
        if sample is None:self.skipTest('System TTF unavailable')
        drawing=make_font_text('Hello!',sample,44)
        self.assertGreater(len(drawing.strokes),4)
        self.assertTrue(any(s.length>0 for s in drawing.strokes))
        with self.assertRaises(ValueError):make_font_text('  ',sample)

    def test_scale_transparent_artwork(self):
        frame=QImage(200,100,QImage.Format.Format_ARGB32)
        frame.fill(Qt.GlobalColor.transparent)
        p=QPainter(frame);p.fillRect(80,40,40,20,Qt.GlobalColor.red);p.end()
        self.assertIs(scale_animation_frame(frame,1),frame)
        a=scale_animation_frame(frame,.5)
        b=scale_animation_frame(frame,1.5)
        def width(im):
            return sum(im.pixelColor(x,50).alpha()>100 for x in range(200))
        self.assertLess(width(a),width(frame))
        self.assertGreater(width(b),width(frame))
        self.assertEqual(a.pixelColor(0,0).alpha(),0)
        with self.assertRaises(ValueError):scale_animation_frame(frame,2.2)

    def test_letter_color_and_background_match_export(self):
        sample=sample_font()
        if sample is None:self.skipTest('No system TTF available')
        from PIL import Image
        from engine import apply_lettering_background
        from unittest.mock import patch
        from PySide6.QtGui import QColor
        drawing=make_font_text('Hello',sample,60)
        transparent=render(drawing,1,720,360)
        self.assertEqual(transparent.pixelColor(0,0).alpha(),0)
        drawing.font_color='#cc1133'
        drawing.lettering_background='#ffffff'
        colored=apply_lettering_background(render(drawing,1,720,360),drawing)
        self.assertEqual(colored.pixelColor(0,0).name(),'#ffffff')
        self.assertTrue(any(
            colored.pixelColor(x,y).red()>colored.pixelColor(x,y).blue()*1.5
            for y in range(100,260,8) for x in range(40,680,8)))
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'lettering'
            export_frames(drawing,folder,duration=.3,fps=10,width=720,height=360,
                          artwork_scale=.5)
            finished=Image.open(folder/'frame_000002.png').convert('RGBA')
            self.assertEqual(finished.getpixel((0,0)),(255,255,255,255))
            meta=json.loads((folder/'sequence.json').read_text())
            self.assertEqual(meta['lettering_background'],'#ffffff')
            self.assertFalse(meta['alpha'])
        w=Window()
        try:
            self.assertAlmostEqual(w.handsize.value(),.75)
            # Defaults are calibrated for the bundled built-in hand.
            self.assertAlmostEqual(w.ax.value(),.08)
            self.assertAlmostEqual(w.ay.value(),.13)
            self.assertTrue(w.showhand.isChecked())
            self.assertTrue(w.show_paint_hand.isChecked())
            self.assertEqual(w.font_bg_mode.currentIndex(),0)
            w.drawing=drawing
            with patch('app.QColorDialog.getColor',return_value=QColor('#4477aa')):
                w.choose_letter_color()
            self.assertEqual(drawing.font_color,'#4477aa')
            w.font_bg_mode.setCurrentIndex(2)
            self.assertEqual(drawing.lettering_background,'#000000')
            w.font_bg_mode.setCurrentIndex(0)
            self.assertIsNone(drawing.lettering_background)
            self.assertEqual(w.canvas.frame.pixelColor(0,0).alpha(),0)
        finally:
            w.close()

    def test_export_and_preview_scale(self):
        d=import_svg(Path(__file__).parent/'samples'/'drawing.svg')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'scaled'
            self.assertEqual(export_frames(d,folder,duration=.3,fps=10,
                          width=240,height=160,artwork_scale=.5),3)
            self.assertEqual(json.loads((folder/'sequence.json').read_text())['artwork_scale'],.5)
            expected=scale_animation_frame(render(d,.5,240,160),.5)
            actual=QImage(str(folder/'frame_000001.png'))
            # Keep converted images alive while copying their pixels; a
            # temporary image can be freed before bytes() reads its buffer.
            got=actual.convertToFormat(QImage.Format.Format_RGBA8888)
            want=expected.convertToFormat(QImage.Format.Format_RGBA8888)
            self.assertEqual(bytes(got.constBits()),bytes(want.constBits()))
        w=Window()
        self.assertEqual(w.artwork_size.value(),100)
        w.artwork_size.setValue(65)
        self.assertEqual(w.options()['artwork_scale'],.65)
        self.assertEqual(w.font_select.count(),11)
        w.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
