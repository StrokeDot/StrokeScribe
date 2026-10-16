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


def _download_pieces(final, original, part, size, progress, cancelled, connections):
    import threading
    pieces = [(i, a, min(size, a + SEGMENT) - 1) for i, a in enumerate(range(0, size, SEGMENT))]
    sidecar = part.with_name(part.name + '.json')
    finished = set()
    if part.is_file():
        try:
            info = json.loads(sidecar.read_text())
            if info.get('size') == size and info.get('segment') == SEGMENT:
                finished = set(info.get('done', []))
        except Exception:
            # An older one-connection download: the start of the file is already there.
            have = part.stat().st_size
            finished = {i for i, a, b in pieces if b < have}
    mode = 'r+b' if part.is_file() else 'w+b'
    with open(part, mode) as f:
        f.truncate(size)
    lock = threading.Lock()
    state = dict(url=final, error=None, live={}, progress={})
    stop = threading.Event()
    todo = [p for p in pieces if p[0] not in finished]

    def save():
        sidecar.write_text(json.dumps(dict(size=size, segment=SEGMENT, done=sorted(finished))))

    def fetch(piece, out):
        i, a, b = piece
        tries = 0
        while not stop.is_set():
            got = 0
            try:
                response = _open(state['url'], a, b)
                with lock:
                    state['live'][i] = response
                with response:
                    if response.status != 206:
                        raise RuntimeError('The server stopped sending pieces.')
                    out.seek(a)
                    while not stop.is_set():
                        block = response.read(BLOCK)
                        if not block:
                            break
                        out.write(block)
                        got += len(block)
                        with lock:
                            state['progress'][i] = got
                if stop.is_set():
                    return
                if got != b - a + 1:
                    raise RuntimeError('A piece of the download was cut off.')
                with lock:
                    finished.add(i); state['progress'].pop(i, None); state['live'].pop(i, None)
                    save()
                return
            except Exception as exc:
                with lock:
                    state['live'].pop(i, None); state['progress'].pop(i, None)
                if stop.is_set():
                    return
                tries += 1
                if tries > 6:
                    state['error'] = exc
                    stop.set(); return
                code = getattr(exc, 'code', None)
                if code in (401, 403, 404, 410):              # the signed address expired: ask again
                    try:
                        state['url'] = _resolve(original) or state['url']
                    except Exception:
                        pass
                stop.wait(min(30, 2 ** tries))

    def worker():
        with open(part, 'r+b') as out:
            while not stop.is_set():
                with lock:
                    if not todo:
                        return
                    piece = todo.pop(0)
                fetch(piece, out)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(connections, len(todo))))]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            if cancelled():
                stop.set()
                with lock:
                    for response in list(state['live'].values()):
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
                with lock:
                    done = sum(min(SEGMENT, size - i * SEGMENT) for i in finished) + sum(state['progress'].values())
                progress(done, size)
            for t in threads:
                t.join(.25)
                break
    finally:
        stop.set()
    if state['error'] is not None:
        with lock:
            save()
        raise RuntimeError(f'Download failed for {part.name[:-5]}: {state["error"]}. '
                           'Try again: it continues where it stopped.')
    if len(finished) != len(pieces):
        save()
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
    target = Path(target)
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            name = member.filename.split('/', 1)[1] if strip_top and '/' in member.filename else member.filename
            if not name or member.is_dir():
                continue
            out = target / name
            if not str(out.resolve()).startswith(str(target.resolve())):
                continue                                   # never write outside the folder
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
