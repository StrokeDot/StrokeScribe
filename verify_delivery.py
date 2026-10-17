"""Produce reviewable exports and verify a ProRes decode, including alpha."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json, subprocess, time
from pathlib import Path
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from engine import import_svg, export_frames, encode_mov, render

app=QApplication([]); here=Path(__file__).parent; out=here/'test-output'
out.mkdir(exist_ok=True); d=import_svg(here/'samples/drawing.svg')
start=time.perf_counter(); folder=out/'sample-1080p'
count=export_frames(d,folder,duration=2,fps=24,workers=1)
render_seconds=time.perf_counter()-start
mov=encode_mov(folder,24)
probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_name,profile,width,height,pix_fmt,nb_frames,r_frame_rate','-of','json',str(mov)],capture_output=True,text=True,check=True)
decoded=out/'mov-decoded-final.png'
subprocess.run(['ffmpeg','-n','-v','error','-i',str(mov),'-vf','select=eq(n\\,47)','-frames:v','1',str(decoded)],check=True)
alpha=Image.open(decoded).getchannel('A'); assert alpha.getextrema()==(0,255)
assert alpha.getpixel((0,0))==0
for w,h in [(2048,1080),(2560,1440)]:
    path=out/f'final-{w}x{h}.png'; assert render(d,1,w,h).save(str(path)); im=Image.open(path); assert im.size==(w,h) and im.getchannel('A').getextrema()==(0,255)
# Friendly contact sheet: baked checkerboard here only, never in exported frames.
sheet=Image.new('RGB',(960,620),'#172330'); draw=ImageDraw.Draw(sheet)
for index,n in enumerate([0,12,24,47]):
    frame=Image.open(folder/f'frame_{n:06d}.png').resize((480,270))
    tile=Image.new('RGBA',(480,270),'#e8edf0'); grid=ImageDraw.Draw(tile)
    for x in range(0,480,20):
        for y in range(0,270,20):
            if (x//20+y//20)%2: grid.rectangle((x,y,x+19,y+19),fill='#d4dce2')
    tile.alpha_composite(frame); x=(index%2)*480; y=(index//2)*310
    sheet.paste(tile.convert('RGB'),(x,y)); draw.text((x+12,y+282),f'Frame {n+1} / 48',fill='white')
sheet.save(out/'contact-sheet.png')
report=dict(tested_on='Windows, Python 3.12, PySide6 6.10.2',stroke_count=len(d.strokes),frames=count,resolution=[1920,1080],fps=24,png_render_seconds=round(render_seconds,2),first_alpha=Image.open(folder/'frame_000000.png').getchannel('A').getextrema(),last_alpha=Image.open(folder/'frame_000047.png').getchannel('A').getextrema(),decoded_mov_alpha=alpha.getextrema(),mov=json.loads(probe.stdout),additional_resolutions_verified=[[2048,1080],[2560,1440]])
(out/'verification.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
