"""ComfyUI workflows (API format) for the three image models.

Built from the official ComfyUI workflow templates (Comfy-Org/workflow_templates):
image_qwen_image_edit_2511, image_flux2_klein_*_4b_distilled and image_flux2_fp8.
CI submits every workflow to a real ComfyUI server to check the node names and
inputs.
"""
from __future__ import annotations

from ai_models import FLUX2_DEV, FLUX2_KLEIN, QWEN_EDIT

LINE_ART_PROMPT = (
    'Redraw this image as clean black line art on a pure white background, like a '
    'coloring book page: smooth single outlines of every shape and the important inner '
    'details, even line weight, no shading, no hatching, no colour, no fills, no text added. '
    'Keep exactly the same composition, position, size and proportions as the original.')


def _model_loader(variant):
    if variant.loader == 'gguf':
        return {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': variant.diffusion.name}}
    return {'class_type': 'UNETLoader',
            'inputs': {'unet_name': variant.diffusion.name, 'weight_dtype': 'default'}}


def _shared(model, ram_gb, folder):
    return next(f for f in model.shared_files(ram_gb) if f.folder == folder)


def qwen_edit(variant, image_name, prompt, seed, ram_gb=None, prefix='StrokeScribe'):
    m = QWEN_EDIT
    return {
        '1': _model_loader(variant),
        '2': {'class_type': 'CLIPLoader', 'inputs': {
            'clip_name': _shared(m, ram_gb, 'text_encoders').name, 'type': 'qwen_image',
            'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': _shared(m, ram_gb, 'vae').name}},
        '5': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['1', 0], 'shift': 3.1}},
        '6': {'class_type': 'CFGNorm', 'inputs': {'model': ['5', 0], 'strength': 1.0}},
        '4': {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': ['6', 0], 'lora_name': _shared(m, ram_gb, 'loras').name, 'strength_model': 1.0}},
        '7': {'class_type': 'LoadImage', 'inputs': {'image': image_name}},
        '8': {'class_type': 'FluxKontextImageScale', 'inputs': {'image': ['7', 0]}},
        '9': {'class_type': 'TextEncodeQwenImageEditPlus', 'inputs': {
            'clip': ['2', 0], 'prompt': prompt, 'vae': ['3', 0], 'image1': ['8', 0]}},
        '10': {'class_type': 'TextEncodeQwenImageEditPlus', 'inputs': {
            'clip': ['2', 0], 'prompt': '', 'vae': ['3', 0], 'image1': ['8', 0]}},
        '11': {'class_type': 'FluxKontextMultiReferenceLatentMethod', 'inputs': {
            'conditioning': ['9', 0], 'reference_latents_method': 'index_timestep_zero'}},
        '12': {'class_type': 'FluxKontextMultiReferenceLatentMethod', 'inputs': {
            'conditioning': ['10', 0], 'reference_latents_method': 'index_timestep_zero'}},
        '13': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['8', 0], 'vae': ['3', 0]}},
        '14': {'class_type': 'KSampler', 'inputs': {
            'model': ['4', 0], 'seed': int(seed), 'steps': m.steps, 'cfg': 1.0,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['11', 0],
            'negative': ['12', 0], 'latent_image': ['13', 0], 'denoise': 1.0}},
        '15': {'class_type': 'VAEDecode', 'inputs': {'samples': ['14', 0], 'vae': ['3', 0]}},
        '16': {'class_type': 'SaveImage', 'inputs': {'images': ['15', 0], 'filename_prefix': prefix}},
    }


