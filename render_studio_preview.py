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
    window.inspector_tabs.setCurrentIndex(3)
    snapshot(f'studio-{theme_name}-export.png')
    window.inspector_tabs.setCurrentIndex(2)
    snapshot(f'studio-{theme_name}-sound.png')
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
# Line editing: a line clicked on the preview, slowed down, with a pause.
window.apply_theme('dark'); window.resize(1490,890)
window.inspector_tabs.setCurrentIndex(0)
window.slider.setValue(1000); app.processEvents()
_lines=window.preview_lines()
if _lines:
    _i=min(2,len(_lines)-1); _mid=_lines[_i][len(_lines[_i])//2]
    window.click_preview(*_mid)
    window.line_pace.setCurrentText('Slow'); window.set_line_pace()
    window.line_pause.setValue(1.)
    window.pen_ease.setCurrentIndex(1)
snapshot('line-editing.png')
# Painting hand: the built-in hand draws, then the built-in paint brush paints.
import tools_kit as _tk
from engine import render as _render
from PIL import ImageFilter as _IF
_bx0,_by0,_bx1,_by1=_d.bounds
_cw,_ch=max(2,round(_bx1-_bx0)),max(2,round(_by1-_by0))
_lines=_pil(_render(_d,1.,_cw,_ch,1.,None)).convert('RGBA')
_fill=_lines.getchannel('A').filter(_IF.MaxFilter(21)).filter(_IF.GaussianBlur(3))
_grad=_Image.linear_gradient('L').rotate(90).resize((_cw,_ch))
_col=_Image.merge('RGB',(_grad.point(lambda v:250-v//3),_grad.point(lambda v:150+v//4),_grad.point(lambda v:60+v*3//4)))
_colour=_Image.new('RGBA',(_cw,_ch),(0,0,0,0)); _colour.paste(_col,(0,0),_fill)
_colour.alpha_composite(_lines)
from PySide6.QtGui import QImage as _QI
_cq=_QI(_colour.tobytes(),_cw,_ch,_QI.Format.Format_RGBA8888).copy()
_hand=_tk.builtin_image('hand')
_brush=_tk.painting_hand(dict(paint_hand=_tk.PAINT_BRUSH,paint_hand_size=30,handsize=.75,ax=.08,ay=.13),_hand)
_o=dict(width=640,height=360,duration=2.,fade_duration=.4,hold_duration=.4,final_image=_cq,thickness=1.,
        hand=_hand,hand_scale=.75,anchor=(.08,.13),reveal_mode='adaptive',brush_width=.14,painting_hand=_brush,
        stroke_spacing=.55,artwork_scale=.8)
_frames=[]
for _i in range(48):
    _f=_pil(_compose(_d,_i/47,_o)).convert('RGBA')
    _bg=_Image.new('RGBA',_f.size,(255,255,255,255)); _bg.alpha_composite(_f)
    _frames.append(_bg.convert('RGB'))
_frames[0].save(str(out/'painting-hand.gif'),save_all=True,append_images=_frames[1:]+[_frames[-1]]*6,
                duration=90,loop=0)
# Scenes: two scenes, the whole video previewed during the camera move.
from engine import import_svg as _imp
window.apply_theme('dark'); window.resize(1490,890)
window.add_scene()
window.set_drawing(_imp('samples/arthur-headset-traced.svg'))
window.scene_list.setCurrentRow(0)
window.preview_scope.setCurrentIndex(1)
_lengths,_joins=window.scene_timeline()
window.slider.setValue(round(1000*(_lengths[0]+_joins[0]*.5)/(sum(_lengths)+sum(_joins))))
snapshot('scenes.png')
# A GIF of each transition between the two finished scenes.
from scenes import transition_frame as _tf, TRANSITIONS as _TR
_a=window.preview_scene(0,640,360); _b=window.preview_scene(1,640,360)
_fa=_compose(_a[0],1.,_a[1],_a[3]); _fb=_compose(_b[0],0.,_b[1],_b[3])   # the next scene starts empty
_frames=[]
for _kind in ('Camera move','Pan right','Zoom in'):
    for _i in range(16):
        _img=_tf(_fa,_fb,_kind,_i/15) if _i else _fa
        _f=_pil(_img).convert('RGBA'); _bg=_Image.new('RGBA',_f.size,(255,255,255,255)); _bg.alpha_composite(_f)
        _frames.append(_bg.convert('RGB'))
    _frames+= [_frames[-1]]*4
# After the last move, the next scene is drawn.
for _i in range(1,13):
    _f=_pil(_compose(_b[0],_i/12*.6,_b[1],_b[3])).convert('RGBA'); _bg=_Image.new('RGBA',_f.size,(255,255,255,255))
    _bg.alpha_composite(_f); _frames.append(_bg.convert('RGB'))
_frames[0].save(str(out/'scene-transitions.gif'),save_all=True,append_images=_frames[1:],duration=70,loop=0)
window.preview_scope.setCurrentIndex(0)
# Export -> Hand only: the preview shows the drawing faintly under the hand.
window.export_layers.setCurrentText('Hand only (no drawing)')
window.inspector_tabs.setCurrentIndex(3)
window.slider.setValue(550)
snapshot('hand-only.png')
window.export_layers.setCurrentText('Drawing and hand')
window.inspector_tabs.setCurrentIndex(0)
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
