"""Remote review screenshots with isolated settings; no models or network."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
import ai_engine
from ai_models import Hardware
from create_image_dialog import CreateImageDialog
from model_updates_live import ModelState, RemoteRevision
from PySide6.QtTest import QTest
import theme

app=QApplication.instance() or QApplication([])
app.setStyle('Fusion')
# The offscreen Qt platform on Windows does not enumerate native fonts.
# Register existing OS fonts explicitly for screenshots only.
font_family='DejaVu Sans'
if os.name=='nt':
    fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    families=[]
    for filename in ('segoeui.ttf','segoeuib.ttf','arial.ttf','arialbd.ttf','seguisym.ttf'):
        font_id=QFontDatabase.addApplicationFont(str(fonts/filename))
        if font_id>=0:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    if not families:
        raise RuntimeError('Headless screenshot font registration failed')
    font_family=families[0]
font=QFont(font_family,10)
if not QFontMetrics(font).inFont('A'):
    raise RuntimeError('Screenshot font cannot render Latin text')
app.setFont(font)
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
    from ai_models import QWEN_EDIT, FLUX2_KLEIN, FLUX2_DEV
    examples=(
        ModelState(QWEN_EDIT.id,QWEN_EDIT.name,QWEN_EDIT.maker,'Image editing',
                   'q4','GGUF Q4','update_available','Illustrative publisher checksum difference',
                   True,RemoteRevision('a'*64,13244758624),QWEN_EDIT.variants[2].diffusion),
        ModelState(FLUX2_KLEIN.id,FLUX2_KLEIN.name,FLUX2_KLEIN.maker,'Image generation',
                   'bf16','BF16','up_to_date','Illustrative matching weights',True),
        ModelState(FLUX2_DEV.id,FLUX2_DEV.name,FLUX2_DEV.maker,'Image generation',
                   'q3','GGUF Q3','not_installed','Illustrative uninstalled model',False),
    )
    with patch('model_updates_live.inspect_models', return_value=examples):
        dialog.check_updates_button.click()
        for _ in range(150):
            app.processEvents()
            if dialog.live_update_worker is None: break
            QTest.qWait(20)
    dialog.resize(1680,1080);app.processEvents()
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
