"""Reusable raster-source pipeline. Original RGBA is separate from analysis."""
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from adaptive_hand import qimage, pil_image
from image_regions import segment_regions

SUPPORTED_FORMATS={'PNG','JPEG','WEBP','BMP'}
@dataclass
class Reconstruction:
    drawing: object
    image: object
    regions: object
    mode: str
    detail: str
    filename: str

def load_raster(filename, with_box=False):
    try:
        with Image.open(filename) as source:
            if source.format not in SUPPORTED_FORMATS:
                raise ValueError('Choose PNG, JPEG, WebP or BMP artwork.')
            if source.width*source.height>24_000_000:
                raise ValueError('Image exceeds 24 megapixels. Resize it before importing.')
            # Normalize camera orientation before deriving geometry.
            image=ImageOps.exif_transpose(source).convert('RGBA')
            image.load()
    except (UnidentifiedImageError,OSError) as exc:
        raise ValueError('The image could not be decoded.') from exc
    bbox=image.getchannel('A').getbbox()
    if bbox is None:
        raise ValueError('The image is completely transparent.')
    # Opaque backgrounds are intentionally retained; this is not background removal.
    if with_box:
        return image.crop(bbox), (image.size, bbox)
    return image.crop(bbox)

def line_art_drawing(original,detail='medium',style='clean'):
    """Ordered pen strokes from the line art method (lineart.py)."""
    from engine import Drawing, Stroke
    from lineart import line_art_strokes
    strokes,outlines=line_art_strokes(original,detail,style)
    width=max(original.size)*.0025
    named=[Stroke(('outline' if i<outlines else 'line')+f' {i+1}',points,'#303946',width)
           for i,points in enumerate(strokes)]
    if not named:
        w,h=original.size
        named=[Stroke('image perimeter',[(0,0),(w,0),(w,h),(0,h),(0,0)],'#303946',width)]
    return Drawing(named,(0.,0.,float(original.width),float(original.height)),[
        'Line art ('+('clean drawing' if style=='clean' else 'detailed')+'): pen strokes reconstructed from the image.',
        'Strokes approximate an artist\'s drawing; original colors are painted afterwards.'])


def guide_drawing(guide,detail='medium'):
    """Pen strokes traced from an aligned line drawing (see ai_lineart)."""
    from engine import Drawing, Stroke
    from lineart import line_drawing_strokes
    strokes,outlines=line_drawing_strokes(guide,detail)
    width=max(guide.size)*.0025
    named=[Stroke(('outline' if i<outlines else 'line')+f' {i+1}',points,'#303946',width)
           for i,points in enumerate(strokes)]
    if not named:
        return line_art_drawing(guide,detail,'clean')
    return Drawing(named,(0.,0.,float(guide.width),float(guide.height)),[
        'Line art from an AI line drawing: each drawn line becomes one pen stroke.'])


FAINT_ALPHA=64  # pixels under ~25% visible: background-removal leftovers


def clean_faint_pixels(image, with_box=False):
    """Make nearly invisible leftover pixels fully transparent."""
    alpha=image.getchannel('A').point(lambda a:0 if a<FAINT_ALPHA else a)
    cleaned=image.copy(); cleaned.putalpha(alpha)
    bbox=alpha.getbbox() or (0,0,image.width,image.height)
    result=cleaned.crop(bbox)
    return (result,bbox) if with_box else result


def artist_drawing(original,detail='medium'):
    """Layered 'Artist' animation: light guides, main lines, dark accents."""
    from engine import Drawing, Stroke
    from lineart import artist_strokes, ARTIST_COLORS, ARTIST_WIDTH
    base=max(original.size)*.0025
    counters={}
    strokes=[]
    for layer,points,pace in artist_strokes(original,detail):
        counters[layer]=counters.get(layer,0)+1
        strokes.append(Stroke(f'{layer} {counters[layer]}',points,ARTIST_COLORS[layer],
                              base*ARTIST_WIDTH[layer],pace))
    if not strokes:
        return line_art_drawing(original,detail,'clean')
    return Drawing(strokes,(0.,0.,float(original.width),float(original.height)),[
        'Artist style: light guide shapes, then the main lines area by area '
        '(densest detail last and slowest), then dark accents.'])


def reconstruct(filename,mode='line_art',detail='medium',clean_faint=False,style='clean',
                animation='standard',line_guide=None):
    """Pen strokes + colours from an image.

    line_guide: optional clean line drawing of the same image (for example
    made by an AI model). It is lined up with the image and traced instead of
    the image itself; the image still supplies the colours.
    """
    if mode!='line_art':
        raise ValueError('Line art is the image method.')
    if detail not in ('low','medium','high','max'):
        raise ValueError('Choose Low, Medium, High or Max detail.')
    original,(full_size,box)=load_raster(filename,with_box=True)
    box2=None
    if clean_faint:
        original,box2=clean_faint_pixels(original,with_box=True)
    regions=segment_regions(original,'high' if detail=='max' else detail)
    if animation not in ('standard','artist'):
        raise ValueError('Choose the Standard or Artist animation.')
    source=original
    guide_score=None
    if line_guide is not None:
        from ai_lineart import guide_image
        guide=line_guide if isinstance(line_guide,Image.Image) else Image.open(line_guide)
        # The line drawing was made from the whole image file: bring it to the
        # file's size and crop it exactly like the artwork was cropped.
        guide=guide.convert('RGBA')
        flat=Image.new('RGBA',guide.size,(255,255,255,255)); flat.alpha_composite(guide)
        guide=flat.resize(full_size,Image.LANCZOS).crop(box)
        if box2:
            guide=guide.crop(box2)
        source,guide_score=guide_image(original,guide)
    if guide_score is not None:
        drawing=guide_drawing(source,detail)
    elif animation=='artist':
        drawing=artist_drawing(source,detail)
        style='clean'
    else:
        drawing=line_art_drawing(source,detail,style)
    if guide_score is not None:
        drawing.warnings=list(drawing.warnings)+[
            'Strokes traced from the AI line drawing'+(
                f' (lined up with the image, match {guide_score:.0%}).' if guide_score>0 else
                ' (could not be lined up automatically; check that the lines match the colours).')]
        drawing.line_guide_score=guide_score
    drawing.line_style=style
    drawing.animation_style=animation
    drawing.image_regions=regions
    drawing.image_region_priority=True
    drawing.source_kind='image'
    drawing.source_mode='line_art'
    return Reconstruction(drawing,qimage(original),regions,'line_art',detail,Path(filename).name)
