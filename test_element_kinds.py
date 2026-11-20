"""Element kind: lettering vs imported SVG / image, for new and old projects."""
import unittest
from types import SimpleNamespace

from element_kinds import (IMAGE, LETTERING, SVG, is_imported, kind_of_drawing,
                           kind_of_state, lettering_title, source_card)


class KindOfDrawing(unittest.TestCase):
    def test_source_kinds(self):
        for source_kind, kind in (('font', LETTERING), ('lettering', LETTERING),
                                  ('svg', SVG), ('image', IMAGE)):
            self.assertEqual(kind_of_drawing(SimpleNamespace(source_kind=source_kind)), kind)

    def test_sample_and_missing(self):
        self.assertEqual(kind_of_drawing(SimpleNamespace()), SVG)
        self.assertEqual(kind_of_drawing(None), SVG)


class KindOfState(unittest.TestCase):
    def test_stored_kind_wins(self):
        self.assertEqual(kind_of_state({'element_kind': 'lettering', 'source': 'svg'}), LETTERING)

    def test_old_lettering_saved_as_svg_is_lettering(self):
        # Before element_kind, lettering scenes were saved with source 'svg'.
        old = {'source': 'svg', 'drawing': {'attributes': {'source_kind': 'font'}}}
        self.assertEqual(kind_of_state(old), LETTERING)
        old['drawing']['attributes']['source_kind'] = 'lettering'
        self.assertEqual(kind_of_state(old), LETTERING)

    def test_old_image_and_svg(self):
        self.assertEqual(kind_of_state({'source': 'image'}), IMAGE)
        self.assertEqual(kind_of_state({'source': 'svg', 'image': None,
                                        'drawing': {'attributes': {}}}), SVG)
        self.assertEqual(kind_of_state({'drawing': {'attributes': {'source_kind': 'image'}}}), IMAGE)

    def test_bad_input(self):
        self.assertEqual(kind_of_state(None), SVG)
        self.assertEqual(kind_of_state({'element_kind': 'banana'}), SVG)


class Cards(unittest.TestCase):
    def test_lettering_card_never_names_a_file(self):
        heading, detail = source_card(LETTERING, title='x.svg', filename='x.svg', text='Hello world!')
        self.assertEqual(heading, 'Handwriting element')
        self.assertNotIn('.svg', detail)
        self.assertNotIn('x.svg', detail)
        self.assertIn('Hello world!', detail)

    def test_imported_cards_use_the_real_name(self):
        self.assertEqual(source_card(SVG, filename='headset.svg'), ('SVG drawing', 'headset.svg'))
        self.assertEqual(source_card(IMAGE, filename='brain.png'), ('Image', 'brain.png'))

    def test_title_and_imported(self):
        self.assertEqual(lettering_title('Hello   world'), 'Lettering — Hello world')
        self.assertTrue(lettering_title('a' * 40).endswith('…'))
        self.assertTrue(is_imported(SVG) and is_imported(IMAGE) and not is_imported(LETTERING))


if __name__ == '__main__':
    unittest.main()
