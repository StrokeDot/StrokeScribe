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
# Library with a few items, and the pen-tip helper.
import os, tempfile, shutil as _sh
_lib_tmp=tempfile.mkdtemp()
os.environ['STROKESCRIBE_CONFIG_DIR']=_lib_tmp
import library
_settings=library.load_settings(); _settings['root']=str(Path(_lib_tmp)/'StrokeScribe Library'); library.save_settings(_settings)
_lib=library.Library()
_lib.add('images',Path('samples/drawing.svg'))
from PIL import Image as _Image, ImageDraw as _Draw
for _name,_col in (('sunset.png',(240,140,60)),('ocean.png',(40,120,200))):
    _im=_Image.new('RGB',(320,200),_col); _Draw.Draw(_im).ellipse((110,40,210,140),fill=(255,230,120))
    _p=Path(_lib_tmp)/_name; _im.save(_p); _lib.add('images',_p)
from hand_tip import find_tip
_lib.add('hands',Path('assets/default_hand.png'),tip=find_tip(_Image.open('assets/default_hand.png'))[:2])
from library_dialog import LibraryDialog, PenTipDialog
from PySide6.QtGui import QImage as _QImage
_d=LibraryDialog(window,'images',lambda *a:None); _d.show(); app.processEvents()
_d.grab().save(str(out/'library-images.png'))
_d.set_category('hands'); app.processEvents(); _d.grab().save(str(out/'library-hands.png')); _d.close()
_t=PenTipDialog(window,_QImage('assets/default_hand.png')); _t.show(); app.processEvents()
_t.grab().save(str(out/'pen-tip.png')); _t.close()
# Eraser preview GIFs (erase stage only) for both styles.
from frame_render import compose_frame as _compose
from export_job import builtin_eraser as _be
from eraser import ERASER_TIP as _tip
from adaptive_hand import pil_image as _pil
from engine import import_svg as _import
_d=_import('samples/drawing.svg')
for _mode in ('zigzag','lines'):
    _o=dict(width=640,height=360,duration=1.,fade_duration=.4,hold_duration=.5,final_image=None,thickness=1.,
            hand=None,hand_scale=.2,anchor=(.1,.1),reveal_mode='adaptive',brush_width=.14,painting_hand=None,
            stroke_spacing=.55,artwork_scale=1.,
            erase=dict(mode=_mode,seconds=3.,size=.08,image=_be(),anchor=_tip,width=.18))
    _frames=[]
    for _i in range(40):
        _f=_pil(_compose(_d,.25+.75*_i/39,_o)).convert('RGBA')
        _bg=_Image.new('RGBA',_f.size,(255,255,255,255)); _bg.alpha_composite(_f)
        _frames.append(_bg.convert('RGB'))
    _frames[0].save(str(out/f'eraser-{_mode}.gif'),save_all=True,append_images=_frames[1:]+[_frames[-1]]*5,
                    duration=80,loop=0)
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
