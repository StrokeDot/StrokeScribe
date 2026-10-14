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
window.source_type.setCurrentIndex(0)
window.resize(1100,740)
snapshot('studio-compact.png')
window.close()
print('Generated four original Studio interface screenshots:', out)

# Inline review without accessing a local Windows filesystem.
import base64
from PySide6.QtCore import QBuffer,QIODevice
from PySide6.QtGui import QImage
preview=QImage(str(out/'studio-animation.png')).scaledToWidth(1200)
buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);preview.save(buffer,'PNG')
print('STUDIO_REVIEW_BASE64='+base64.b64encode(bytes(buffer.data())).decode())
