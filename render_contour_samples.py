"""Generate review frames remotely; synthetic artwork, not the user's headset."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PIL import Image, ImageDraw
from test_contour_transitions import fixture, frame, pixels
from engine import render
out=Path('samples/contour-transitions')
out.mkdir(parents=True,exist_ok=True)
d,im=fixture()
im.save(str(out/'synthetic-headset-source.png'))
rows=[]
for mode in ('legacy','paint','retire'):
    d.contour_transition=mode
    for direction in (('forward','reverse') if mode=='retire' else ('forward',)):
        d.retirement_direction=direction
        row=Image.new('RGB',(320*6,270),'#202832')
        for col,p in enumerate((.25,.50,.75,.85,.98,1.)):
            f=frame(d,im,p)
            f.save(str(out/f'{mode}-{direction}-{round(p*100):03d}.png'))
            tile=Image.new('RGBA',(320,240),'#e1e5ea')
            draw=ImageDraw.Draw(tile)
            for y in range(0,240,16):
                for x in range(0,320,16):
                    if (x//16+y//16)%2:draw.rectangle((x,y,x+15,y+15),fill='#bac3ce')
            tile.alpha_composite(Image.fromarray(pixels(f)))
            row.paste(tile.convert('RGB'),(col*320,30))
            ImageDraw.Draw(row).text((col*320+8,8),f'{mode} {direction}: {p:.0%}',fill='white')
        rows.append(row)
sheet=Image.new('RGB',(1920,270*len(rows)),'#202832')
for i,row in enumerate(rows):sheet.paste(row,(0,i*270))
sheet.save(out/'comparison.png')
for p in (0,.25,.5,.75,1):
    render(d,p,640,480).save(str(out/f'drawing-{round(p*100):03d}.png'))
print('Review frames: samples/contour-transitions/comparison.png')
