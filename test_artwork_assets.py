"""Durable raster/guide provenance with safe managed materialization."""
import base64,importlib,importlib.util,tempfile,unittest
from pathlib import Path
from PIL import Image
class ArtworkAssetsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('artwork_assets'),'Durable paired artwork storage is missing')
        return importlib.import_module('artwork_assets')
    def test_pair_survives_original_files_removed(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=root/'color.png';guide=root/'lines.png'
            Image.new('RGBA',(80,50),(25,140,190,180)).save(original)
            Image.new('RGB',(80,50),'white').save(guide)
            before=original.read_bytes(),guide.read_bytes()
            data=m.capture_assets(original,guide);original.unlink();guide.unlink()
            p,g=m.materialize_assets(data,root/'cache')
            self.assertEqual((Path(p).read_bytes(),Path(g).read_bytes()),before)
            self.assertEqual(m.validate_assets(data)['schema'],1)
    def test_unsafe_extension_and_malformed_base64_rejected(self):
        m=self.module()
        for ext,raw in (('../../evil.exe','AAAA'),('.png','!!!!')):
            with self.assertRaises(ValueError):
                m.validate_assets(dict(schema=1,kind='raster',original=dict(extension=ext,data=raw),guide=None))
    def test_source_pixel_budget_is_checked_before_decoding(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'large.png';Image.new('L',(5001,4800),0).save(p)
            with self.assertRaisesRegex(ValueError,'pixel|large'):
                m.capture_assets(p)
    def test_existing_supported_images_above_16_megapixels_remain_supported(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'supported.png';Image.new('L',(4100,4000),0).save(p)
            self.assertEqual(m.capture_assets(p)['schema'],1)
    def test_materialization_does_not_trust_provenance_paths(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'input.png';Image.new('RGB',(5,5),'red').save(p)
            data=m.capture_assets(p);data['path']='../../outside'
            out,_=m.materialize_assets(data,root/'cache')
            self.assertTrue(Path(out).resolve().is_relative_to((root/'cache').resolve()))
            self.assertEqual(Path(out).read_bytes(),p.read_bytes())
if __name__=='__main__':unittest.main()
