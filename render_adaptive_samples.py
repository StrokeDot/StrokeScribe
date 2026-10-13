"""Generate review frames in GitHub Actions; no personal artwork is required."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
from PIL import Image, ImageDraw
from test_adaptive import fixture, APP
from adaptive_hand import plan_for, pil_image
from color_reveal import render_color_timeline

def main():
    out=Path('samples/adaptive-demo'); out.mkdir(parents=True,exist_ok=True)
    drawing,image=fixture(240)
    pil_image(image).save(out/'representative-source.png')
    paths=[]
    for stroke in drawing.strokes:
        commands='M '+' L '.join(f'{x},{y}' for x,y in stroke.points)
        paths.append(f'<path d="{commands}" />')
    (out/'representative-contours.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">'
        '<g fill="none" stroke="#153c54" stroke-width="2">'+''.join(paths)+'</g></svg>')
    # Fixture bounds deliberately include whitespace. The program auto-fits SVG
    # geometry and PNG independently; real paired files need matching extents.
    plan=plan_for(drawing,image,.12,.55)
    counts={}
    sheet=Image.new('RGB',(1280,1000),'#f5f5f5')
    pen=ImageDraw.Draw(sheet)
    for i,progress in enumerate((.25,.5,.75,1.)):
        frame=render_color_timeline(drawing,(2+8*progress)/10,
            width=640,height=480,duration=2,fade_duration=8,hold_duration=0,
            final_image=image,reveal_mode='adaptive',brush_width=.12,stroke_spacing=.55)
        name=f'painting-{round(progress*100):03d}.png'
        frame.save(str(out/name))
        rgba=pil_image(frame)
        background=Image.new('RGBA',rgba.size,'white')
        background.alpha_composite(rgba)
        x=(i%2)*640; y=(i//2)*500
        sheet.paste(background.convert('RGB'),(x,y))
        pen.text((x+12,y+482),f'{round(progress*100)}% painting progress',fill='black')
        counts[str(progress)]=sum(plan.mask(progress).histogram()[1:])
    sheet.save(out/'contact-sheet.png')
    report=dict(regions=plan.region_count,segments=len(plan.segments),
        coverage=counts,complete_by=.98,warnings=plan.warnings,
        headset_png_available=False,
        fixture='Representative transparent illustration; not headset colors',
        planning_grid=plan.size)
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    # Downloaded packages include these four reference frames and source fixture.
if __name__=='__main__':
    main()
