"""exp.245 (the user: the Hand out of element 4 disappeared after adding element 5, which has no
hand): a hand linked "straight on to the next hand" goes back to its corner when the next
element on its page has no hand; snapping does not link to an element without a hand."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class PruneLinks(unittest.TestCase):
    def setUp(self):
        from app import Window
        self.w = Window(); self.w.resize(1400, 860); self.w.show(); APP.processEvents()
        self.addCleanup(self.w.close)
        self.w.duration.setValue(1.)
        self.w.hand_rest.setChecked(True)                   # the hand waits and travels
        self.assertTrue(self.w.add_picture())               # element 2 on the same page

    def test_a_link_to_an_element_without_a_hand_is_dropped(self):
        w = self.w
        w.scenes[0]['hand_link'] = True
        self.assertTrue(w.has_drawing_hand(1))
        self.assertEqual(w.prune_hand_links(), [])           # the next one has a hand: kept
        self.assertTrue(w.scenes[0].get('hand_link'))
        already = w.entrance.findText('Already there')
        w.entrance.setCurrentIndex(already)
        APP.processEvents()
        if w.history_timer.isActive():
            w.commit_history()                                # the change prunes the link
        self.assertFalse(w.has_drawing_hand(1))
        self.assertFalse(w.scenes[0].get('hand_link'))

    def test_snapping_does_not_link_to_an_element_without_a_hand(self):
        w = self.w
        w.entrance.setCurrentIndex(w.entrance.findText('Already there'))
        w.store_scene(thumbnail=False)
        w.snap_hands(1, 0)
        self.assertFalse(w.scenes[0].get('hand_link'))


if __name__ == '__main__':
    unittest.main()
