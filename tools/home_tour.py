"""Screenshots of the Home screen and the timeline track headers (review aid, exp.107)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')


def main(out):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog
    app = QApplication.instance() or QApplication([])
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    os.environ['STROKESCRIBE_PROJECTS_FOLDER'] = str(tmp / 'StrokeScribe Projects')
    (tmp / 'StrokeScribe Projects').mkdir()
    from app import Window
    from engine import import_svg

    def settle(ms=120):
        for _ in range(3):
            app.processEvents()
        QTest.qWait(ms)

    w = Window(); w.resize(1600, 960); w.show(); settle(300)
    home = w.show_home(); settle()
    w.grab().save(str(out / '1-home-empty.png'))
    w.hide_home()
    w.set_drawing(import_svg(ROOT / 'samples' / 'drawing.svg')); settle(200)
    for name in ('Product launch', 'Science class - cells', 'Coffee shop ad', 'Wedding story'):
        target = str(tmp / 'StrokeScribe Projects' / (name + '.strokescribe'))
        with mock.patch.object(QFileDialog, 'getSaveFileName', return_value=(target, '')):
            w.save_project(save_as=True)
    # one without a preview (initials)
    (tmp / 'StrokeScribe Projects' / 'Old sketch.strokescribe').write_bytes(
        (tmp / 'StrokeScribe Projects' / 'Coffee shop ad.strokescribe').read_bytes())
    w.show_home(); settle(200)
    w.grab().save(str(out / '2-home-projects.png'))
    w.hide_home(); settle()
    # Track headers: three elements, one on Track 2, one hidden, track 1 muted.
    w.add_scene(); w.add_scene(); settle(200)
    w.preview_scope.setCurrentIndex(1); settle(200)
    try:
        w.place_element(1, 0.5, 1)
        w.toggle_element_flag(2, 'hide')
        w.toggle_track(0, 'mute')
    except Exception as exc:
        print('tracks:', exc)
    settle(300)
    t = w.stage_timeline
    t.grab().save(str(out / '3-track-headers.png'))
    t.grab().scaled(t.width() * 2, t.height() * 2).save(str(out / '4-track-headers-2x.png'))
    w.grab().save(str(out / '5-window-with-tracks.png'))
    print('done')
    w.close(); settle()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'tour'))
