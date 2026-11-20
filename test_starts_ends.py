"""exp.44 (the user): the Hand window has Starts (where the hand is / Free beginning: drag the
green dot) and Ends (Stop and wait, Through / Near the corner, Free ending: drag the red dot),
the same for an element's hand and a sticker's; a sticker's Free ending leaves the hand there."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
os.environ.setdefault('STROKESCRIBE_PREVIEW_CACHE', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


class StartsEnds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import Window
        from engine import import_svg
        cls.w = w = Window(); w.show()
        w.set_drawing(import_svg('samples/drawing.svg'))
        w.add_scene(); w.set_drawing(import_svg('samples/drawing.svg'))
        for _ in range(40): APP.processEvents()
        w.hand_rest.setChecked(True)
        w.preview_scope.setCurrentIndex(1)
        for _ in range(40): APP.processEvents()
        w.board_frames = lambda: [(0., 0., 1.), (0., 0., 1.)]

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def tearDown(self):
        w = self.w
        w.overlays[:] = [o for o in w.overlays if o.get('kind') != 'sticker']
        for s in w.scenes:
            for key in ('hand_flow', 'hand_end', 'hand_begin', 'hand_start', 'hand_link'):
                s.pop(key, None)
        w._scene_cache = {}; w.__dict__.pop('_memo', None)
        w.refresh(); APP.processEvents()

    def window_rows(self, opener):
        """The Hand window's Starts / Ends choices (the window opened and cancelled)."""
        seen = {}
        real = QDialog.exec

        def fake(dialog):
            from PySide6.QtWidgets import QComboBox
            boxes = dialog.findChildren(QComboBox)
            seen['texts'] = [[b.itemText(i) for i in range(b.count())] for b in boxes]
            return QDialog.DialogCode.Rejected
        QDialog.exec = fake
        try:
            opener()
        finally:
            QDialog.exec = real
        return seen['texts']

    def test_a_both_windows_have_starts_and_ends(self):
        w = self.w
        texts = self.window_rows(lambda: w.edit_hand_glide(1))
        self.assertTrue(any(t[0].startswith('Where the hand is') and any('Free beginning' in x for x in t) for t in texts))
        ends = next(t for t in texts if t and t[0] == 'Back to its corner (and waits there)')
        self.assertTrue(any('Through the corner' in x for x in ends) and any('Free ending' in x for x in ends))
        w.add_sticker('Circle')
        st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        st['drawing'] = 'Hand: outline'
        texts = self.window_rows(lambda: w.edit_sticker_hand(st['id']))
        self.assertTrue(any(t[0].startswith('Where the hand is') for t in texts))
        ends = next(t for t in texts if t and t[0] == 'Back to its corner (and waits there)')
        self.assertTrue(any('Free ending' in x for x in ends))

    def test_b_free_beginning_moves_the_way_back_before(self):
        w = self.w
        snap = w.glide_snapshot(1, 'in')
        kind, ref, movable, _ = w.green_dot(1, snap, False)
        self.assertEqual((kind, movable), ('corner', False))         # where the hand is: fixed
        kind, ref, movable, _ = w.green_dot(1, snap, True)
        self.assertEqual((kind, ref, movable), ('prev', 0, True))     # Free beginning: draggable
        W, H = snap['size']
        w.apply_start_move(w.start_move(snap, kind, ref, (.2 * W, .3 * H)))
        self.assertEqual(w.scenes[0]['hand_flow'], 'free')            # element 1's way back ends there
        w._scene_cache = {}; w.__dict__.pop('_memo', None)
        snap = w.glide_snapshot(1, 'in')
        self.assertAlmostEqual(snap['a'][0], .2 * W, delta=2); self.assertAlmostEqual(snap['a'][1], .3 * H, delta=2)

    def test_c_a_sticker_free_ending_leaves_the_hand_there(self):
        import stickers
        w = self.w
        end = max(b for a, b in w.hand_busy_spans())
        w.add_sticker('Circle')
        st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        st.update(drawing='Hand: outline', start=round(end + 1., 2), hand_flow='free', hand_end=[.25, .3])
        w.refresh(); APP.processEvents()
        W = 960; H = round(W * w.board_aspect())
        span = stickers.busy(st)
        tip = stickers.hand_tip(st, span[1] - 1e-3, W, H, stickers.home_on_frame(st, W, H))
        self.assertAlmostEqual(tip[0], .25 * W, delta=4); self.assertAlmostEqual(tip[1], .3 * H, delta=4)
        spot, _ = w.hand_spot_at(W, H, span[1] + .5)                  # then the hand waits there
        self.assertAlmostEqual(spot[0], .25 * W, delta=3); self.assertAlmostEqual(spot[1], .3 * H, delta=3)
        self.assertEqual(w.hand_source_at(span[1] + .5)[0], 'sticker')
        st2 = dict(st); w.add_sticker('Arrow')                        # a sticker after it starts there
        nxt = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        nxt.update(drawing='Hand: outline', start=round(span[1] + 1.5, 2))
        w.refresh(); APP.processEvents()
        self.assertAlmostEqual(nxt['_home_screen'][0], .25, delta=.01)
        self.assertAlmostEqual(nxt['_home_screen'][1], .3, delta=.01)

    def test_d_hand_paths_sticker_red_dot(self):
        w = self.w
        end = max(b for a, b in w.hand_busy_spans())
        w.add_sticker('Circle')
        st = [o for o in w.overlays if o.get('kind') == 'sticker'][-1]
        st.update(drawing='Hand: outline', start=round(end + 1., 2), hand_flow='free', hand_end=[.25, .3])
        w.refresh(); APP.processEvents()
        rows = [r for r in w.hand_path_rows() if r['kind'] == 'sticker']
        out = next(r for r in rows if r['which'] == 'out')
        self.assertTrue(out['movable_end'])
        real = QDialog.exec

        def fake(d):
            if hasattr(d, 'moves'):
                i = next(i for i, m in enumerate(d.moves) if m['kind'] == 'sticker' and m['which'] == 'out')
                d.list.setCurrentRow(i)
                x0, y0, pw, ph = d.moves[i]['place']
                d.canvas.b = (x0 + .6 * pw, y0 + .7 * ph)
                return QDialog.DialogCode.Accepted
            return QDialog.DialogCode.Rejected
        QDialog.exec = fake
        try:
            w.open_hand_paths()
        finally:
            QDialog.exec = real
        self.assertAlmostEqual(st['hand_end'][0], .6, delta=.01); self.assertAlmostEqual(st['hand_end'][1], .7, delta=.01)


if __name__ == '__main__':
    unittest.main()
