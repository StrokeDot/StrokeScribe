"""CI checks for the AI image feature (run on GitHub Actions, which has internet).

  python tools/ci_ai_check.py urls
      Every model file exists on Hugging Face with exactly the registered size,
      and the ComfyUI / ComfyUI-GGUF downloads exist.
  python tools/ci_ai_check.py workflows <ComfyUI dir> <base dir>
      Starts a real ComfyUI (CPU) with placeholder model files and submits every
      workflow StrokeScribe can build; ComfyUI must accept each one (correct
      node names, inputs and file names).
"""
import http.client
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_engine  # noqa: E402
import ai_models  # noqa: E402
from ai_workflows import LINE_ART_PROMPT, build  # noqa: E402


def all_files():
    seen = {}
    for m in ai_models.MODELS:
        for f in [v.diffusion for v in m.variants] + list(m.shared) + list(m.low_ram_shared):
            seen[f.url] = f
    return list(seen.values())


def remote_size(url):
    parsed = urllib.parse.urlparse(url)
    for _ in range(5):
        conn = http.client.HTTPSConnection(parsed.netloc, timeout=60)
        conn.request('HEAD', parsed.path, headers={'User-Agent': 'StrokeScribe-CI'})
        r = conn.getresponse()
        linked = r.getheader('X-Linked-Size')
        if linked:
            return r.status, int(linked)
        if r.status in (301, 302, 303, 307, 308):
            location = r.getheader('Location')
            parsed = urllib.parse.urlparse(urllib.parse.urljoin(url, location))
            continue
        return r.status, int(r.getheader('Content-Length') or -1)
    return 0, -1


def check_urls():
    problems = []
    for f in all_files():
        status, size = remote_size(f.url)
        ok = status in (200, 302) and size == f.size
        print(('OK  ' if ok else 'BAD ') + f'{f.name}: status {status}, size {size} (expected {f.size})')
        if not ok:
            problems.append(f.name)
    for url in (ai_engine.COMFY_ZIP, ai_engine.GGUF_ZIP):
        request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'StrokeScribe-CI'})
        with urllib.request.urlopen(request, timeout=60) as r:
            print('OK  ' + url, r.status)
    if problems:
        sys.exit('Missing or changed model files: ' + ', '.join(problems))


def check_workflows(comfy, base):
    comfy, base = Path(comfy), Path(base)
    for f in all_files():
        target = base / 'models' / f.folder / f.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'0')
    (base / 'input').mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.new('RGB', (64, 48), 'white').save(base / 'input' / 'in.png')
    port = 8199
    proc = subprocess.Popen([sys.executable, str(comfy / 'main.py'), '--cpu', '--listen', '127.0.0.1',
                             '--port', str(port), '--base-directory', str(base),
                             '--disable-auto-launch'], cwd=str(comfy))
    try:
        for _ in range(240):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/system_stats', timeout=5)
                break
            except Exception:
                if proc.poll() is not None:
                    sys.exit('ComfyUI did not start')
                time.sleep(1)
        info = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/object_info/UnetLoaderGGUF').read())
        assert 'UnetLoaderGGUF' in info, 'ComfyUI-GGUF custom node not loaded'
        count = 0
        for model in ai_models.MODELS:
            if 'sound' in model.tasks:
                for variant in model.variants:
                    wf = build(model, variant, 'pencil on paper', 1, seconds=4)
                    body = json.dumps({'prompt': wf, 'client_id': 'ci'}).encode()
                    req = urllib.request.Request(f'http://127.0.0.1:{port}/prompt', data=body,
                                                 headers={'Content-Type': 'application/json'})
                    try:
                        reply = json.loads(urllib.request.urlopen(req, timeout=30).read())
                    except urllib.error.HTTPError as exc:
                        sys.exit(f'{model.id}/{variant.id}: rejected: ' + exc.read().decode()[:2000])
                    assert reply.get('prompt_id') and not reply.get('node_errors'), reply
                    count += 1
                    print(f'OK  {model.id} {variant.id} sound')
                continue
            for variant in model.variants:
                for ram in (16, 128):
                    for image in ((None, 'in.png') if 'generate' in model.tasks else ('in.png',)):
                        wf = build(model, variant, LINE_ART_PROMPT, 1, image_name=image, ram_gb=ram)
                        body = json.dumps({'prompt': wf, 'client_id': 'ci'}).encode()
                        req = urllib.request.Request(f'http://127.0.0.1:{port}/prompt', data=body,
                                                     headers={'Content-Type': 'application/json'})
                        try:
                            reply = json.loads(urllib.request.urlopen(req, timeout=30).read())
                        except urllib.error.HTTPError as exc:
                            sys.exit(f'{model.id}/{variant.id}/{image}: rejected: '
                                     + exc.read().decode()[:2000])
                        assert reply.get('prompt_id') and not reply.get('node_errors'), reply
                        count += 1
                        print(f'OK  {model.id} {variant.id} {"edit" if image else "generate"} ram={ram}')
        urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/queue', method='POST',
                               data=b'{"clear": true}', headers={'Content-Type': 'application/json'}))
        print(f'{count} workflows accepted by ComfyUI {ai_engine.COMFY_VERSION}')
    finally:
        proc.terminate()


if __name__ == '__main__':
    if sys.argv[1] == 'urls':
        check_urls()
    else:
        check_workflows(sys.argv[2], sys.argv[3])
