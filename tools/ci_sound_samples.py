"""Real test of Create sound: download Stable Audio 3 Small-SFX, run it on the CPU
with ComfyUI exactly as the app does, and save sample sounds to listen to.

    python tools/ci_sound_samples.py <ComfyUI dir> <base dir> <output dir>

Fails if the model files do not download with the registered sizes, if ComfyUI
rejects or fails the workflow, or if a sound comes out silent.
"""
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ai_engine  # noqa: E402
import ai_models  # noqa: E402
import numpy as np  # noqa: E402
from ai_workflows import SOUND_PROMPTS, build  # noqa: E402
import sound  # noqa: E402

SAMPLES = [('pencil-1', 'Pencil', 11), ('pencil-2', 'Pencil', 222), ('brush', 'Brush', 33), ('eraser', 'Eraser', 44)]
SECONDS = 8


def main(comfy, base, out):
    comfy, base, out = Path(comfy), Path(base), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    model = ai_models.STABLE_AUDIO_SFX
    variant = model.variants[0]
    for f in model.files(variant):
        target = base / 'models' / f.folder / f.name
        started = time.time()
        ai_engine.download(f.url, target, f.size)
        print(f'downloaded {f.name} ({f.size / 1e9:.2f} GB) in {time.time() - started:.0f} s', flush=True)
    port = 8198
    proc = subprocess.Popen([sys.executable, str(comfy / 'main.py'), '--cpu', '--listen', '127.0.0.1',
                             '--port', str(port), '--base-directory', str(base), '--disable-auto-launch'],
                            cwd=str(comfy))
    lines = []
    try:
        for _ in range(300):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/system_stats', timeout=5)
                break
            except Exception:
                if proc.poll() is not None:
                    sys.exit('ComfyUI did not start')
                time.sleep(1)
        for name, kind, seed in SAMPLES:
            wf = build(model, variant, SOUND_PROMPTS[kind], seed, seconds=SECONDS)
            body = json.dumps({'prompt': wf, 'client_id': 'ci'}).encode()
            req = urllib.request.Request(f'http://127.0.0.1:{port}/prompt', data=body,
                                         headers={'Content-Type': 'application/json'})
            reply = json.loads(urllib.request.urlopen(req, timeout=60).read())
            prompt_id = reply['prompt_id']
            started = time.time()
            path = None
            while time.time() - started < 1800:
                entry = json.loads(urllib.request.urlopen(
                    f'http://127.0.0.1:{port}/history/{prompt_id}', timeout=30).read()).get(prompt_id)
                if entry:
                    status = entry.get('status', {})
                    if status.get('status_str') == 'error':
                        sys.exit(f'{name}: generation failed: {json.dumps(status)[:3000]}')
                    for output in entry.get('outputs', {}).values():
                        for item in output.get('audio', []):
                            path = base / 'output' / item.get('subfolder', '') / item['filename']
                    if path or status.get('completed'):
                        break
                time.sleep(2)
            if not path or not path.is_file():
                sys.exit(f'{name}: no sound was saved')
            took = time.time() - started
            target = out / f'{name}{path.suffix}'
            shutil.copy(path, target)
            if shutil.which('ffmpeg'):
                subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(target), '-b:a', '192k',
                                str(out / f'{name}.mp3')], check=True)
            data = sound.load_recording(target)
            if data is None:
                sys.exit(f'{name}: the sound is silent or unreadable')
            spectrum = np.abs(np.fft.rfft(data[:sound.RATE * 4]))
            freqs = np.fft.rfftfreq(min(len(data), sound.RATE * 4), 1 / sound.RATE)
            centroid = float((spectrum * freqs).sum() / max(1e-9, spectrum.sum()))
            rms = float(np.sqrt(np.mean(data ** 2)))
            line = (f'{name}: {kind}, seed {seed}, {len(data) / sound.RATE:.1f} s after trimming, '
                    f'loudness {rms:.3f}, brightness {centroid:.0f} Hz, made in {took:.0f} s on the CPU')
            print(line, flush=True)
            lines.append(line)
            if rms < .003:
                sys.exit(f'{name}: almost silent')
    finally:
        proc.terminate()
    (out / 'samples.txt').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main(*sys.argv[1:4])
