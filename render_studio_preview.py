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

for theme_name in ('dark','light'):
    window.apply_theme(theme_name)
    window.resize(1490,890)
    window.inspector_tabs.setCurrentIndex(0)
    window.slider.setValue(450)
    snapshot(f'studio-{theme_name}-animation.png')
    window.inspector_tabs.setCurrentIndex(1)
    snapshot(f'studio-{theme_name}-hand.png')
    window.inspector_tabs.setCurrentIndex(2)
    snapshot(f'studio-{theme_name}-export.png')
    window.inspector_tabs.setCurrentIndex(0)
    window.set_busy('Preparing your drawing',62,'Planning the brush route…')
    snapshot(f'studio-{theme_name}-loading.png')
    window.clear_busy()
    window.source_type.setCurrentIndex(1)
    snapshot(f'studio-{theme_name}-image-import.png')
    window.source_type.setCurrentIndex(0)
    window.resize(1100,740)
    snapshot(f'studio-{theme_name}-compact.png')
# Hand with a smaller artwork: the hand must not be cut off.
window.apply_theme('dark')
window.resize(1490,890)
window.artwork_size.setValue(50)
window.handsize.setValue(.75)
window.slider.setValue(980)
snapshot('studio-dark-artwork-50.png')
window.artwork_size.setValue(100)
# Keep the original file names for older review scripts.
import shutil
shutil.copy(out/'studio-dark-animation.png',out/'studio-animation.png')
# Create Image (AI) window, as on a PC with a 16 GB graphics card.
from ai_models import Hardware
from create_image_dialog import CreateImageDialog
for theme_name in ('dark','light'):
    window.apply_theme(theme_name)
    dialog=CreateImageDialog(window,str(Path('samples/drawing.svg').resolve()),None,
                             hardware=Hardware('NVIDIA GeForce RTX 4070 Ti SUPER',16.,32.,True))
    dialog.image_path=None
    dialog.set_task('generate')
    dialog.show(); app.processEvents()
    dialog.grab().save(str(out/f'create-image-{theme_name}.png'))
    dialog.set_task('lineart'); app.processEvents()
    dialog.grab().save(str(out/f'create-image-lineart-{theme_name}.png'))
    dialog.close()
window.apply_theme('dark')
# Setup & system check window, with the real checks of the build machine.
import preflight
from setup_wizard import SetupDialog
setup=SetupDialog(window,auto_check=False)
setup.show_results(preflight.system_info(),preflight.run_checks('balanced'))
setup.show(); app.processEvents()
if not setup.grab().save(str(out/'setup-window.png')):
    raise RuntimeError('Unable to save setup window screenshot')
setup.close()
window.close()
print('Generated original Studio interface screenshots:', out)

# Inline review without accessing a local Windows filesystem.
import base64
from PySide6.QtCore import QBuffer,QIODevice
from PySide6.QtGui import QImage
preview=QImage(str(out/'studio-dark-animation.png')).scaledToWidth(1200)
buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);preview.save(buffer,'PNG')
print('STUDIO_REVIEW_BASE64='+base64.b64encode(bytes(buffer.data())).decode())
