"""Render representative workflow evidence in remote CI; no user files/models."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication
from engine import import_svg
from image_reconstruct import reconstruct
from svg_appearance import render_appearance
from test_artwork_rendering import rgba,frame
APP=QApplication.instance() or QApplication([])
OUT=Path('samples/artwork-workflow')

def make_samples():
    OUT.mkdir(parents=True,exist_ok=True)
    original=Image.new('RGBA',(300,220),(0,0,0,0))
    c=ImageDraw.Draw(original)
    c.rectangle((60,85,235,190),fill='#f2c26b')
    c.polygon([(42,88),(146,22),(252,88)],fill='#da594b')
    c.rectangle((128,126,166,190),fill='#5c8dd5')
    c.rectangle((80,112,110,143),fill='#79d6e9')
    c.rectangle((184,112,214,143),fill='#79d6e9')
    c.ellipse((248,20,280,52),fill='#f2b937')
    original.save(OUT/'house-original.png')
    guide=Image.new('RGB',original.size,'white');g=ImageDraw.Draw(guide)
    g.line([(42,88),(146,22),(252,88)],fill='black',width=3)
    for b in ((60,85,235,190),(128,126,166,190),(80,112,110,143),(184,112,214,143)):
        g.rectangle(b,outline='black',width=2)
    g.ellipse((248,20,280,52),outline='black',width=2)
    guide.save(OUT/'house-guide.png')
    r=reconstruct(str(OUT/'house-original.png'),detail='low',line_guide=str(OUT/'house-guide.png'))
    r.drawing.image_animation='draw_paint'
    cases=[('paired-house',r.drawing,r.image)]
    portrait=Image.new('RGBA',(120,240),(0,0,0,0));p=ImageDraw.Draw(portrait)
    p.ellipse((34,15,87,79),fill='#d49a72')
    p.polygon([(31,84),(90,84),(110,193),(8,193)],fill='#358cbe')
    p.rectangle((32,190,49,226),fill='#c48361');p.rectangle((70,190,87,226),fill='#c48361')
    portrait.save(OUT/'portrait-original.png')
    lines=Image.new('RGB',portrait.size,'white');p=ImageDraw.Draw(lines)
    p.ellipse((34,15,87,79),outline='black',width=2)
    p.line([(31,84),(90,84),(110,193),(8,193),(31,84)],fill='black',width=2)
    p.rectangle((32,190,49,226),outline='black',width=2);p.rectangle((70,190,87,226),outline='black',width=2)
    square=Image.new('RGB',(240,240),'white');square.paste(lines,(60,0));square.save(OUT/'portrait-guide.png')
    r=reconstruct(str(OUT/'portrait-original.png'),detail='low',line_guide=str(OUT/'portrait-guide.png'))
    r.drawing.image_animation='draw_paint'
    cases.append(('letterboxed-portrait',r.drawing,r.image))
    svg=OUT/'filled-controller.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="260" height="140"><path fill="#111111" fill-rule="evenodd" d="M55 20H205Q225 20 235 50L250 110Q250 132 228 124L186 96H74L32 124Q10 132 10 110L25 50Q35 20 55 20Z M55 49H69V61H81V75H69V87H55V75H43V61H55Z"/><circle cx="186" cy="57" r="7" fill="#58b25d"/><circle cx="207" cy="74" r="7" fill="#d75149"/></svg>')
    d=import_svg(svg);cases.append(('native-filled-controller',d,render_appearance(d,960)))
    stages=[('Empty',0),('Draw 25%',.25/2.2),('Draw 75%',.75/2.2),('Paint 0%',1/2.2),
            ('Paint 25%',1.25/2.2),('Paint 50%',1.5/2.2),('Paint 75%',1.75/2.2),('Paint 100%',1)]
    for name,d,image in cases:
        o=dict(width=640,height=360,duration=1.,fade_duration=1.,hold_duration=.2,
               final_image=image,hand=None,painting_hand=None,reveal_mode='adaptive',
               brush_width=.18,stroke_spacing=.55,artwork_scale=1.,thickness=1.,layers='art')
        sheet=Image.new('RGB',(1280,780),'#202733');labels=ImageDraw.Draw(sheet)
        for i,(label,f) in enumerate(stages):
            q=frame(d,o,f)
            q.save(str(OUT/(name+'-'+label.lower().replace(' ','-').replace('%','')+'.png')))
            art=Image.fromarray(rgba(q),'RGBA').resize((320,180))
            tile=Image.new('RGBA',(320,180),'#e8edf2')
            grid=ImageDraw.Draw(tile)
            for y in range(0,180,12):
                for x in range(0,320,12):
                    if (x//12+y//12)%2:grid.rectangle((x,y,x+11,y+11),fill='#cbd2dc')
            tile.alpha_composite(art)
            x=(i%4)*320;y=(i//4)*390
            sheet.paste(tile.convert('RGB'),(x,y+25))
            labels.text((x+8,y+6),name+' | '+label,fill='white')
        # Keep geometry undistorted; unused space leaves room for labels.
        sheet=sheet.crop((0,0,1280,600))
        sheet.save(OUT/(name+'-contact-sheet.png'))
    (OUT/'README.txt').write_text('Original synthetic fixtures, not the user Cain/Abel or beach-girl files. Individual PNGs retain alpha. Contact sheets show a checkerboard only for review. Created on the remote runner. Native SVG source and paired PNG/guide are included.\n')

if __name__=='__main__':make_samples()
