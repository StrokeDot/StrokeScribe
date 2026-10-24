"""Library (safe copies of images and hands) and automatic pen-tip finding."""
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import library
from hand_tip import find_tip

HAND = Path(__file__).parent / 'assets' / 'default_hand.png'
TIP = (.093, .149)        # graphite point of the built-in hand (measured)


class PenTipTests(unittest.TestCase):
    def assertNear(self, found, expected, tolerance=.02):
        self.assertIsNotNone(found)
        self.assertLess(abs(found[0] - expected[0]), tolerance, found)
        self.assertLess(abs(found[1] - expected[1]), tolerance, found)

    def test_built_in_hand_in_any_orientation(self):
        hand = Image.open(HAND).convert('RGBA')
        self.assertNear(find_tip(hand), TIP)
        self.assertNear(find_tip(ImageOps.mirror(hand)), (1 - TIP[0], TIP[1]))
        self.assertNear(find_tip(ImageOps.flip(hand)), (TIP[0], 1 - TIP[1]))
        self.assertNear(find_tip(hand.rotate(90, expand=True)), (TIP[1], 1 - TIP[0]))
        self.assertGreater(find_tip(hand)[2], .5)

    def test_simple_drawn_hand_and_empty_image(self):
        img = Image.new('RGBA', (400, 400), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((250, 250, 400, 400), fill=(200, 150, 120, 255))      # arm from the corner
        d.ellipse((180, 180, 300, 300), fill=(210, 160, 130, 255))       # hand
        d.polygon([(200, 200), (60, 80), (68, 72), (215, 190)], fill=(230, 180, 80, 255))  # pencil
        self.assertNear(find_tip(img), (60 / 400, 80 / 400), .03)
        self.assertIsNone(find_tip(Image.new('RGBA', (100, 100), (0, 0, 0, 0))))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ['STROKESCRIBE_CONFIG_DIR'] = str(self.dir / 'config')
        settings = library.load_settings()
        settings['root'] = str(self.dir / 'Lib')
        library.save_settings(settings)

    def tearDown(self):
        del os.environ['STROKESCRIBE_CONFIG_DIR']
        self.tmp.cleanup()

    def picture(self, name, colour):
        path = self.dir / name
        Image.new('RGB', (40, 30), colour).save(path)
        return path

    def test_copies_are_safe_and_organised(self):
        lib = library.Library()
        a = self.picture('cat.png', 'red')
        item = lib.add('images', a)
        self.assertEqual(item.path.parent, self.dir / 'Lib' / 'Images')
        a.unlink()                                              # original deleted: copy stays
        self.assertTrue(item.path.is_file())
        same = self.picture('again.png', 'red')
        self.assertEqual(lib.add('images', same).file, item.file)   # same picture: no duplicate
        other = self.picture('cat.png', 'blue')
        second = lib.add('images', other)
        self.assertEqual(second.file, 'cat (2).png')
        self.assertEqual([i.file for i in lib.items('images')], ['cat (2).png', 'cat.png'])
        self.assertEqual([i.file for i in lib.items('images', 'cat (2')], ['cat (2).png'])
        with self.assertRaises(ValueError):
            lib.add('hands', self.dir / 'x.svg')
        # Files copied into the folder by hand show up too.
        Image.new('RGB', (5, 5)).save(self.dir / 'Lib' / 'Images' / 'dropped.png')
        self.assertIn('dropped.png', [i.file for i in lib.items('images')])
        lib.rename(second, 'Blue cat')
        self.assertIn('Blue cat', [i.name for i in lib.items('images')])

    def test_delete_is_recoverable_and_hand_tips_are_kept(self):
        lib = library.Library()
        hand = lib.add('hands', HAND, tip=TIP)
        self.assertEqual(lib.tip_for(hand.path), TIP)
        self.assertIsNone(lib.tip_for(HAND))                    # not a library file
        lib.set_tip(hand, (.2, .3))
        self.assertEqual(lib.items('hands')[0].tip, (.2, .3))
        moved = lib.delete(hand)
        self.assertTrue(moved.is_file())
        self.assertIn('Deleted items', str(moved))
        self.assertEqual(lib.items('hands'), [])

    def test_move_library_folder(self):
        lib = library.Library()
        item = lib.add('images', self.picture('a.png', 'green'))
        new_root = self.dir / 'Elsewhere' / 'StrokeScribe Library'
        lib.move_to(new_root)
        self.assertEqual(library.load_settings()['root'], str(new_root))
        self.assertEqual([i.file for i in library.Library().items('images')], [item.file])
        self.assertFalse((self.dir / 'Lib' / 'Images' / item.file).exists())


    def test_move_conflicting_names_keeps_both_images_and_indexes(self):
        import json
        lib = library.Library()
        old = lib.add('images', self.picture('cat.png', 'red'), name='Original red')
        new_root = self.dir / 'Elsewhere' / 'StrokeScribe Library'
        target_folder = new_root / 'Images'
        target_folder.mkdir(parents=True)
        Image.new('RGB', (40, 30), 'blue').save(target_folder / 'cat.png')
        (target_folder / 'index.json').write_text(json.dumps({
            'cat.png': {'name': 'Already there blue', 'added': 1.}
        }))
        lib.move_to(new_root)
        items = {item.name: item for item in library.Library().items('images')}
        self.assertEqual(set(items), {'Already there blue', 'Original red'})
        self.assertEqual(items['Already there blue'].file, 'cat.png')
        self.assertEqual(items['Original red'].file, 'cat (2).png')
        self.assertEqual(Image.open(items['Original red'].path).getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(Image.open(items['Already there blue'].path).getpixel((0, 0)), (0, 0, 255))
        self.assertFalse(old.path.exists())

    def test_move_same_contents_preserves_destination_and_source_metadata(self):
        import json
        lib = library.Library()
        old = lib.add('images', self.picture('cat.png', 'red'), name='Red original')
        new_root = self.dir / 'Another'
        target = new_root / 'Images'
        target.mkdir(parents=True)
        Image.open(old.path).save(target / 'cat.png')
        (target / 'index.json').write_text(json.dumps({
            'cat.png': {'name': 'Already there', 'added': 1.}
        }))
        lib.move_to(new_root)
        self.assertEqual((target / 'cat.png').read_bytes(), self.picture('same.png', 'red').read_bytes())
        self.assertEqual(len(library.Library().items('images')), 1)

    def test_colliding_existing_suffix_reuses_identical_hand_and_retains_tip(self):
        import json
        lib = library.Library()
        old = lib.add('hands', HAND, name='My calibrated hand', tip=TIP)
        new_root = self.dir / 'Existing'
        folder = new_root / 'Hands'
        folder.mkdir(parents=True)
        # The unnumbered name differs, but a previous partially copied
        # identical version already exists under the numbered name.
        Image.new('RGBA', (8, 8), 'red').save(folder / old.file)
        suffix = Path(old.file).with_name(Path(old.file).stem + ' (2).png').name
        (folder / suffix).write_bytes(old.path.read_bytes())
        (folder / 'index.json').write_text(json.dumps({
            old.file: {'name': 'Other hand', 'added': 1},
            suffix: {'name': 'Existing copy', 'added': 2}
        }))
        lib.move_to(new_root)
        existing = next(i for i in library.Library().items('hands') if i.file == suffix)
        self.assertEqual(existing.tip, TIP)
        self.assertEqual(len(library.Library().items('hands')), 2)

    def test_move_interrupted_copy_never_discards_original(self):
        from unittest.mock import patch
        lib = library.Library()
        old = lib.add('images', self.picture('cat.png', 'green'))
        new_root = self.dir / 'Broken'
        with patch.object(library.shutil, 'copy2', side_effect=OSError('disk disconnected')):
            with self.assertRaises(OSError):
                lib.move_to(new_root)
        self.assertTrue(old.path.is_file())
        self.assertEqual(library.load_settings()['root'], str(self.dir / 'Lib'))
        self.assertEqual(library.Library().items('images')[0].file, 'cat.png')


@unittest.skipIf(os.environ.get('STROKESCRIBE_SKIP_QT') == '1', 'needs Qt')
class LibraryWindowTests(LibraryTests):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_loading_a_hand_keeps_a_copy_and_finds_the_tip(self):
        from PySide6.QtWidgets import QFileDialog
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        hand = self.dir / 'my hand.png'
        Image.open(HAND).save(hand)
        original = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(hand), ''))
        try:
            w.loadhand()
        finally:
            QFileDialog.getOpenFileName = original
        self.assertFalse(w.hand_builtin)
        self.assertAlmostEqual(w.ax.value(), TIP[0], delta=.02)
        self.assertAlmostEqual(w.ay.value(), TIP[1], delta=.02)
        self.assertIn('automatically', w.hand_name.text())
        items = library.Library().items('hands')
        self.assertEqual(len(items), 1)
        self.assertIsNotNone(items[0].tip)                      # remembered with the hand
        # A manual adjustment is remembered for next time.
        w.ax.setValue(.111); w.remember_tip()
        self.assertAlmostEqual(library.Library().items('hands')[0].tip[0], .111)
        w.use_builtin_hand()
        w.use_library_item('hands', library.Library().items('hands')[0])
        self.assertAlmostEqual(w.ax.value(), .111)

    def test_library_window_lists_and_uses_items(self):
        from library_dialog import LibraryDialog, PenTipDialog
        from PySide6.QtGui import QImage
        lib = library.Library()
        lib.add('images', self.picture('photo.png', 'red'))
        used = []
        d = LibraryDialog(None, 'images', lambda c, i: used.append((c, i.file)))
        self.addCleanup(d.close)
        self.assertEqual(d.grid.count(), 1)
        self.assertFalse(d.use_button.isEnabled())
        d.grid.setCurrentRow(0)
        self.assertTrue(d.use_button.isEnabled())
        d.use()
        self.assertEqual(used, [('images', 'photo.png')])
        d.set_category('hands')
        self.assertEqual(d.grid.count(), 0)
        self.assertTrue(d.empty.isVisibleTo(d))
        self.assertEqual(d.add_files([str(HAND)]), 1)
        self.assertIsNotNone(lib.items('hands')[0].tip)          # tip found on upload
        tip = PenTipDialog(None, QImage(str(HAND)))
        self.addCleanup(tip.close)
        self.assertAlmostEqual(tip.tip[0], TIP[0], delta=.02)

    def test_imported_image_is_kept_in_the_library(self):
        from app import Window
        w = Window()
        self.addCleanup(w.close)
        path = self.picture('sketch.png', 'purple')
        kept = w.keep_in_library('images', str(path))
        self.assertEqual(Path(kept).parent, self.dir / 'Lib' / 'Images')
        settings = library.load_settings(); settings['keep_imports'] = False; library.save_settings(settings)
        self.assertEqual(w.keep_in_library('images', str(path)), str(path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
