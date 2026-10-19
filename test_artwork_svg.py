"""Native SVG source, vector geometry and final fills share one coordinate frame."""
import importlib,importlib.util,tempfile,unittest
from pathlib import Path
from engine import import_svg
from projects import drawing_to_dict,drawing_from_dict
class SvgAppearanceTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('svg_appearance'),'Native SVG paint appearance is missing')
        return importlib.import_module('svg_appearance')
    def load(self,text):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'art.svg';p.write_text(text,encoding='utf-8')
            return import_svg(p)
    def test_black_fill_and_compound_hole_survive_project_roundtrip(self):
        m=self.module()
        d=self.load('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><path fill="black" fill-rule="evenodd" d="M10 10H190V90H10Z M80 35H120V65H80Z"/></svg>')
        self.assertTrue(d.svg_has_fill)
        restored=drawing_from_dict(drawing_to_dict(d))
        self.assertIn('fill-rule',restored.svg_source)
        self.assertEqual(len(restored.strokes),2)
        image=m.render_appearance(restored,200)
        self.assertEqual(image.pixelColor(image.width()//2,image.height()//2).alpha(),0)
        self.assertEqual(image.pixelColor(image.width()//8,image.height()//2).name(),'#000000')
        self.assertGreater(image.pixelColor(image.width()//8,image.height()//2).alpha(),250)
    def test_viewbox_offset_and_group_transform_align_in_viewport_coordinates(self):
        m=self.module()
        d=self.load('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="10 20 200 100"><g transform="translate(20 5)"><rect x="20" y="30" width="100" height="50" fill="#3366cc"/></g></svg>')
        self.assertEqual(tuple(round(x) for x in d.bounds),(60,30,260,130))
        image=m.render_appearance(d,200)
        self.assertEqual((image.width(),image.height()),(200,100))
        for x,y in ((10,10),(100,50),(190,90)):
            self.assertEqual(image.pixelColor(x,y).name(),'#3366cc')
            self.assertEqual(image.pixelColor(x,y).alpha(),255)
    def test_inherited_fill_opacity_and_outline_only_detection(self):
        m=self.module()
        d=self.load('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><g fill="#00aa55" fill-opacity="0.5"><rect x="10" y="10" width="80" height="80"/></g></svg>')
        image=m.render_appearance(d,120)
        self.assertTrue(d.svg_has_fill)
        self.assertAlmostEqual(image.pixelColor(60,60).alpha(),128,delta=1)
        outlines=self.load('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><path d="M10 10L90 90" fill="none" stroke="black"/></svg>')
        self.assertFalse(outlines.svg_has_fill)
        self.assertTrue(outlines.strokes)
    def test_external_resources_and_huge_intrinsic_dimensions_rejected(self):
        self.module()
        for text in (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><image href="file:///private.png"/><path d="M0 0L90 90" stroke="black"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" width="1000000000" height="1000000000"><rect width="800000000" height="800000000"/></svg>',
        ):
            with self.assertRaisesRegex(ValueError,'external|resource|dimensions|large|limit'):
                self.load(text)
    def test_repeated_large_appearance_renders_obey_cache_budget(self):
        m=self.module();m.clear_cache()
        try:
            for i in range(10):
                d=self.load('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="#%06x"/></svg>'%(i+1))
                image=m.render_appearance(d,2048)
                self.assertLessEqual(image.width()*image.height(),8_000_000)
                self.assertLessEqual(m.cache_bytes(),128*1024*1024)
        finally:m.clear_cache()
if __name__=='__main__':unittest.main()
