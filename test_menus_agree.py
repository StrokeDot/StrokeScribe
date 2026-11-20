"""exp.65 (the user: the menus do not agree; the menu audit): one place per question, and the
words say what really happens."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from unittest import mock

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog

APP = QApplication.instance() or QApplication([])


def pump(n=20):
    for _ in range(n): APP.processEvents()


class MenusAgree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg')); pump()
        w.hand_rest.setChecked(True); w.preview_scope.setCurrentIndex(1); pump()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def boxes(self, opener, act=None):
        seen = {}

        def run(dialog):
            boxes = dialog.findChildren(QComboBox)
            seen['starts'] = next(b for b in boxes if b.count() and b.itemText(0).startswith('Where the hand is'))
            seen['ends'] = next(b for b in boxes if b.count() and b.itemText(0) == 'Stop and wait')
            seen['checks'] = [c.text() for c in dialog.findChildren(QCheckBox)]
            seen['texts'] = [[b.itemText(i) for i in range(b.count())] for b in (seen['starts'], seen['ends'])]
            if act is None:
                return QDialog.DialogCode.Rejected
            act(seen['starts'], seen['ends'])
            return QDialog.DialogCode.Accepted
        with mock.patch.object(QDialog, 'exec', run):
            opener()
        return seen

    def test_stays_where_it_finished_is_an_ending_not_a_checkbox(self):
        w = self.w
        seen = self.boxes(lambda: w.edit_hand_glide(0), lambda s, e: e.setCurrentIndex(e.findData('link')))
        self.assertFalse(any('Stays where it finished' in c for c in seen['checks']))
        self.assertTrue(any('Stays where it finished' in x for x in seen['texts'][1]))
        self.assertTrue(w.scenes[0].get('hand_link'))
        self.assertIsNone(w.scenes[0].get('hand_flow'))
        seen = self.boxes(lambda: w.edit_hand_glide(0))
        self.assertEqual(seen['ends'].currentData(), 'link')                 # shown as it is
        self.boxes(lambda: w.edit_hand_glide(0), lambda s, e: e.setCurrentIndex(0))
        self.assertFalse(w.scenes[0].get('hand_link'))

    def test_the_sticker_window_has_in_from_below_and_the_panel_only_says_it(self):
        import stickers
        w = self.w
        item = w.add_sticker('Circle'); item['drawing'] = 'Hand: outline'
        w.select_overlay(item['id']); pump()
        self.assertNotIsInstance(w.sticker_hand_way, QComboBox)             # one place to choose
        self.assertEqual(w.sticker_hand_way.text(), 'From where the hand is → back to where the hand waits')
        seen = self.boxes(lambda: w.edit_sticker_hand(item['id']),
                          lambda s, e: s.setCurrentIndex(s.findData('below')))
        self.assertEqual(item['hand_way'], 'Comes in and leaves')
        self.assertEqual(seen['ends'].currentData(), 'below')                # the two go together
        w.sync_sticker_panel()
        self.assertEqual(w.sticker_hand_way.text(), 'Comes in from below → leaves below')
        self.boxes(lambda: w.edit_sticker_hand(item['id']), lambda s, e: e.setCurrentIndex(0))
        self.assertEqual(item['hand_way'], 'Rests in its corner')
        self.assertEqual(stickers.hand_summary(dict(item, hand_flow='free')),
                         'From where the hand is → stays where you put it')

    def test_no_corner_promise_in_the_back_row(self):
        from PySide6.QtWidgets import QLabel
        w = self.w
        texts = []

        def look(dialog):
            texts.extend(l.text() + ' ' + l.toolTip() for l in dialog.findChildren(QLabel))
            return QDialog.DialogCode.Rejected
        with mock.patch.object(QDialog, 'exec', look):
            w.edit_hand_glide(0)
        back = [t for t in texts if t.startswith('Back')]
        self.assertTrue(back)
        self.assertFalse(any('its corner' in t for t in back))


if __name__ == '__main__':
    unittest.main()
