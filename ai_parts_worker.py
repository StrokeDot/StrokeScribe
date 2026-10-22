"""Find the parts of a picture with Segment Anything (runs in the AI engine's Python).

    python ai_parts_worker.py MODEL_DIR IMAGE OUT_PNG [--cpu]

MODEL_DIR holds a Hugging Face Segment Anything checkpoint (config.json,
preprocessor_config.json, model.safetensors). IMAGE is the colour picture.
OUT_PNG gets a 16-bit label image of the same size: 0 = nothing (transparent),
1..n = parts. Bigger parts are written first, so a smaller part inside a bigger
one (a speaker inside an ear cup) keeps its own label. A JSON line with the
part count and timing is printed at the end.

This file only uses packages the AI engine already has (torch, transformers,
numpy, Pillow); StrokeScribe itself never imports it.
"""
from __future__ import annotations

import json
import sys
import time

MAX_SIDE = 1024           # Segment Anything works at 1024 px anyway
MIN_SHARE = .0004         # masks smaller than this share of the picture are ignored


def find_parts(model_dir, image_path, out_path, cpu=False):
    import numpy as np
    import torch
    from PIL import Image
    from transformers import pipeline
    started = time.time()
    picture = Image.open(image_path).convert('RGBA')
    w, h = picture.size
    scale = min(1., MAX_SIDE / max(w, h))
    small = picture.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS) \
        if scale < 1 else picture
    flat = Image.new('RGBA', small.size, 'white')
    flat.alpha_composite(small)
    device = 0 if (torch.cuda.is_available() and not cpu) else -1
    finder = pipeline('mask-generation', model=str(model_dir), device=device)
    result = finder(flat.convert('RGB'), points_per_batch=64, pred_iou_thresh=.86,
                    stability_score_thresh=.9)
    masks = [np.asarray(m, bool) for m in result['masks']]
    alpha = np.asarray(small.getchannel('A')) >= 64
    area = max(1, int(alpha.sum()))
    masks = [m & alpha for m in masks]
    masks = [m for m in masks if m.sum() >= MIN_SHARE * area]
    masks.sort(key=lambda m: -int(m.sum()))          # big first; smaller parts drawn over them
    labels = np.zeros(alpha.shape, np.uint16)
    for i, m in enumerate(masks[:65000], 1):
        labels[m] = i
    # Picture left without any part: one more part per connected piece.
    rest = alpha & (labels == 0)
    if rest.any():
        try:
            import cv2
            n, comp = cv2.connectedComponents(rest.astype(np.uint8), connectivity=4)
            for c in range(1, n):
                labels[comp == c] = len(masks) + c
        except ImportError:
            labels[rest] = len(masks) + 1
    out = Image.fromarray(labels, 'I;16')
    if out.size != (w, h):
        out = out.resize((w, h), Image.Resampling.NEAREST)
    out.save(out_path)
    info = dict(parts=int(labels.max()), masks=len(masks), seconds=round(time.time() - started, 2),
                device='cuda' if device == 0 else 'cpu', size=[w, h])
    print(json.dumps(info), flush=True)
    return info


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 3:
        print(__doc__); sys.exit(2)
    find_parts(args[0], args[1], args[2], cpu='--cpu' in sys.argv)
