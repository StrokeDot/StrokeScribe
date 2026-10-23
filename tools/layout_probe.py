"""Which control makes a right-panel page wider than its column? (diagnostic)

Replays test_inspector_scene_switch (narrow panel, sections opened as the test opens
them) and prints, for every overflow, the widgets whose right edge is furthest out.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')


def main():
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    from app import Window
    from studio_workspace import TABS
    from ui_sections import Section, reveal
    w = Window(); w.resize(1490, 890); w.show(); app.processEvents()
    out = []

    def report(tag, area):
        content = area.widget()
        rows = []
        for child in content.findChildren(QWidget):
            if not child.isVisible():
                continue
            x = child.mapTo(content, QPoint(0, 0)).x()
            need = max(child.minimumWidth(), child.minimumSizeHint().width())
            rows.append((x + need, x, need, type(child).__name__, child.objectName(),
                         (getattr(child, 'text', lambda: '')() if hasattr(child, 'text') else '')[:30]))
        rows.sort(reverse=True)
        out.append(f'{tag}: content {content.width()} viewport {area.viewport().width()} '
                   f'content min {content.minimumSizeHint().width()}')
        for r in rows[:10]:
            out.append(f'    right={r[0]} x={r[1]} min={r[2]} {r[3]} {r[4]!r} {r[5]!r}')

    for state in ('closed', 'open'):
        if state == 'open':
            for s in w.findChildren(Section):
                s.set_expanded(True)
        for win in ((1040, 768), (1490, 890)):
            w.resize(*win); app.processEvents()
            for right in (270, 330):
                split = w.workspace_splitter
                split.moveSplitter(split.width() - right, 2); app.processEvents()
                for image in (False, True):
                    w.is_image_artwork = (lambda v=image: v); w.sync_workspace(); app.processEvents()
                    for name, page in (('animation', TABS['animation']), ('source', TABS['source']),
                                       ('hand', TABS['hand'])):
                        area = w.inspector_tabs.widget(page)
                        w.inspector_tabs.setCurrentIndex(page); app.processEvents()
                        if area.widget().width() > area.viewport().width() + 2:
                            report(f'{state} {win} right={right} image={image} {name}', area)
    print('\n'.join(out) or 'no overflow')
    w.close()


if __name__ == '__main__':
    main()
