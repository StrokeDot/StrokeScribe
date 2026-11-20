"""exp.41 (the user): Hand paths: every hand way (elements, stickers, Hand motions) in time order,
one line per hand, and the green / red dots can be dragged there (no jumps)."""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
from PySide6.QtWidgets import QApplication, QDialog

APP = QApplication.instance() or QApplication([])


class Overview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import camera_clips
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
        lay = w.timeline_layout()
        cls.clip = c = camera_clips.new_clip('Hand motion', round(lay.items[0].end + .05, 2))
        c['duration'] = .8; c['back'] = False; c['path'] = [[.5, .5], [.3, .4]]
        w.cameras.append(c)
        w.add_sticker('Arrow')
        cls.sticker = st = [o for o in w.visible_titles() if o.get('kind') == 'sticker'][0]
        st['drawing'] = 'Hand: outline'
        w.place_hand_sticker(st)
        w._scene_cache = {}; w.__dict__.pop('_memo', None)

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def run_dialog(self, act):
        w = self.w
        real = QDialog.exec

        def fake(dialog):
            if hasattr(dialog, 'moves'):
                act(dialog)
                return QDialog.DialogCode.Accepted
            return QDialog.DialogCode.Rejected
        QDialog.exec = fake
        try:
            w.open_hand_paths()
        finally:
            QDialog.exec = real

    def test_a_every_way_in_time_order(self):
        rows = self.w.hand_path_rows()
        kinds = [r['kind'] for r in rows]
        self.assertIn('motion', kinds); self.assertIn('sticker', kinds)
        self.assertEqual(kinds.count('element'), 4)
        starts = [r['times'][0] for r in rows]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(r.get('who') == 'Writing hand' for r in rows))
        self.assertTrue(all(r.get('hand') is not None for r in rows))
        motion = next(r for r in rows if r['kind'] == 'motion')
        self.assertTrue(motion['locked'])
        nxt = next(r for r in rows if r['kind'] == 'element' and r['k'] == 1 and r['which'] == 'in')
        self.assertTrue(nxt['movable_start'])                 # the Hand motion left the hand there

    def test_b_dragging_the_green_dot_moves_the_hand_motion_end(self):
        def act(d):
            i = next(i for i, m in enumerate(d.moves) if m['kind'] == 'element' and m['k'] == 1 and m['which'] == 'in')
            d.list.setCurrentRow(i)
            W, H = d.moves[i]['size']
            d.canvas.a = (.8 * W, .2 * H)
        self.run_dialog(act)
        self.assertEqual(self.clip['path'][-1], [.8, .2])

    def test_c_sticker_keyframes_are_kept(self):
        def act(d):
            i = next(i for i, m in enumerate(d.moves) if m['kind'] == 'sticker' and m['which'] == 'in')
            d.list.setCurrentRow(i)
            d.canvas.keys = [(.5, .3)]
        self.run_dialog(act)
        self.assertEqual([tuple(k) for k in self.sticker['hand_in_path']], [(.5, .3)])

    def test_d_strip_chooses(self):
        from glide_path_dialog import HandStrip
        rows = [dict(times=(0., 1.), kind='element'), dict(times=(2., 3.), kind='motion', who='Left hand')]
        s = HandStrip(rows); s.resize(600, 80)
        self.assertEqual(s.hands, ['Writing hand', 'Left hand'])
        got = []
        s.chosen = got.append
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        p = s._bar(1).center()
        s.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(p), QPointF(p),
                                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(got, [1])


if __name__ == '__main__':
    unittest.main()
