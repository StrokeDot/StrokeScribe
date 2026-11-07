"""Self-contained original/guide assets. Provenance never controls file paths."""
from __future__ import annotations
import base64,hashlib,io,os,tempfile
from pathlib import Path
from PIL import Image
MAX_SOURCE_BYTES=64*1024*1024
MAX_PIXELS=24_000_000
EXTENSIONS={'.png','.jpg','.jpeg','.webp','.bmp'}

def _image_bytes(raw):
    if len(raw)>MAX_SOURCE_BYTES:
        raise ValueError('Artwork source is too large (64 MiB maximum).')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width<1 or im.height<1 or im.width*im.height>MAX_PIXELS:
                raise ValueError('Artwork exceeds the 24 million pixel limit.')
            if im.format not in ('PNG','JPEG','WEBP','BMP'):
                raise ValueError('Unsupported artwork image format.')
            im.verify()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Artwork image could not be validated: '+str(exc)) from exc
    return raw

def _entry(path):
    path=Path(path)
    if path.suffix.lower() not in EXTENSIONS:
        raise ValueError('Unsupported artwork extension.')
    if path.stat().st_size>MAX_SOURCE_BYTES:
        raise ValueError('Artwork source is too large (64 MiB maximum).')
    raw=_image_bytes(path.read_bytes())
    return dict(extension=path.suffix.lower(),data=base64.b64encode(raw).decode('ascii'))

def capture_assets(original_path,guide_path=None):
    return dict(schema=1,kind='raster',original=_entry(original_path),
                guide=_entry(guide_path) if guide_path else None)

def _decode(entry):
    if not isinstance(entry,dict) or entry.get('extension') not in EXTENSIONS:
        raise ValueError('Invalid artwork asset extension.')
    value=entry.get('data')
    if not isinstance(value,str) or len(value)>4*((MAX_SOURCE_BYTES+2)//3):
        raise ValueError('Invalid or oversized artwork asset data.')
    try:
        raw=base64.b64decode(value,validate=True)
    except Exception as exc:
        raise ValueError('Invalid base64 artwork asset.') from exc
    return _image_bytes(raw)

def validate_assets(data):
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema']!=1 or data.get('kind')!='raster':
        raise ValueError('Unsupported artwork asset metadata.')
    _decode(data.get('original'))
    if data.get('guide') is not None:
        _decode(data['guide'])
    # Only normalized, recognized fields survive untrusted input.
    out=dict(schema=1,kind='raster',original=dict(data['original']),guide=dict(data['guide']) if data.get('guide') else None)
    frame=data.get('frame')
    if isinstance(frame,dict):
        import json
        if len(json.dumps(frame))>8192:
            raise ValueError('Artwork alignment metadata is too large.')
        out['frame']=frame
    return out

def materialize_assets(data,root=None):
    data=validate_assets(data)
    if root is None:
        from preflight import config_path
        root=config_path().parent/'artwork-cache'
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    paths=[]
    for key in ('original','guide'):
        entry=data.get(key)
        if entry is None:
            paths.append(None);continue
        raw=_decode(entry)
        path=root/(hashlib.sha256(raw).hexdigest()+entry['extension'])
        if path.is_symlink():
            raise ValueError('Unsafe managed artwork cache entry.')
        if not path.exists() or path.read_bytes()!=raw:
            fd,name=tempfile.mkstemp(prefix='.artwork-',dir=root)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                os.replace(name,path)
            finally:
                Path(name).unlink(missing_ok=True)
        paths.append(str(path))
    return tuple(paths)
