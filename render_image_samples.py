"""Remote CI review artifacts; synthetic artwork, never a substitute for user photos."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PIL import Image,ImageDraw
from test_image_source import artwork,APP
from image_reconstruct import reconstruct
from color_reveal import render_color_timeline
from adaptive_hand import plan_for,pil_image
out=Path('samples/image-reconstruction-demo'); out.mkdir(parents=True,exist_ok=True)
source=out/'representative-transparent.png'; artwork().save(source)
result=reconstruct(source,'line_art','medium')
plan=plan_for(result.drawing,result.image)
frames=[]
for fraction in (.25,.5,.75,1):
    image=pil_image(render_color_timeline(result.drawing,(1+fraction*4)/5,640,360,
            duration=1,fade_duration=4,hold_duration=0,final_image=result.image,reveal_mode='adaptive'))
    image.save(out/f'painting-{round(fraction*100):03d}.png')
    bg=Image.new('RGB',image.size,'#dddddd')
    bg.paste(image,mask=image.getchannel('A')); ImageDraw.Draw(bg).text((10,10),f'Painting {fraction:.0%}',fill='black'); frames.append(bg)
sheet=Image.new('RGB',(1280,720))
for i,im in enumerate(frames): sheet.paste(im,((i%2)*640,(i//2)*360))
sheet.save(out/'contact-sheet.png')
(out/'README.txt').write_text('Synthetic transparent illustration. Original headset PNG is not supplied by this task. Review Windows hand calibration, busy artwork and real photographs manually. All color samples use identical adaptive masks in preview/export.\n')
print(f'Regions: {plan.region_count}; brush segments: {len(plan.segments)}')

# A compact remote preview is also available in CI logs for automated review.
import io,base64
buffer=io.BytesIO(); sheet.resize((960,540)).save(buffer,format='PNG')
print('REVIEW_IMAGE_BASE64='+base64.b64encode(buffer.getvalue()).decode('ascii'))
