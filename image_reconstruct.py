"""Reusable raster-source pipeline. Original RGBA is separate from analysis."""
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from adaptive_hand import qimage, pil_image
from image_regions import segment_regions
from image_trace import trace_image

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

def reconstruct(filename,mode='auto_trace',detail='medium'):
    if mode not in ('auto_trace','stroke_reconstruction'):
        raise ValueError('AI redraw is not implemented yet.')
    if detail not in ('low','medium','high'):
        raise ValueError('Choose Low, Medium or High detail.')
    original=load_raster(filename)
    regions=segment_regions(original,detail)
    drawing=trace_image(original,regions,detail,mode)
    # Optional metadata: existing SVG Drawings have no region map and use
    # the unchanged contour/alpha planner.
    drawing.image_regions=regions
    drawing.image_region_priority=mode=='stroke_reconstruction'
    drawing.source_kind='image'
    drawing.source_mode=mode
    return Reconstruction(drawing,qimage(original),regions,mode,detail,Path(filename).name)
