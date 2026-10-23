"""Diagnostics: the hand cut by "Ink on the page", and the move-in hand out of step in
the whole video (a review aid, not a test).

    python tools/sync_probe.py OUTPUT_FOLDER

Hands are pure green so they can be measured. Writes sync.txt and a few PNGs.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
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
    log = []

    def settle(ms=50):
        for _ in range(3):
            app.processEvents()
        QTest.qWait(ms)

    def arr(frame):
        q = frame.convertToFormat(QImage.Format.Format_RGBA8888)
        a = np.frombuffer(q.constBits(), np.uint8, q.bytesPerLine() * q.height()).reshape(q.height(), -1)
        return a[:, :q.width() * 4].reshape(q.height(), q.width(), 4).copy()

    def green(a):
        return (a[..., 1] > 200) & (a[..., 0] < 60) & (a[..., 2] < 60) & (a[..., 3] > 200)

    def box(mask):
        ys, xs = np.nonzero(mask)
        return None if not len(xs) else (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))

    # Pictures: a book page (transparent around it), a portrait on paper, a diary.
    page = Image.new('RGBA', (900, 600), (0, 0, 0, 0))
    ImageDraw.Draw(page).rectangle((120, 60, 780, 560), fill=(196, 160, 110, 255), outline=(90, 60, 30, 255), width=8)
    page.save(tmp / 'page.png')
    portrait = Image.new('RGB', (500, 600), (230, 220, 200))
    d = ImageDraw.Draw(portrait)
    d.ellipse((150, 120, 350, 380), outline=(30, 30, 30), width=8, fill=(120, 110, 100))
    d.rectangle((120, 380, 380, 560), outline=(20, 20, 20), width=8, fill=(90, 80, 70))
    portrait.save(tmp / 'portrait.png')
    diary = Image.new('RGBA', (800, 560), (0, 0, 0, 0))
    ImageDraw.Draw(diary).rectangle((60, 40, 740, 520), fill=(170, 120, 70, 255), outline=(60, 40, 20, 255), width=10)
    diary.save(tmp / 'diary.png')
    hand = QImage(220, 340, QImage.Format.Format_ARGB32_Premultiplied); hand.fill(QColor(0, 255, 0))
    hand_path = tmp / 'green hand.png'; hand.save(str(hand_path))

    w = Window(); w.resize(1600, 1000); w.show(); settle(200)
    w.set_hand(hand, 'probe hand')
    w.handsize.setValue(.8)

    def add(path, placement, same_spot=False):
        w.image_detail.setCurrentText('Low')
        if placement == 'replace':
            w.request_artwork(str(path), kind='image', placement='replace')
        else:
            w.new_element('file', same_spot=same_spot, path=str(path))
        if w.builder:
            w.builder.wait(180000)
        settle(300)

    add(tmp / 'page.png', 'replace')
    w.entrance.setCurrentText('Pop in'); w.duration.setValue(1.)
    add(tmp / 'portrait.png', 'add', same_spot=True)                 # + On this page
    w.paint_hand.setCurrentText(tools_kit.PAINT_SAME)
    w.image_animation.setCurrentText('Paint Only'); w.image_duration.setValue(3.)
    w.artwork_size.setValue(81)
    settle(200)
    k_portrait = w.scene_index
    log.append(f'elements so far: {len(w.scenes)}, portrait is element {k_portrait + 1}, '
               f'drawn over the page: {w.drawn_over(k_portrait)}')

    width = w.PREVIEW_WIDTH

    def element_frames(fracs):
        w.preview_scope.setCurrentIndex(0); settle(100); w.refresh(); settle(100)
        return [w.render_view(f, width) for f in fracs]

    # 1. Ink on the page: is the hand cut?
    fracs = [.2, .4, .6, .8]
    for ink in (False, True):
        if w.ink_on.isChecked() != ink:
            w.ink_on.setChecked(ink); settle(200)
        w._look_preview = False; w.refresh(); settle(100)
        frames = element_frames(fracs)
        counts = []
        for f, frame in zip(fracs, frames):
            a = arr(frame)
            g = green(a)
            counts.append((int(g.sum()), box(g)))
            frame.save(str(out / f'ink-{"on" if ink else "off"}-{int(f * 100)}.png'))
        log.append(f'ink {"on " if ink else "off"} element view, hand pixels at {fracs}: '
                   + '; '.join(f'{c} box={b}' for c, b in counts))
    # Whole video, same element.
    w.preview_scope.setCurrentIndex(1); settle(200); w.refresh(); settle(200)
    h = round(width * w._view['ratio'])
    for ink in (False, True):
        w.ink_on.setChecked(ink); settle(200); w._look_preview = False; w.refresh(); settle(100)
        counts = []
        for f in fracs:
            frame = w.whole_frame_at('scene', k_portrait, f, width, h)
            g = green(arr(frame)); counts.append((int(g.sum()), box(g)))
            frame.save(str(out / f'whole-ink-{"on" if ink else "off"}-{int(f * 100)}.png'))
        log.append(f'ink {"on " if ink else "off"} whole video, hand pixels: '
                   + '; '.join(f'{c} box={b}' for c, b in counts))
    w.ink_on.setChecked(False); settle(100)

    # 2. Move in: the diary slides in from the bottom carried by the hand.
    add(tmp / 'diary.png', 'add')
    k_diary = w.scene_index
    w.entrance.setCurrentText('Slide in from the bottom'); w.entrance_part.setCurrentIndex(0)
    w.duration.setValue(2.)
    w.set_move_hand(str(hand_path)); w.move_hand.setChecked(True)
    settle(200)
    fracs = [.1, .25, .4, .55, .7]
    elem = element_frames(fracs)
    w.preview_scope.setCurrentIndex(1); settle(200); w.refresh(); settle(200)
    h = round(width * w._view['ratio'])
    whole = [w.whole_frame_at('scene', k_diary, f, width, h) for f in fracs]
    log.append(f'diary is element {k_diary + 1}')
    for f, a_frame, b_frame in zip(fracs, elem, whole):
        rows = []
        for name, frame in (('element', a_frame), ('whole', b_frame)):
            a = arr(frame)
            g = green(a)
            brown = (a[..., 3] > 200) & ~g & (a[..., 0] > 120) & (a[..., 0] < 200) & (a[..., 2] < 110)
            gb, bb = box(g), box(brown)
            gap = (gb[1] - bb[3]) if gb and bb else None
            rows.append(f'{name}: picture {bb} hand {gb} (hand top - picture bottom = {gap})')
            frame.save(str(out / f'move-{name}-{int(f * 100)}.png'))
        log.append(f'move-in f={f}: ' + ' | '.join(rows))
    (out / 'sync.txt').write_text('\n'.join(log) + '\n', encoding='utf-8')
    print('\n'.join(log))
    w.close(); settle()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'sync-probe'))
