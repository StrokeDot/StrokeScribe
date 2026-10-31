"""Contact sheets of the whole-video preview with the screen hand (exp.149)."""
import os, sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else 'probe-out'); OUT.mkdir(parents=True, exist_ok=True)
from unittest import mock
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QImage, QPainter, QColor, QFont
for n in ('question', 'warning', 'information', 'critical'):
    mock.patch.object(QMessageBox, n, return_value=QMessageBox.StandardButton.Discard).start()
app = QApplication([])
from app import Window
from engine import import_svg
w = Window(); w.resize(1500, 900); w.show(); app.processEvents()
w.set_drawing(import_svg(HERE / 'samples' / 'drawing.svg'))
w.add_scene(); w.set_drawing(import_svg(HERE / 'samples' / 'arthur-headset-traced.svg'))
w.hand_rest.setChecked(True); w.hand_rest_travel.setValue(.8)
w.preview_scope.setCurrentIndex(1); app.processEvents()
z = w.add_camera_clip('Zoom in', at=1.0); z['to'] = (2.2, .4, .4)
w.select_camera(None); w.refresh(); app.processEvents()


def sheet(name):
    total = w.timeline_layout().total
    print(name, 'total', total, [(i.start, i.length, i.track) for i in w.timeline_layout().items], flush=True)
    frames = []
    N = 24
    for i in range(N):
        w.position = i / (N - 1); w.refresh(); app.processEvents()
        f = w.canvas.frame
        img = QImage(f.size(), QImage.Format.Format_ARGB32_Premultiplied); img.fill(QColor('white'))
        p = QPainter(img); p.drawImage(0, 0, f)
        if w.canvas.titles_frame is not None: p.drawImage(0, 0, w.canvas.titles_frame)
        if w.canvas.rest_frame is not None: p.drawImage(0, 0, w.canvas.rest_frame)
        p.setPen(QColor('red')); p.setFont(QFont('Sans', 22))
        p.drawText(10, 30, f'{w.position * total:.2f}s rest={w.canvas.rest_frame is not None}')
        p.end()
        frames.append(img.scaledToWidth(480))
    cols = 4; rows = (N + cols - 1) // cols
    fw, fh = frames[0].width(), frames[0].height()
    out = QImage(cols * fw, rows * fh, QImage.Format.Format_RGB32); out.fill(QColor('gray'))
    p = QPainter(out)
    for i, f in enumerate(frames):
        p.drawImage((i % cols) * fw, (i // cols) * fh, f)
    p.end()
    out.save(str(OUT / f'{name}.png'))


sheet('sequential')
w.place_element(1, 3.0, 1)        # element 2 on Track 2, overlapping
app.processEvents()
sheet('tracks')
print('done', flush=True)
