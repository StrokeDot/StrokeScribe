"""Remote review screenshots with isolated settings; no models or network."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
import ai_engine
from ai_models import Hardware
from create_image_dialog import CreateImageDialog
import theme

app=QApplication.instance() or QApplication([])
app.setStyle('Fusion')
app.setFont(QFont('Segoe UI' if os.name=='nt' else 'DejaVu Sans',10))
out=Path('samples/image-generator-updates')
out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'STROKESCRIBE_CONFIG_DIR':tmp}):
    settings=ai_engine.load_settings();settings['root']=str(Path(tmp)/'Example AI engine')
    ai_engine.save_settings(settings)
    theme.set_current('dark')
    app.setStyleSheet(theme.stylesheet('dark',Path('assets').resolve()))
    dialog=CreateImageDialog(hardware=Hardware('NVIDIA GeForce RTX 4070 Ti SUPER',16,64,True))
    # The preview demonstrates the UI only, not installation or inference.
    dialog.engine_label.setText('AI engine: demonstration setup  •  Folder: example AI engine folder')
    dialog.install_button.hide()
    dialog.download_button.hide()
    dialog.resize(1200,900);dialog.show();app.processEvents()
    dialog.grab().save(str(out/'create-image-drawer-closed.png'))
    dialog.check_updates_button.click();dialog.resize(1680,1080);app.processEvents()
    dialog.grab().save(str(out/'create-image-drawer-open.png'))
    dialog.resize(1000,740);app.processEvents()
    dialog.grab().save(str(out/'create-image-drawer-compact.png'))
    dialog.resize(1680,1080);app.processEvents()
    dialog.manage_models_button.click();app.processEvents()
    dialog.model_manager.grab().save(str(out/'manage-ai-models.png'))
    dialog.model_manager.close()
    dialog.close()
# Small preview via CI logs for remote visual inspection.
import base64
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
for name in ('create-image-drawer-open.png','create-image-drawer-compact.png'):
    image=QImage(str(out/name))
    image=image.scaledToWidth(1300 if 'open' in name else 1000)
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
    print('DRAWER_REVIEW_'+('WIDE' if 'open' in name else 'COMPACT')+'='+base64.b64encode(bytes(buffer.data())).decode('ascii'))
print('Saved UI review screenshots to '+str(out))
