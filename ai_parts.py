"""AI parts: the parts of a picture found by Segment Anything, for the Painter mode.

Segment Anything (Meta, Apache 2.0) finds the objects and pieces in a picture
(an ear cushion, a speaker, the band) instead of colour patches. It runs once
per picture in the AI engine's Python (ai_parts_worker.py, on the graphics card
when there is one); the result is a label picture kept on the element
(drawing.ai_parts_image) and saved with the project. Painting itself never
needs the AI.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

HF = 'https://huggingface.co/facebook/sam-vit-huge/resolve/87aecf0df4ce6b30cd7de76e87673c49644bdf67/'
FOLDER = 'segment_anything/sam-vit-huge'
LICENSE = 'Apache 2.0 (Meta Segment Anything)'


def model_files():
    from ai_models import ModelFile
    return (ModelFile(HF + 'config.json', FOLDER, 6569),
            ModelFile(HF + 'preprocessor_config.json', FOLDER, 466),
            ModelFile(HF + 'model.safetensors', FOLDER, 2564432288,
                      'edfb0462392541fca9af44ff039bfb32dbd0c939997f3abb77a26e23af7afd7c'))


def download_size_gb():
    return sum(f.size for f in model_files()) / 1024 ** 3


def model_dir(paths):
    return paths.models / FOLDER


def engine_ready(paths):
    return paths.engine_installed()


def model_ready(paths):
    """All files there with their full size (the checksum was checked when downloading)."""
    for f in model_files():
        target = paths.model_path(f)
        if not target.is_file() or target.stat().st_size != f.size:
            return False
    return True


def download(paths, progress=lambda done, total, name: None, cancelled=lambda: False):
    from ai_engine import download_model
    missing = [f for f in model_files()
               if not paths.model_path(f).is_file() or paths.model_path(f).stat().st_size != f.size]
    if missing:
        download_model(paths, missing, progress, cancelled)


def find_parts(paths, picture, cpu=False, log=lambda text: None, cancelled=lambda: False):
    """Run Segment Anything on `picture` (PIL RGBA); returns a PIL 'I;16' label image (same size)."""
    import tempfile
    from PIL import Image
    worker = Path(__file__).resolve().parent / 'ai_parts_worker.py'
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / 'picture.png', Path(tmp) / 'parts.png'
        picture.convert('RGBA').save(src)
        cmd = [str(paths.python), '-I', str(worker), str(model_dir(paths)), str(src), str(out)]
        if cpu:
            cmd.append('--cpu')
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                creationflags=flags, encoding='utf-8', errors='replace')
        lines = []

        def read():
            for line in proc.stdout:
                lines.append(line.rstrip())
                log(line.rstrip())
        reader = threading.Thread(target=read, daemon=True); reader.start()
        while proc.poll() is None:
            if cancelled():
                proc.kill(); raise InterruptedError('Cancelled.')
            reader.join(.2)
        reader.join(2)
        if proc.returncode or not out.is_file():
            tail = '\n'.join(lines[-12:])
            raise RuntimeError('Segment Anything could not find the parts.\n' + tail)
        labels = Image.open(out); labels.load()
        info = next((json.loads(l) for l in reversed(lines) if l.startswith('{')), {})
        labels.info['parts'] = info.get('parts')
        return labels


def regions_of(labels, size):
    """The label picture as a grid of part ids `size` (gw, gh) (nearest neighbour)."""
    from PIL import Image
    im = labels if labels.mode == 'I' else labels.convert('I')
    return list(im.resize(size, Image.Resampling.NEAREST).getdata())
