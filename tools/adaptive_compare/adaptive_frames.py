"""Render Adaptive Hand Painting frames of the Arthur headset with one StrokeScribe checkout.

    python adaptive_frames.py REPO COLOR_PNG OUT
"""
import json, os, sys
from pathlib import Path
repo, color, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(repo)); os.chdir(repo)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
app = QApplication([])
from engine import import_svg
from color_reveal import render_color_timeline
drawing = import_svg(str(repo / 'samples' / 'arthur-headset-traced.svg'))
image = QImage(str(color))
hand = QImage(str(repo / 'assets' / 'default_hand.png'))
fractions = [round(.40 + i * .05, 2) for i in range(12)]
for i, f in enumerate(fractions):
    frame = render_color_timeline(drawing, f, 960, 540, duration=4, fade_duration=4, hold_duration=.6,
                                  final_image=image, hand=hand, hand_scale=.75, anchor=(.08, .13),
                                  reveal_mode='adaptive', brush_width=.14, painting_hand=hand,
                                  stroke_spacing=.55)
    frame.save(str(out / f'frame_{i:02d}.png'))
info = dict(strokes=len(drawing.strokes), points=sum(len(s.points) for s in drawing.strokes),
            ink=round(sum(s.length for s in drawing.strokes), 2), bounds=[round(b, 2) for b in drawing.bounds],
            fractions=fractions)
(out / 'info.json').write_text(json.dumps(info, indent=1))
print(json.dumps(info))
