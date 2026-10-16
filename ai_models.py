"""Open image models StrokeScribe can run locally, and which version fits a PC.

Each model comes in several versions (variants) of different size. The app
reads the graphics card memory (VRAM) and system memory (RAM) and picks the
best version that fits, so the same feature works on small and large PCs.
Bigger cards get the full-precision files; smaller ones get compressed
(quantized, GGUF) files that look slightly less detailed but run.

All files come from Hugging Face and are verified in CI (name and byte size).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field

HF = 'https://huggingface.co/'


@dataclass(frozen=True)
class ModelFile:
    url: str
    folder: str          # ComfyUI models sub-folder
    size: int            # bytes (checked after download)

    @property
    def name(self):
        return self.url.rsplit('/', 1)[-1]


@dataclass(frozen=True)
class Variant:
    id: str
    label: str
    min_vram_gb: float          # runs fully on the graphics card from here
    diffusion: ModelFile
    loader: str = 'unet'        # 'unet' (safetensors) or 'gguf'
    note: str = ''


@dataclass(frozen=True)
class ImageModel:
    id: str
    name: str
    maker: str
    license: str
    license_url: str
    commercial: str             # plain-language summary of the license
    needs_acceptance: bool      # show the license and ask before downloading
    tasks: tuple                # 'generate', 'edit'
    variants: tuple             # largest first
    shared: tuple               # text encoder, VAE, speed-up LoRA (all variants)
    min_ram_gb: float
    good_ram_gb: float
    steps: int
    summary: str
    low_ram_shared: tuple = field(default=())   # smaller text encoder for low RAM

    def files(self, variant, ram_gb=None):
        return (variant.diffusion,) + self.shared_files(ram_gb)

    def shared_files(self, ram_gb=None):
        if self.low_ram_shared and ram_gb is not None and ram_gb < self.good_ram_gb:
            return self.low_ram_shared
        return self.shared


def _f(path, folder, size):
    return ModelFile(HF + path, folder, size)


QWEN_VAE = _f('Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors',
              'vae', 253806246)
QWEN_TEXT = _f('Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/'
               'qwen_2.5_vl_7b_fp8_scaled.safetensors', 'text_encoders', 9384670680)
QWEN_LIGHTNING = _f('lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/'
                    'Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors', 'loras', 849608296)
QWEN_GGUF = 'unsloth/Qwen-Image-Edit-2511-GGUF/resolve/main/qwen-image-edit-2511-'

FLUX2_VAE = _f('Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors',
               'vae', 336213556)
KLEIN_TEXT = _f('Comfy-Org/flux2-klein/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors',
                'text_encoders', 8044982048)
DEV_TEXT = _f('Comfy-Org/flux2-dev/resolve/main/split_files/text_encoders/'
              'mistral_3_small_flux2_fp8.safetensors', 'text_encoders', 18034640095)
DEV_TEXT_SMALL = _f('Comfy-Org/flux2-dev/resolve/main/split_files/text_encoders/'
                    'mistral_3_small_flux2_fp4_mixed.safetensors', 'text_encoders', 12275678071)
DEV_TURBO = _f('Comfy-Org/flux2-dev/resolve/main/split_files/loras/Flux2TurboComfyv2.safetensors',
               'loras', 2760814872)
DEV_GGUF = 'city96/FLUX.2-dev-gguf/resolve/main/flux2-dev-'


QWEN_EDIT = ImageModel(
    id='qwen_edit_2511', name='Qwen-Image-Edit 2511', maker='Alibaba (Qwen)',
    license='Apache 2.0', license_url='https://www.apache.org/licenses/LICENSE-2.0',
    commercial='Free for any use, including commercial.', needs_acceptance=False,
    tasks=('edit',),
    summary='Best free editor: turns an image into clean line art or follows edit instructions '
            'while keeping the layout.',
    variants=(
        Variant('fp8', 'Full quality (FP8)', 22,
                _f('Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/'
                   'qwen_image_edit_2511_fp8mixed.safetensors', 'diffusion_models', 20533762817)),
        Variant('q5', 'High (GGUF Q5_K_M)', 18,
                _f(QWEN_GGUF + 'Q5_K_M.gguf', 'diffusion_models', 15027501664), 'gguf'),
        Variant('q4', 'Balanced (GGUF Q4_K_M)', 15,
                _f(QWEN_GGUF + 'Q4_K_M.gguf', 'diffusion_models', 13244758624), 'gguf'),
        Variant('q4_0', 'Compact (GGUF Q4_0)', 11.5,
                _f(QWEN_GGUF + 'Q4_0.gguf', 'diffusion_models', 11852773984), 'gguf'),
        Variant('q3', 'Small (GGUF Q3_K_M)', 9.5,
                _f(QWEN_GGUF + 'Q3_K_M.gguf', 'diffusion_models', 9920805472), 'gguf',
                'Noticeably less detail.'),
        Variant('q2', 'Smallest (GGUF Q2_K)', 7.5,
                _f(QWEN_GGUF + 'Q2_K.gguf', 'diffusion_models', 7468022368), 'gguf',
                'Lowest quality; for 8 GB cards.'),
    ),
    shared=(QWEN_TEXT, QWEN_VAE, QWEN_LIGHTNING),
    min_ram_gb=16, good_ram_gb=32, steps=4,
)

FLUX2_KLEIN = ImageModel(
    id='flux2_klein_4b', name='FLUX.2 [klein] 4B', maker='Black Forest Labs',
    license='Apache 2.0', license_url='https://www.apache.org/licenses/LICENSE-2.0',
    commercial='Free for any use, including commercial.', needs_acceptance=False,
    tasks=('generate', 'edit'),
    summary='Small and fast: creates images from text and edits images, in seconds.',
    variants=(
        Variant('bf16', 'Full quality (BF16)', 11,
                _f('Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/'
                   'flux-2-klein-4b.safetensors', 'diffusion_models', 7751105712)),
        Variant('fp8', 'Compact (FP8)', 5.5,
                _f('black-forest-labs/FLUX.2-klein-4b-fp8/resolve/main/flux-2-klein-4b-fp8.safetensors',
                   'diffusion_models', 4070624520)),
    ),
    shared=(KLEIN_TEXT, FLUX2_VAE),
    min_ram_gb=12, good_ram_gb=16, steps=4,
)

FLUX2_DEV = ImageModel(
    id='flux2_dev', name='FLUX.2 [dev]', maker='Black Forest Labs',
    license='FLUX [dev] Non-Commercial License',
    license_url='https://huggingface.co/black-forest-labs/FLUX.2-dev/blob/main/LICENSE.md',
    commercial='The model is for non-commercial use. Check the license before using it in '
               'anything you sell; ask Black Forest Labs for a commercial license.',
    needs_acceptance=True,
    tasks=('generate', 'edit'),
    summary='Highest quality, very large (32B). Needs a lot of memory and is slow on smaller cards.',
    variants=(
        Variant('fp8', 'Full quality (FP8)', 38,
                _f('Comfy-Org/flux2-dev/resolve/main/split_files/diffusion_models/'
                   'flux2_dev_fp8mixed.safetensors', 'diffusion_models', 35455599592)),
        Variant('q5', 'High (GGUF Q5_K_M)', 27,
                _f(DEV_GGUF + 'Q5_K_M.gguf', 'diffusion_models', 24057238496), 'gguf'),
        Variant('q4', 'Balanced (GGUF Q4_K_M)', 22,
                _f(DEV_GGUF + 'Q4_K_M.gguf', 'diffusion_models', 20082414560), 'gguf'),
        Variant('q3', 'Compact (GGUF Q3_K_M)', 15,
                _f(DEV_GGUF + 'Q3_K_M.gguf', 'diffusion_models', 15960134624), 'gguf',
                'Part of the model runs from system memory: slower.'),
        Variant('q2', 'Smallest (GGUF Q2_K)', 11.5,
                _f(DEV_GGUF + 'Q2_K.gguf', 'diffusion_models', 12858250208), 'gguf',
                'Lowest quality.'),
    ),
    shared=(DEV_TEXT, FLUX2_VAE, DEV_TURBO),
    low_ram_shared=(DEV_TEXT_SMALL, FLUX2_VAE, DEV_TURBO),
    min_ram_gb=32, good_ram_gb=64, steps=8,
)

MODELS = (QWEN_EDIT, FLUX2_KLEIN, FLUX2_DEV)
BY_ID = {m.id: m for m in MODELS}


# ---------------------------------------------------------------- hardware

@dataclass
class Hardware:
    gpu: str | None
    vram_gb: float | None
    ram_gb: float | None
    nvidia: bool

    def summary(self):
        parts = [f'{self.gpu} ({self.vram_gb:.0f} GB graphics memory)' if self.gpu and self.vram_gb
                 else 'No NVIDIA graphics card found']
        if self.ram_gb:
            parts.append(f'{self.ram_gb:.0f} GB system memory')
        return '  •  '.join(parts)


def detect_hardware():
    """Graphics card (via nvidia-smi) and system memory. Never raises."""
    gpu = vram = None
    exe = shutil.which('nvidia-smi')
    if exe:
        try:
            out = subprocess.run([exe, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                                 capture_output=True, text=True, timeout=8,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
            best = None
            for line in out.strip().splitlines():
                name, mem = [x.strip() for x in line.rsplit(',', 1)]
                mem_gb = float(mem) / 1024
                if best is None or mem_gb > best[1]:
                    best = (name, mem_gb)
            if best:
                gpu, vram = best
        except Exception:
            pass
    try:
        from preflight import memory_gb
        ram = memory_gb()[0]
    except Exception:
        ram = None
    return Hardware(gpu, vram, ram, gpu is not None)


# ---------------------------------------------------------------- choosing

FIT_GOOD, FIT_SLOW, FIT_NO = 'good', 'slow', 'no'


def choose_variant(model, hw):
    """Best version for this PC and how well it fits.

    good: runs fully on the graphics card. slow: part of the model is kept in
    system memory (ComfyUI moves it in and out), still works. no: not enough
    memory at all (or no NVIDIA card).
    """
    smallest = model.variants[-1]
    if not hw.nvidia or not hw.vram_gb:
        return smallest, FIT_NO
    usable = hw.vram_gb - .5          # the desktop uses a little of the card
    for variant in model.variants:
        if usable >= variant.min_vram_gb:
            fit = FIT_GOOD
            if hw.ram_gb is not None and hw.ram_gb < model.min_ram_gb:
                fit = FIT_NO
            elif hw.ram_gb is not None and hw.ram_gb < model.good_ram_gb:
                fit = FIT_SLOW
            return variant, fit
    # Smaller than the smallest version: it can still run partly from RAM.
    if usable >= smallest.min_vram_gb * .6 and (hw.ram_gb or 0) >= model.good_ram_gb:
        return smallest, FIT_SLOW
    return smallest, FIT_NO


def fit_text(fit):
    return {FIT_GOOD: 'Fits your PC', FIT_SLOW: 'Runs, but slower on your PC',
            FIT_NO: 'Too big for your PC'}[fit]


def download_size(model, variant, ram_gb=None):
    return sum(f.size for f in model.files(variant, ram_gb))


def gb(size):
    return f'{size / 1e9:.1f} GB'
