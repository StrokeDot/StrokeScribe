"""Diagnostics for the whole-video preview (a review aid, not a test).

    python tools/play_probe.py OUTPUT_FOLDER

Builds a small project like a real one: a page drawn then painted, then a second
element whose lines slide in from the bottom carried by a move-in hand and are then
painted. The drawing hand, painting hand and move-in hand are pure green, so every
frame can be checked for "is a hand there?". Then:

1. hand.txt  - every frame of the whole video: element, part (move / draw / paint /
   hold), green pixels. Frames where a hand is expected but missing are marked.
2. play.txt  - Pre-render, then Play: how many frames came ready-made and how long
   each frame took (what decides whether playback is smooth).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')


def main(out):
    import numpy as np
    from PIL import Image, ImageDraw
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    os.environ['STROKESCRIBE_PREVIEW_CACHE'] = str(tmp / 'cache')
    from app import Window
    import tools_kit

    def settle(ms=50):
        for _ in range(3):
            app.processEvents()
        QTest.qWait(ms)

    def picture(name, colours):
        path = tmp / name
        im = Image.new('RGB', (640, 420), (236, 228, 212))
        d = ImageDraw.Draw(im)
        for i, c in enumerate(colours):
            d.rectangle((40 + i * 190, 60, 200 + i * 190, 360), outline=(30, 30, 30), width=6, fill=c)
        d.ellipse((240, 120, 400, 300), outline=(20, 20, 20), width=5, fill=(150, 90, 160))
        im.save(path)
        return path

    green = QImage(70, 110, QImage.Format.Format_ARGB32_Premultiplied); green.fill(QColor(0, 255, 0))
    green_path = tmp / 'green hand.png'; green.save(str(green_path))

    w = Window(); w.resize(1600, 1000); w.show(); settle(200)
    w.set_hand(green, 'probe hand')
    log = []

    def add(path, placement):
        w.image_detail.setCurrentText('Low')
        w.request_artwork(str(path), kind='image', placement=placement)
        if w.builder:
            w.builder.wait(180000)
        settle(300)

    add(picture('page.png', [(180, 120, 70), (90, 120, 160), (200, 170, 60)]), 'replace')
    w.duration.setValue(1.5); w.image_duration.setValue(2.0)
    w.paint_hand.setCurrentText(tools_kit.PAINT_SAME)
    add(picture('second.png', [(160, 60, 60), (70, 140, 120), (120, 100, 200)]), 'add')
    w.duration.setValue(1.5); w.image_duration.setValue(2.0)
    w.paint_hand.setCurrentText(tools_kit.PAINT_SAME)
    w.reveal_mode.setCurrentText('Left to right (columns)')
    w.entrance.setCurrentText('Slide in from the bottom')
    w.entrance_part.setCurrentIndex(1)                      # only the lines, then paint
    w.set_move_hand(str(green_path)); w.move_hand.setChecked(True)
    settle(200)
    log.append(f'elements: {len(w.scenes)}  version: {__import__("version").APP_VERSION}')
    w.preview_scope.setCurrentIndex(1); settle(300)          # Whole video
    w.refresh(); settle(200)
    view = w._view
    log.append(f'whole video: {view["length"]:.2f} s, frames {w.frame_index(1.)[1] + 1}')

    # 1. Is a hand there, frame by frame?
    rows = []
    count = w.frame_index(1.)[1] + 1
    for i in range(count):
        segment, local, frames, where, k = w.segment_at(i)
        began = time.perf_counter()
        try:
            frame = w.render_segment(where, k, local, frames, w.PREVIEW_WIDTH)
        except Exception as exc:
            rows.append(f'{i:4} {where:5} {k} ERROR {exc!r}'); continue
        spent = time.perf_counter() - began
        q = frame.convertToFormat(QImage.Format.Format_RGBA8888)
        a = np.frombuffer(q.constBits(), np.uint8, q.bytesPerLine() * q.height()).reshape(q.height(), -1)
        a = a[:, :q.width() * 4].reshape(q.height(), q.width(), 4)
        g = int(((a[..., 1] > 200) & (a[..., 0] < 60) & (a[..., 2] < 60)).sum())
        part = ''
        if where == 'scene':
            opts = w.preview_scene(k, w.PREVIEW_WIDTH, round(w.PREVIEW_WIDTH * view['ratio']))[1]
            parts = w.stage_parts(opts)
            whole = sum(v for _, v in parts) or 1
            t = local / max(1, frames) * whole
            acc = 0.
            for key, v in parts:
                if t < acc + v or key == parts[-1][0]:
                    part = f'{key} {t - acc:.2f}/{v:.2f}'; break
                acc += v
        expect = where == 'scene' and part.split(' ')[0] in ('move', 'draw', 'paint')
        mark = '  <-- NO HAND' if expect and g == 0 else ''
        rows.append(f'{i:4} {where:5} {k} {part:18} green={g:6} {spent * 1000:6.0f} ms{mark}')
    missing = sum(1 for r in rows if 'NO HAND' in r)
    (out / 'hand.txt').write_text(f'frames without a hand where one is expected: {missing}\n' +
                                  '\n'.join(rows) + '\n', encoding='utf-8')
    log.append(f'hand check: {missing} frames without a hand where one is expected (see hand.txt)')

    # 2. Pre-render, then play.
    w.segment_cache.forget_memory(); w.segment_cache.clear_disk(); w.clear_frames()
    w.refresh(); settle()
    began = time.perf_counter()
    w.prerender_whole()
    steps = 0
    while w._prerender_all and steps < count * 3:
        w.prerender_step(); steps += 1
    log.append(f'pre-render: {time.perf_counter() - began:.1f} s, ready {w.ready_frames()}')
    if getattr(w, 'prerender_dialog', None):
        w.prerender_dialog.reject()
    settle()
    misses = {'n': 0}
    real = w.render_segment

    def counted(*a, **k):
        misses['n'] += 1
        return real(*a, **k)
    w.render_segment = counted
    w.position = 0.; w.playing = True
    times = []
    for i in range(count):
        w.position = i / max(1, count - 1)
        t0 = time.perf_counter()
        w._playhead_only = True; w.refresh()
        times.append(time.perf_counter() - t0)
    w.playing = False
    times.sort()
    log.append(f'play: {count} frames, drawn again {misses["n"]} (the rest ready-made); '
               f'per frame median {times[len(times) // 2] * 1000:.0f} ms, '
               f'90% {times[int(len(times) * .9)] * 1000:.0f} ms, worst {times[-1] * 1000:.0f} ms '
               f'(smooth at 30 fps needs < 33 ms)')
    (out / 'play.txt').write_text('\n'.join(log) + '\n', encoding='utf-8')
    print('\n'.join(log))
    w.close(); settle()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'probe'))
