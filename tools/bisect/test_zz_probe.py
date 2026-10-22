import os, tempfile, unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
APP = QApplication.instance() or QApplication([])

class Probe(unittest.TestCase):
    def test_probe(self):
        os.environ['STROKESCRIBE_PREVIEW_CACHE'] = tempfile.mkdtemp()
        from app import Window
        from engine import import_svg
        w = Window(); w.show()
        w.duration.setValue(1.); w.add_scene()
        w.set_drawing(import_svg(Path('samples') / 'arthur-headset-traced.svg'))
        w.duration.setValue(1.); w.preview_scope.setCurrentIndex(1)
        APP.processEvents()
        view = getattr(w, '_view', None)
        print('\nPROBE mouse', QApplication.mouseButtons(), 'modal', APP.activeModalWidget(),
              'visible', w.isVisible(), 'playing', w.playing, 'busy', w.busy, 'preparing', w._preparing,
              'view', view is not None, 'token ok', view is not None and view['token'] == w._view_token(),
              'cache', w.segment_cache.folder if hasattr(w.segment_cache, 'folder') else None,
              'env', os.environ.get('STROKESCRIBE_PREVIEW_CACHE'), flush=True)
        for _ in range(5): w.prerender_step()
        print('PROBE ready', w.ready_frames(), flush=True)
        w.playing = False; w.close()
