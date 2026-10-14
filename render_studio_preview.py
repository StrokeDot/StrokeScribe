"""Create visual review screenshots for the original StrokeScribe Studio UI."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app import Window

app=QApplication.instance() or QApplication([])
out=Path('samples/studio-preview')
out.mkdir(parents=True,exist_ok=True)
window=Window()
window.resize(1490,890)
window.show()
app.processEvents()

def snapshot(name):
    app.processEvents()
    if not window.grab().save(str(out/name)):
        raise RuntimeError('Unable to save Studio screenshot: '+name)

snapshot('studio-animation.png')
window.inspector_tabs.setCurrentIndex(1)
snapshot('studio-hand.png')
window.inspector_tabs.setCurrentIndex(2)
snapshot('studio-export.png')
window.inspector_tabs.setCurrentIndex(0)
window.source_type.setCurrentIndex(1)
snapshot('studio-image-import.png')
window.close()
print('Generated four original Studio interface screenshots:', out)