def _flux2(model, variant, prompt, seed, width, height, image_name, ram_gb, prefix):
    """FLUX.2 [klein] (CFGGuider, cfg 1) and FLUX.2 [dev] (FluxGuidance + turbo LoRA)."""
    dev = model is FLUX2_DEV
    g = {
        '1': _model_loader(variant),
        '2': {'class_type': 'CLIPLoader', 'inputs': {
            'clip_name': _shared(model, ram_gb, 'text_encoders').name, 'type': 'flux2',
            'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': _shared(model, ram_gb, 'vae').name}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': prompt}},
        '20': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': int(seed)}},
        '21': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}},
    }
    model_ref = ['1', 0]
    if dev:
        g['5'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': ['1', 0], 'lora_name': _shared(model, ram_gb, 'loras').name,
            'strength_model': 1.0}}
        model_ref = ['5', 0]
        g['6'] = {'class_type': 'FluxGuidance', 'inputs': {'conditioning': ['4', 0], 'guidance': 4.0}}
        positive = ['6', 0]
    else:
        g['6'] = {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['4', 0]}}
        positive, negative = ['4', 0], ['6', 0]
    if image_name:
        g['10'] = {'class_type': 'LoadImage', 'inputs': {'image': image_name}}
        g['11'] = {'class_type': 'ImageScaleToTotalPixels', 'inputs': {
            'image': ['10', 0], 'upscale_method': 'area' if dev else 'nearest-exact',
            'megapixels': 1.0, 'resolution_steps': 1}}
        g['12'] = {'class_type': 'GetImageSize', 'inputs': {'image': ['11', 0]}}
        g['13'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['11', 0], 'vae': ['3', 0]}}
        g['14'] = {'class_type': 'ReferenceLatent', 'inputs': {'conditioning': positive, 'latent': ['13', 0]}}
        positive = ['14', 0]
        if not dev:
            g['15'] = {'class_type': 'ReferenceLatent', 'inputs': {'conditioning': negative,
                                                                   'latent': ['13', 0]}}
            negative = ['15', 0]
        w, h = ['12', 0], ['12', 1]
    else:
        w, h = int(width), int(height)
    g['22'] = {'class_type': 'Flux2Scheduler', 'inputs': {'steps': model.steps, 'width': w, 'height': h}}
    g['23'] = {'class_type': 'EmptyFlux2LatentImage', 'inputs': {'width': w, 'height': h, 'batch_size': 1}}
    if dev:
        g['24'] = {'class_type': 'BasicGuider', 'inputs': {'model': model_ref, 'conditioning': positive}}
    else:
        g['24'] = {'class_type': 'CFGGuider', 'inputs': {'model': model_ref, 'positive': positive,
                                                         'negative': negative, 'cfg': 1.0}}
    g['25'] = {'class_type': 'SamplerCustomAdvanced', 'inputs': {
        'noise': ['20', 0], 'guider': ['24', 0], 'sampler': ['21', 0], 'sigmas': ['22', 0],
        'latent_image': ['23', 0]}}
    g['26'] = {'class_type': 'VAEDecode', 'inputs': {'samples': ['25', 0], 'vae': ['3', 0]}}
    g['27'] = {'class_type': 'SaveImage', 'inputs': {'images': ['26', 0], 'filename_prefix': prefix}}
    return g


def build(model, variant, prompt, seed, image_name=None, width=1344, height=768, ram_gb=None,
          prefix='StrokeScribe'):
    """Workflow for a task: with image_name it edits that image, otherwise it creates one."""
    if model is QWEN_EDIT:
        if not image_name:
            raise ValueError('Qwen-Image-Edit edits an image: choose an image first.')
        return qwen_edit(variant, image_name, prompt, seed, ram_gb, prefix)
    if model in (FLUX2_KLEIN, FLUX2_DEV):
        return _flux2(model, variant, prompt, seed, width, height, image_name, ram_gb, prefix)
    raise ValueError('Unknown model')


SIZES = {  # width, height (multiples of 16, about one megapixel)
    'Wide 16:9': (1344, 768), 'Landscape 4:3': (1152, 864), 'Square 1:1': (1024, 1024),
    'Portrait 3:4': (864, 1152), 'Tall 9:16': (768, 1344),
}
