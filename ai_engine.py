"""Local AI image engine: installs and runs ComfyUI in the background.

Nothing here runs unless the user installs the engine from the Create Image
window. Everything lives in one folder the user can choose (models are big):

    <root>/venv            Python environment with PyTorch (CUDA) for the engine
    <root>/ComfyUI         ComfyUI, pinned release
    <root>/data/models     model files (diffusion_models, text_encoders, vae, loras)
    <root>/data/custom_nodes/ComfyUI-GGUF   loader for compressed (GGUF) models
    <root>/data/input, output

The engine is started as a hidden local server (127.0.0.1 only) when an image
is requested, and stopped with the app.
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

COMFY_VERSION = 'v0.41.1'
COMFY_ZIP = f'https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/{COMFY_VERSION}.zip'
GGUF_COMMIT = '6ea2651e7df66d7585f6ffee804b20e92fb38b8a'
GGUF_ZIP = f'https://github.com/city96/ComfyUI-GGUF/archive/{GGUF_COMMIT}.zip'
TORCH_INDEX = {'nvidia': 'https://download.pytorch.org/whl/cu130',
               'cpu': 'https://download.pytorch.org/whl/cpu'}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


# ---------------------------------------------------------------- settings

def _settings_path():
    from preflight import config_path
    return config_path().parent / 'ai_engine.json'


def default_root():
    if sys.platform == 'win32' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'StrokeScribe' / 'ai-engine'
    return Path.home() / '.local' / 'share' / 'StrokeScribe' / 'ai-engine'


def load_settings():
    try:
        data = json.loads(_settings_path().read_text())
    except Exception:
        data = {}
    data.setdefault('root', str(default_root()))
    data.setdefault('accepted_licenses', [])
    data.setdefault('variant_override', {})
    return data


def save_settings(data):
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class Paths:
    def __init__(self, root=None):
        self.root = Path(root or load_settings()['root'])
        self.venv = self.root / 'venv'
        self.comfy = self.root / 'ComfyUI'
        self.data = self.root / 'data'
        self.models = self.data / 'models'
        self.custom_nodes = self.data / 'custom_nodes'
        self.input = self.data / 'input'
        self.output = self.data / 'output'
        self.marker = self.root / 'engine.json'

    @property
    def python(self):
        return self.venv / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')

    def model_path(self, model_file):
        return self.models / model_file.folder / model_file.name

    def engine_installed(self):
        try:
            info = json.loads(self.marker.read_text())
        except Exception:
            return False
        return (info.get('comfy') == COMFY_VERSION and self.python.is_file()
                and (self.comfy / 'main.py').is_file())

    def has_files(self, files):
        return all(self.model_path(f).is_file() and self.model_path(f).stat().st_size == f.size
                   for f in files)


# ---------------------------------------------------------------- downloads

class Cancelled(Exception):
    pass


CONNECTIONS = 8                  # parallel connections for a big model file
SEGMENT = 32 << 20               # bytes per piece (each piece is resumable)
BLOCK = 256 << 10                # read size: small, so Cancel works within a moment
SOCKET_TIMEOUT = 20              # seconds without data before a connection is retried
PARALLEL_FROM = 64 << 20         # files smaller than this use one connection
RETRIES = []                     # (file, piece, problem) of the last downloads, for the engine log


def _open(url, start=None, end=None, timeout=SOCKET_TIMEOUT):
    request = urllib.request.Request(url, headers={'User-Agent': 'StrokeScribe'})
    if start is not None:
        request.add_header('Range', f'bytes={start}-{"" if end is None else end}')
    return urllib.request.urlopen(request, timeout=timeout)


def download(url, target, size=None, progress=None, cancelled=lambda: False, connections=None):
    """Download with resume, progress(done, total) and size check.

    Big files with a known size are fetched in pieces over several connections
    at once (much faster where one connection is slowed down, as with Hugging
    Face from some countries); finished pieces are remembered in <name>.part.json,
    so a stopped download continues where it stopped."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if size and target.is_file() and target.stat().st_size == size:
        if progress:
            progress(size, size)
        return target
    part = target.with_name(target.name + '.part')
    connections = CONNECTIONS if connections is None else connections
    if size and size >= PARALLEL_FROM and connections > 1:
        try:
            final = _resolve(url)
        except Cancelled:
            raise
        except Exception:
            final = None
        if final:
            _download_pieces(final, url, part, size, progress, cancelled, connections)
            part.replace(target)
            return target
    _download_single(url, part, size, progress, cancelled)
    if size and part.stat().st_size != size:
        raise RuntimeError(f'{target.name} is incomplete ({part.stat().st_size} of {size} bytes). '
                           'Try again to resume.')
    part.replace(target)
    return target


