"""Render the supplied headset's manually reconstructed SVG with the prototype."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json, subprocess, time
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication
from engine import import_svg, export_frames, encode_mov, render

app=QApplication([])
here=Path(__file__).parent
out=here/'headset-demo'; out.mkdir(exist_ok=True)
drawing=import_svg(here/'samples/arthur-headset-traced.svg')
frames=out/'transparent-frames'
started=time.perf_counter()
count=export_frames(drawing,frames,duration=8,fps=24,width=1920,height=1080)
mov=encode_mov(frames,24)
render(drawing,1).save(str(out/'headset-final-transparent.png'))
# Only the viewing copy has a white background. Source PNGs and MOV retain alpha.
preview=out/'headset-preview-white.mp4'
subprocess.run(['ffmpeg','-n','-hide_banner','-loglevel','error',
 '-f','lavfi','-i','color=c=white:s=1920x1080:r=24:d=8',
 '-framerate','24','-i',str(frames/'frame_%06d.png'),
 '-filter_complex','[0:v][1:v]overlay=shortest=1,format=yuv420p',
 '-c:v','libx264','-crf','19','-movflags','+faststart',str(preview)],check=True)
subprocess.run(['ffmpeg','-n','-hide_banner','-loglevel','error','-i',str(preview),
 '-filter_complex','fps=12,scale=768:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse',str(out/'headset-preview.gif')],check=True)
subprocess.run(['ffmpeg','-n','-hide_banner','-loglevel','error','-i',str(mov),'-vf','select=eq(n\\,191)','-frames:v','1',str(out/'mov-final-alpha-check.png')],check=True)
first=Image.open(frames/'frame_000000.png'); last=Image.open(frames/'frame_000191.png'); decoded=Image.open(out/'mov-final-alpha-check.png')
assert first.getchannel('A').getextrema()==(0,0)
assert last.getchannel('A').getextrema()==(0,255)
assert decoded.getchannel('A').getextrema()==(0,255)
assert last.size==(1920,1080)
assert decoded.getchannel('A').getpixel((0,0))==0
coverage=[]
for n in (0,48,96,144,191):
    alpha=Image.open(frames/f'frame_{n:06d}.png').getchannel('A')
    coverage.append(sum(alpha.histogram()[1:]))
assert all(a<b for a,b in zip(coverage,coverage[1:]))
report=dict(source='arthur headset white.png',conversion='Manual simplified contour reconstruction; not automatic tracing',strokes=len(drawing.strokes),frames=count,fps=24,duration_seconds=8,resolution=[1920,1080],png_alpha_verified=True,decoded_prores_alpha_verified=True,coverage_samples=coverage,elapsed_seconds=round(time.perf_counter()-started,2),filmora_tested=False)
(out/'verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
