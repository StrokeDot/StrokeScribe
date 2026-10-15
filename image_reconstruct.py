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

def load_raster(filename):
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


FAINT_ALPHA=64  # pixels under ~25% visible: background-removal leftovers


def clean_faint_pixels(image):
    """Make nearly invisible leftover pixels fully transparent."""
    alpha=image.getchannel('A').point(lambda a:0 if a<FAINT_ALPHA else a)
    cleaned=image.copy(); cleaned.putalpha(alpha)
    bbox=alpha.getbbox()
    return cleaned.crop(bbox) if bbox else cleaned


def reconstruct(filename,mode='line_art',detail='medium',clean_faint=False,style='clean'):
    if mode!='line_art':
        raise ValueError('Line art is the image method.')
    if detail not in ('low','medium','high','max'):
        raise ValueError('Choose Low, Medium, High or Max detail.')
    original=load_raster(filename)
    if clean_faint:
        original=clean_faint_pixels(original)
    regions=segment_regions(original,'high' if detail=='max' else detail)
    drawing=line_art_drawing(original,detail,style)
    drawing.line_style=style
    drawing.image_regions=regions
    drawing.image_region_priority=True
    drawing.source_kind='image'
    drawing.source_mode='line_art'
    return Reconstruction(drawing,qimage(original),regions,'line_art',detail,Path(filename).name)