def _resolve(url):
    """The file's real address after redirects, if the server sends pieces (Range); else None."""
    with _open(url, 0, 0) as response:
        if response.status != 206:
            return None
        return response.geturl()


def _download_single(url, part, size, progress, cancelled):
    done = part.stat().st_size if part.is_file() else 0
    if size and done > size:
        part.unlink(); done = 0
    sidecar = part.with_name(part.name + '.json')
    if sidecar.is_file():                       # pieces of a parallel download: start again
        sidecar.unlink(); part.unlink(missing_ok=True); done = 0
    try:
        response = _open(url, done if done else None, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and size and done == size:     # already complete
            return
        raise RuntimeError(f'Download failed ({exc.code}) for {url}') from exc
    with response:
        if done and response.status != 206:                # server ignored the resume
            done = 0
        total = size or (done + int(response.headers.get('Content-Length') or 0)) or None
        with open(part, 'ab' if done else 'wb') as out:
            while True:
                if cancelled():
                    raise Cancelled('Download paused; it continues where it stopped next time.')
                block = response.read(BLOCK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress:
                    progress(done, total)


MIN_SPLIT = 4 << 20              # a piece is shared with an idle connection only if this much is left


def _merge(ranges):
    out = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _missing(done, size):
    gaps, at = [], 0
    for a, b in _merge(done):
        if a > at:
            gaps.append([at, a - 1])
        at = max(at, b + 1)
    if at < size:
        gaps.append([at, size - 1])
    return gaps


def _download_pieces(final, original, part, size, progress, cancelled, connections):
    """Fetch [0, size) in pieces over several connections.

    Pieces wait in a queue. When the queue is empty, an idle connection takes the
    second half of the piece with the most bytes left (one slow connection must not
    keep the whole file waiting). Downloaded byte ranges are saved in the .part.json
    file, so a stopped download continues where it stopped."""
    import threading
    from collections import deque
    sidecar = part.with_name(part.name + '.json')
    done = []
    if part.is_file():
        try:
            info = json.loads(sidecar.read_text())
            if info.get('size') == size and 'ranges' in info:
                done = [list(r) for r in info['ranges']]
            elif info.get('size') == size and 'done' in info:          # pieces of exp.46
                seg = int(info.get('segment') or SEGMENT)
                done = [[i * seg, min(size, (i + 1) * seg) - 1] for i in info['done']]
        except Exception:
            have = part.stat().st_size                 # an older one-connection download
            done = [[0, min(have, size) - 1]] if have else []
    with open(part, 'r+b' if part.is_file() else 'w+b') as f:
        f.truncate(size)
    todo = deque()
    for a, b in _missing(done, size):
        for x in range(a, b + 1, SEGMENT):
            todo.append([x, min(b, x + SEGMENT - 1)])
    lock = threading.Lock()
    stop = threading.Event()
    state = dict(url=final, error=None, failures=0)
    active = {}                                       # id -> {'start', 'pos', 'end', 'response'}

    def save():
        sidecar.write_text(json.dumps(dict(size=size, ranges=_merge(done))))

    def next_piece():
        with lock:
            if todo:
                return todo.popleft()
            # Share the slowest remaining piece.
            best = max(active.values(), key=lambda e: e['end'] - e['pos'], default=None)
            if best is None or best['end'] - best['pos'] + 1 < 2 * MIN_SPLIT:
                return None
            mid = (best['pos'] + best['end']) // 2
            piece = [mid + 1, best['end']]
            best['end'] = mid
            return piece

    def fetch(a, b, out, key):
        entry = dict(start=a, pos=a, end=b, response=None)
        with lock:
            active[key] = entry
        try:
            response = _open(state['url'], a, b)
            entry['response'] = response
            with response:
                if response.status != 206:
                    raise RuntimeError('The server stopped sending pieces.')
                while not stop.is_set():
                    block = response.read(BLOCK)
                    if not block:
                        break
                    with lock:
                        pos, end = entry['pos'], entry['end']
                        take = max(0, min(len(block), end - pos + 1))
                        entry['pos'] = pos + take
                    if take:
                        out.seek(pos)
                        out.write(block[:take])
                    if pos + take > end:
                        break                          # this piece (maybe shortened) is complete
            if stop.is_set():
                return
            if entry['pos'] <= entry['end']:
                raise RuntimeError('A piece of the download was cut off.')
        except Exception as exc:
            if stop.is_set():
                return
            with lock:
                state['failures'] += 1
                failures = state['failures']
                if entry['pos'] <= entry['end']:
                    todo.append([entry['pos'], entry['end']])      # the rest, again later
            RETRIES.append((part.name, a, f'{type(exc).__name__}: {exc}'[:160]))
            del RETRIES[:-50]
            if failures > 12:
                state['error'] = exc
                stop.set()
                return
            if getattr(exc, 'code', None) in (401, 403, 404, 410):  # the signed address expired
                try:
                    state['url'] = _resolve(original) or state['url']
                except Exception:
                    pass
            stop.wait(min(20, 1.5 ** failures))
        finally:
            with lock:
                active.pop(key, None)
                if entry['pos'] > entry['start']:
                    done.append([entry['start'], entry['pos'] - 1])

    def worker(n):
        with open(part, 'r+b') as out:
            while not stop.is_set():
                piece = next_piece()
                if piece is None:
                    with lock:
                        busy = bool(active) or bool(todo)
                    if not busy:
                        return
                    stop.wait(.2)                     # maybe a failed piece comes back
                    continue
                fetch(piece[0], piece[1], out, (n, piece[0]))

    count = max(1, min(connections, len(todo) * 2 or 1))
    threads = [threading.Thread(target=worker, args=(n,), daemon=True) for n in range(count)]
    for t in threads:
        t.start()

    def received():
        with lock:
            return sum(b - a + 1 for a, b in _merge(done)) + sum(e['pos'] - e['start'] for e in active.values())
    try:
        while any(t.is_alive() for t in threads):
            if cancelled():
                stop.set()
                with lock:
                    responses = [e['response'] for e in active.values() if e['response'] is not None]
                for response in responses:
                    try:
                        response.close()               # wakes a connection that waits for data
                    except Exception:
                        pass
                for t in threads:
                    t.join(2)
                with lock:
                    save()
                raise Cancelled('Download paused; it continues where it stopped next time.')
            if progress:
                progress(received(), size)
            time.sleep(.25)
    finally:
        stop.set()
    with lock:
        save()
        missing = _missing(done, size)
    if state['error'] is not None:
        raise RuntimeError(f'Download failed for {part.name[:-5]}: {state["error"]}. '
                           'Try again: it continues where it stopped.')
    if missing:
        raise RuntimeError(f'{part.name[:-5]} is incomplete. Try again: it continues where it stopped.')
    if progress:
        progress(size, size)
    sidecar.unlink(missing_ok=True)


def free_space_gb(path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return None


# ---------------------------------------------------------------- installing the engine

def _run(cmd, log, cancelled, cwd=None):
    """Run a command, streaming its output lines to log(); raise on failure."""
    log('> ' + ' '.join(str(c) for c in cmd))
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors='replace',
                            creationflags=NO_WINDOW)
    for line in proc.stdout:
        log(line.rstrip())
        if cancelled():
            proc.terminate()
            raise Cancelled('Installation cancelled.')
    if proc.wait() != 0:
        raise RuntimeError(f'Step failed: {Path(str(cmd[0])).name} {" ".join(map(str, cmd[1:3]))}')


def _base_python():
    exe = Path(getattr(sys, '_base_executable', None) or sys.executable)
    if exe.name.lower() == 'pythonw.exe' and (exe.parent / 'python.exe').is_file():
        exe = exe.parent / 'python.exe'          # the installed app runs windowless
    return str(exe)


def _extract_zip(data, target, strip_top=True):
    """Validate every ComfyUI member and CRC before replacing the old engine."""
    from archive_safety import validate_archive
    target = Path(target)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        prefix = ''
        if strip_top:
            roots = {info.filename.split('/', 1)[0]
                     for info in archive.infolist() if info.filename}
            if len(roots) != 1:
                raise ValueError('ComfyUI ZIP must have one enclosing folder.')
            prefix = next(iter(roots)) + '/'
        files = validate_archive(archive, target, prefix=prefix,
                                 max_files=60000, max_bytes=4 * 1024 ** 3)
        if not files:
            raise ValueError('ComfyUI ZIP contains no installable files.')
        bad = archive.testzip()
        if bad is not None:
            raise ValueError('ComfyUI ZIP is damaged at ' + bad)
        # No deletion before preflight. The staged/atomic extraction upgrade
        # is handled separately by the interrupted-installation phase.
        if target.exists():
            shutil.rmtree(target)
        for member, _, out in files:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(member))


def _fetch(url, log):
    log('Downloading ' + url)
    request = urllib.request.Request(url, headers={'User-Agent': 'StrokeScribe'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def install_engine(paths, nvidia=True, log=print, step=lambda i, n, text: None,
                   cancelled=lambda: False):
    """Create the engine (about 4-5 GB). Safe to run again to repair."""
    steps = ['Creating the engine environment', 'Installing PyTorch (graphics card support)',
             'Downloading ComfyUI ' + COMFY_VERSION, 'Installing ComfyUI parts',
             'Adding the compressed-model (GGUF) loader', 'Finishing']
    n = len(steps)
    for folder in (paths.models, paths.custom_nodes, paths.input, paths.output):
        folder.mkdir(parents=True, exist_ok=True)
    step(0, n, steps[0])
    if not paths.python.is_file():
        _run([_base_python(), '-m', 'venv', paths.venv], log, cancelled)
    _run([paths.python, '-m', 'pip', 'install', '--upgrade', 'pip'], log, cancelled)
    step(1, n, steps[1])
    _run([paths.python, '-m', 'pip', 'install', 'torch', 'torchvision', 'torchaudio',
          '--index-url', TORCH_INDEX['nvidia' if nvidia else 'cpu']], log, cancelled)
    step(2, n, steps[2])
    _extract_zip(_fetch(COMFY_ZIP, log), paths.comfy)
    step(3, n, steps[3])
    _run([paths.python, '-m', 'pip', 'install', '-r', paths.comfy / 'requirements.txt'], log, cancelled)
    step(4, n, steps[4])
    _extract_zip(_fetch(GGUF_ZIP, log), paths.custom_nodes / 'ComfyUI-GGUF')
    _run([paths.python, '-m', 'pip', 'install', 'gguf>=0.13.0', 'sentencepiece', 'protobuf'],
         log, cancelled)
    step(5, n, steps[5])
    paths.marker.write_text(json.dumps({'comfy': COMFY_VERSION, 'gguf': GGUF_COMMIT,
                                        'nvidia': bool(nvidia), 'installed': time.time()}))
    log('The AI engine is installed.')


def download_model(paths, files, progress=lambda done, total, name: None, cancelled=lambda: False):
    """Download every missing file of a model version (resumable)."""
    total = sum(f.size for f in files)
    base = 0
    for f in files:
        target = paths.model_path(f)
        download(f.url, target, f.size, lambda done, _t, f=f, base=base:
                 progress(base + done, total, f.name), cancelled)
        base += f.size


# ---------------------------------------------------------------- running the engine

def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Engine:
    """A hidden local ComfyUI server for this app session."""

    PROGRESS = re.compile(r'(\d{1,3})%\|')

    def __init__(self, paths=None, log=None):
        self.paths = paths or Paths()
        self.proc = None
        self.port = None
        self.percent = None
        self.log_lines = []
        self.log = log or (lambda line: None)

    # -- server
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, timeout=240, cancelled=lambda: False):
        if self.running():
            return
        if not self.paths.engine_installed():
            raise RuntimeError('The AI engine is not installed yet.')
        self.port = _free_port()
        cmd = [str(self.paths.python), str(self.paths.comfy / 'main.py'), '--listen', '127.0.0.1',
               '--port', str(self.port), '--base-directory', str(self.paths.data),
               '--disable-auto-launch', '--preview-method', 'none']
        self.proc = subprocess.Popen(cmd, cwd=str(self.paths.comfy), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors='replace',
                                     creationflags=NO_WINDOW)
        import threading
        threading.Thread(target=self._read_output, daemon=True).start()
        started = time.time()
        while time.time() - started < timeout:
            if cancelled():
                self.stop(); raise Cancelled('Cancelled.')
            if self.proc.poll() is not None:
                raise RuntimeError('The AI engine stopped while starting:\n' + '\n'.join(self.log_lines[-15:]))
            try:
                self._get('/system_stats')
                return
            except Exception:
                time.sleep(1)
        self.stop()
        raise RuntimeError('The AI engine did not start in time.')

    def _read_output(self):
        for line in self.proc.stdout:
            line = line.rstrip()
            self.log_lines = (self.log_lines + [line])[-200:]
            match = self.PROGRESS.search(line)
            if match:
                self.percent = int(match.group(1))
            self.log(line)

    def stop(self):
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    # -- HTTP
    def _url(self, path):
        return f'http://127.0.0.1:{self.port}{path}'

    def _get(self, path):
        with urllib.request.urlopen(self._url(path), timeout=10) as r:
            return json.loads(r.read() or b'{}')

    def _post(self, path, payload):
        request = urllib.request.Request(self._url(path), data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=30) as r:
                return json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')
            raise RuntimeError('The AI engine rejected the request: ' + detail[:600]) from exc

    # -- jobs
    def put_input(self, image_path):
        """Copy an input image where ComfyUI's LoadImage finds it."""
        self.paths.input.mkdir(parents=True, exist_ok=True)
        name = f'strokescribe_{uuid.uuid4().hex[:10]}.png'
        from PIL import Image, ImageOps
        with Image.open(image_path) as im:
            im = ImageOps.exif_transpose(im).convert('RGBA')   # same orientation as the import
            flat = Image.new('RGB', im.size, 'white')
            flat.paste(im, mask=im.getchannel('A'))       # models expect no transparency
            flat.save(self.paths.input / name)
        return name

    def run(self, workflow, timeout=3600, cancelled=lambda: False):
        """Queue a workflow and return the path of the first saved image (or sound)."""
        self.percent = 0
        reply = self._post('/prompt', {'prompt': workflow, 'client_id': 'strokescribe'})
        if reply.get('node_errors'):
            raise RuntimeError('The AI engine rejected the workflow: ' + json.dumps(reply['node_errors'])[:600])
        prompt_id = reply['prompt_id']
        started = time.time()
        while time.time() - started < timeout:
            if cancelled():
                try:
                    self._post('/interrupt', {})
                finally:
                    raise Cancelled('Image generation cancelled.')
            if not self.running():
                raise RuntimeError('The AI engine stopped:\n' + '\n'.join(self.log_lines[-15:]))
            history = self._get('/history/' + prompt_id)
            entry = history.get(prompt_id)
            if entry:
                status = entry.get('status', {})
                if status.get('status_str') == 'error':
                    messages = [m for m in status.get('messages', []) if m and m[0] == 'execution_error']
                    detail = messages[0][1].get('exception_message', '') if messages else ''
                    raise RuntimeError('The AI engine failed: ' + (detail or 'see the engine log')[:600])
                for output in entry.get('outputs', {}).values():
                    for image in output.get('images', []) + output.get('audio', []):
                        return self.paths.output / image.get('subfolder', '') / image['filename']
                if status.get('completed'):
                    raise RuntimeError('The AI engine finished without an image.')
            time.sleep(.7)
        raise RuntimeError('Image generation took too long.')


def new_seed():
    return random.randint(1, 2**48)
