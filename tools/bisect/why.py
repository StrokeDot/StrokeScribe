"""Why does pre-render make no frames? Run inside a StrokeScribe checkout."""
import os, sys, tempfile, traceback
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['STROKESCRIBE_PREVIEW_CACHE'] = tempfile.mkdtemp()
sys.path.insert(0, os.getcwd())
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from app import Window
from engine import import_svg
w = Window(); w.show()
w.duration.setValue(1.); w.add_scene()
w.set_drawing(import_svg(Path('samples') / 'arthur-headset-traced.svg'))
w.duration.setValue(1.); w.preview_scope.setCurrentIndex(1)
for _ in range(5): app.processEvents()
view = getattr(w, '_view', None)
print('view', None if view is None else {k: v for k, v in view.items() if k in ('all', 'length', 'token')})
print('token now', w._view_token())
print('visible', w.isVisible(), 'playing', w.playing, 'busy', w.busy, 'preparing', w._preparing,
      'builder', bool(w.builder and w.builder.isRunning()), 'worker', bool(w.worker and w.worker.isRunning()))
try:
    seg = w.segment_at(0); print('segment_at(0)', seg[1:])
    f = w.render_segment(seg[3], seg[4], seg[1], seg[2], w.PREVIEW_WIDTH); print('render ok', f.width(), f.height())
except Exception:
    traceback.print_exc()
for _ in range(10): w.prerender_step()
print('ready', w.ready_frames())
