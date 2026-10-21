"""Screenshots of every side panel, for reviewing the UI without a desktop.

    python tools/ui_shots.py OUTPUT_FOLDER

Opens the Studio at 2000 x 1124 (a common laptop window), shows each left and
right panel at a realistic width, imports a picture with a long file name and
presses Apply image settings, and saves PNGs plus report.txt. The report lists
any page whose contents are wider than its visible area, with the controls
that ask for the most width. Used by the Quick checks workflow on Windows.
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
    from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    from app import Window
    from studio_workspace import LEFT, TABS

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    report = []

    def settle(ms=60):
        for _ in range(3):
            app.processEvents()
        QTest.qWait(ms)
        app.processEvents()

    w = Window()
    w.resize(2000, 1124)
    w.show()
    settle(200)
    layout = w.sidebar_layout
    layout.widths['source'], layout.widths['inspector'] = 330, 400
    split = w.workspace_splitter

    def widest(area):
        rows = []
        for child in area.widget().findChildren(QWidget):
            if child.isVisible():
                need = child.minimumWidth() or child.minimumSizeHint().width()
                text = ''
                if hasattr(child, 'text'):
                    try:
                        text = str(child.text())[:40]
                    except Exception:
                        text = ''
                rows.append((need, type(child).__name__, text))
        rows.sort(reverse=True)
        return '; '.join(f'{n}px {t} {x!r}' for n, t, x in rows[:4])

    def check(name, area):
        content, view = area.widget().width(), area.viewport().width()
        status = 'OK' if content <= view + 1 else f'OVERFLOW by {content - view}px'
        report.append(f'{name:28} content {content:4} / visible {view:4}  {status}')
        if status != 'OK':
            report.append('    widest: ' + widest(area))

    def shot(name, side):
        settle()
        panel = split.widget(0 if side == 'left' else 2)
        panel.grab().save(str(out / f'{name}.png'))
        tabs = w.left_tabs if side == 'left' else w.inspector_tabs
        area = tabs.currentWidget()
        if isinstance(area, QScrollArea):
            check(name, area)
            # The bottom of long pages too (where clipping was reported).
            bar = area.verticalScrollBar()
            if bar.maximum() > 0:
                bar.setValue(bar.maximum())
                settle()
                panel.grab().save(str(out / f'{name}-bottom.png'))
                bar.setValue(0)

    for key in LEFT:
        w.show_left_panel(key)
        shot(f'left-{key}', 'left')
    for key in TABS:
        w.show_right_panel(key)
        shot(f'right-{key}', 'right')
    w.grab().save(str(out / 'window-panels-open.png'))

    # A picture with a long file name, then Apply image settings.
    try:
        from PIL import Image, ImageDraw
        folder = Path(tempfile.mkdtemp())
        picture = folder / 'ChatGPT_Image_Oct_20_2026_10_15_33_PM_with_a_long_name.png'
        image = Image.new('RGB', (640, 420), 'white')
        draw = ImageDraw.Draw(image)
        draw.ellipse((80, 60, 320, 300), outline='black', width=6, fill=(230, 180, 90))
        draw.rectangle((360, 120, 580, 360), outline='black', width=6, fill=(90, 150, 220))
        image.save(picture)
        w.image_detail.setCurrentText('Low')
        w.request_artwork(str(picture), kind='image', placement='replace')
        if w.builder:
            w.builder.wait(120000)
        settle(300)
        w.show_right_panel('source')
        shot('image-imported', 'right')
        w.rebuild_image()
        if w.builder:
            w.builder.wait(120000)
        settle(300)
        w.show_right_panel('source')
        shot('image-after-apply', 'right')
    except Exception as exc:                       # a review aid: report, never fail
        report.append(f'image import step failed: {exc!r}')

    w.show_right_panel('hand')
    shot('hand-after-image', 'right')
    w.grab().save(str(out / 'window.png'))
    (out / 'report.txt').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print('\n'.join(report))
    w.playing = False
    w.close()
    settle()
    return 0


if __name__ == '__main__':
    started = time.time()
    code = main(sys.argv[1] if len(sys.argv) > 1 else 'ui-shots')
    print(f'ui shots in {time.time() - started:.1f} s')
    sys.exit(code)
