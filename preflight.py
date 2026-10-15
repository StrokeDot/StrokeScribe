"""System preflight: what StrokeScribe needs, what this computer has, and where.

Pure Python (no Qt) so it can be tested headless. Nothing is downloaded or
installed here unless a caller explicitly runs pull_model() or
winget_install(); the setup window asks the user before doing either.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from urllib.request import Request, urlopen

OLLAMA_URL = 'http://127.0.0.1:11434'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# Model choices: instruct variants answer directly (plain qwen3-vl tags are
# thinking models). Sizes are Ollama's listed download sizes.
TIERS = {
    'fast': dict(label='Fast', model='qwen3-vl:2b-instruct', model_gb=1.9,
                 profile='fast', ram_gb=8,
                 summary='Quickest analysis with the smallest local AI model. '
                         'Good for simple artwork and older computers.'),
    'balanced': dict(label='Balanced', model='qwen3-vl:4b-instruct', model_gb=3.3,
                     profile='balanced', ram_gb=12,
                     summary='Recommended. Good object recognition at a moderate speed.'),
    'quality': dict(label='Quality', model='qwen3-vl:4b-instruct', model_gb=3.3,
                    profile='quality', ram_gb=12,
                    summary='Same model as Balanced, with a larger image and more '
                            'parts for detailed artwork. Slower analysis.'),
    'max': dict(label='Max', model='qwen3-vl:8b-instruct', model_gb=6.1,
                profile='quality', ram_gb=16,
                summary='Largest local model and most detailed settings. Best '
                        'recognition; needs a strong computer (a GPU helps a lot).'),
}
TIER_ORDER = ('fast', 'balanced', 'quality', 'max')

PACKAGES = (('PySide6', 'PySide6'), ('svgelements', 'svgelements'),
            ('Pillow', 'PIL'), ('numpy', 'numpy'),
            ('opencv-python-headless', 'cv2'))
ENCODERS = (('libx264', 'MP4 export'), ('libvpx-vp9', 'WebM export'),
            ('prores_ks', 'ProRes MOV export'))
WINGET_IDS = {'ffmpeg': 'Gyan.FFmpeg', 'ollama': 'Ollama.Ollama'}


@dataclass
class CheckItem:
    key: str
    name: str
    purpose: str
    status: str            # 'ok', 'missing', 'warning'
    detail: str = ''
    location: str = ''
    required: bool = True
    action: str = ''       # '', 'pull_model', 'winget_ffmpeg', 'winget_ollama', 'start_ollama'
    size_gb: float = 0.


@dataclass
class SystemInfo:
    os_name: str
    ram_total_gb: float | None
    ram_free_gb: float | None
    disk_free_gb: float | None
    disk_path: str
    gpus: list = field(default_factory=list)


# ---------- System ----------

def _windows_memory():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return status.ullTotalPhys / 2**30, status.ullAvailPhys / 2**30


def memory_gb():
    """Total and available RAM in GB, or (None, None) if unknown."""
    try:
        if sys.platform == 'win32':
            return _windows_memory()
        values = {}
        with open('/proc/meminfo') as handle:
            for line in handle:
                name, value = line.split(':', 1)
                values[name] = int(value.split()[0]) / 2**20
        return values.get('MemTotal'), values.get('MemAvailable')
    except Exception:
        return None, None


def gpus():
    """NVIDIA GPUs with memory via nvidia-smi; empty when unknown/absent."""
    tool = shutil.which('nvidia-smi')
    if not tool:
        return []
    try:
        out = subprocess.run([tool, '--query-gpu=name,memory.total',
                              '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=8,
                             creationflags=NO_WINDOW).stdout
    except Exception:
        return []
    found = []
    for line in out.strip().splitlines():
        name, _, memory = line.rpartition(',')
        try:
            found.append((name.strip(), round(float(memory) / 1024, 1)))
        except ValueError:
            continue
    return found


def models_dir():
    """Where Ollama stores models (OLLAMA_MODELS, else ~/.ollama/models)."""
    custom = os.environ.get('OLLAMA_MODELS')
    return Path(custom) if custom else Path.home() / '.ollama' / 'models'


def system_info():
    total, free = memory_gb()
    target = models_dir()
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        disk = shutil.disk_usage(probe).free / 2**30
    except OSError:
        disk = None
    return SystemInfo(f'{platform.system()} {platform.release()}', total, free,
                      disk, str(probe), gpus())


# ---------- FFmpeg ----------

def _ffmpeg_candidates():
    local = os.environ.get('LOCALAPPDATA')
    if local:
        yield Path(local) / 'Microsoft' / 'WinGet' / 'Links' / 'ffmpeg.exe'
        packages = Path(local) / 'Microsoft' / 'WinGet' / 'Packages'
        if packages.is_dir():
            yield from sorted(packages.glob('Gyan.FFmpeg*/*/bin/ffmpeg.exe'))
    for root in (os.environ.get('ProgramFiles'), 'C:\\ffmpeg'):
        if root:
            yield Path(root) / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
            yield Path(root) / 'bin' / 'ffmpeg.exe'


def find_ffmpeg():
    """ffmpeg on PATH, or in the usual Windows install places."""
    found = shutil.which('ffmpeg')
    if found:
        return found
    for candidate in _ffmpeg_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


def ensure_ffmpeg_on_path():
    """Make a freshly installed FFmpeg usable without restarting Windows.

    A new install updates PATH only for programs started afterwards. Adding
    its folder to this process lets export find it immediately.
    """
    found = find_ffmpeg()
    if found and not shutil.which('ffmpeg'):
        os.environ['PATH'] = str(Path(found).parent) + os.pathsep + os.environ.get('PATH', '')
    return found


def ffmpeg_encoders(path):
    try:
        out = subprocess.run([path, '-hide_banner', '-encoders'], capture_output=True,
                             text=True, timeout=15, creationflags=NO_WINDOW).stdout
    except Exception:
        return set()
    return {name for name, _ in ENCODERS if f' {name} ' in out}


# ---------- Ollama ----------

def find_ollama():
    found = shutil.which('ollama')
    if found:
        return found
    local = os.environ.get('LOCALAPPDATA')
    if local:
        candidate = Path(local) / 'Programs' / 'Ollama' / 'ollama.exe'
        if candidate.is_file():
            return str(candidate)
    return None


def _get_json(path, timeout=3):
    with urlopen(OLLAMA_URL + path, timeout=timeout) as response:
        return json.loads(response.read(2_000_000))


def ollama_version():
    try:
        return _get_json('/api/version').get('version')
    except Exception:
        return None


def ollama_models():
    """Installed model names with sizes in GB; None if Ollama is not reachable."""
    try:
        data = _get_json('/api/tags')
    except Exception:
        return None
    return {m.get('name', ''): round(m.get('size', 0) / 1e9, 1)
            for m in data.get('models', []) if m.get('name')}


def has_model(installed, model):
    return model in installed or (':' not in model and model + ':latest' in installed)


# ---------- Checklist ----------

def run_checks(tier='balanced'):
    """Everything this tier needs, each with status and location."""
    settings = TIERS[tier]
    items = []
    for dist, module in PACKAGES:
        try:
            version = metadata.version(dist)
            spec = __import__(module)
            where = str(Path(spec.__file__).parent) if getattr(spec, '__file__', None) else ''
            items.append(CheckItem(f'pkg:{dist}', f'{dist} {version}', 'App library',
                                   'ok', 'Installed by Setup.cmd', where))
        except Exception:
            items.append(CheckItem(f'pkg:{dist}', dist, 'App library', 'missing',
                                   'Run Setup.cmd again to install it.'))
    items.append(CheckItem('python', f'Python {platform.python_version()}', 'Runs the app',
                           'ok', '', sys.executable))

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        encoders = ffmpeg_encoders(ffmpeg)
        missing = [label for name, label in ENCODERS if name not in encoders]
        items.append(CheckItem('ffmpeg', 'FFmpeg', 'Video export (MP4, WebM, MOV)',
                               'warning' if missing else 'ok',
                               ('Missing encoders for: ' + ', '.join(missing) +
                                '. Install the full Gyan build.') if missing
                               else 'MP4, WebM and ProRes encoders available',
                               ffmpeg, action='winget_ffmpeg' if missing else ''))
    else:
        items.append(CheckItem('ffmpeg', 'FFmpeg', 'Video export (MP4, WebM, MOV)',
                               'missing', 'PNG export works without it; videos need it.',
                               action='winget_ffmpeg', size_gb=.2))

    ollama = find_ollama()
    version = ollama_version()
    if not ollama and not version:
        items.append(CheckItem('ollama', 'Ollama', 'Runs the local AI (AI redraw)',
                               'missing', 'Needed only for AI redraw. Free; runs on your PC.',
                               required=False, action='winget_ollama', size_gb=1.0))
    elif not version:
        items.append(CheckItem('ollama', 'Ollama (not running)', 'Runs the local AI (AI redraw)',
                               'warning', 'Installed but not running. It can be started for you.',
                               ollama, required=False, action='start_ollama'))
    else:
        items.append(CheckItem('ollama', f'Ollama {version}', 'Runs the local AI (AI redraw)',
                               'ok', 'Running', ollama or 'running service', required=False))

    model = settings['model']
    installed = ollama_models() if version else None
    where = str(models_dir())
    if installed is not None and has_model(installed, model):
        items.append(CheckItem('model', model, f'AI model for {settings["label"]}', 'ok',
                               f'{installed.get(model, settings["model_gb"])} GB',
                               where, required=False))
    else:
        items.append(CheckItem('model', model, f'AI model for {settings["label"]}', 'missing',
                               f'{settings["model_gb"]} GB download'
                               + ('' if version else ' (after Ollama is installed and running)'),
                               where, required=False, action='pull_model',
                               size_gb=settings['model_gb']))
    return items


def advice(info, tier):
    """Plain warnings about this computer for the chosen tier."""
    notes = []
    settings = TIERS[tier]
    # Computers sold as "8 GB" report a little less, so allow 10% slack.
    if info.ram_total_gb is not None and info.ram_total_gb < settings['ram_gb']*.9:
        notes.append(f'{settings["label"]} works best with about {settings["ram_gb"]} GB of RAM; '
                     f'this computer has {info.ram_total_gb:.0f} GB. A lower level may run better.')
    if info.disk_free_gb is not None and info.disk_free_gb < settings['model_gb'] + 2:
        notes.append(f'Only {info.disk_free_gb:.1f} GB free on the model drive; '
                     f'the AI model needs {settings["model_gb"]} GB plus working space.')
    if not info.gpus and tier == 'max':
        notes.append('No NVIDIA GPU detected. Max will run on the processor and be slow.')
    return notes


# ---------- Installing (only when the user agreed) ----------

def pull_model(model, progress=None, cancelled=lambda: False):
    """Download an Ollama model, reporting (status, completed, total)."""
    body = json.dumps({'model': model, 'stream': True}).encode()
    request = Request(OLLAMA_URL + '/api/pull', data=body,
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=60) as response:
        for line in response:
            if cancelled():
                raise InterruptedError('Download cancelled.')
            if not line.strip():
                continue
            update = json.loads(line)
            if update.get('error'):
                raise RuntimeError('Ollama: ' + str(update['error']))
            if progress:
                progress(update.get('status', ''), update.get('completed', 0),
                         update.get('total', 0))
            if update.get('status') == 'success':
                return True
    raise RuntimeError('Ollama ended the download before it finished.')


def winget_install(tool, output=None):
    """Install FFmpeg or Ollama with Windows' own package manager (winget)."""
    if sys.platform != 'win32' or not shutil.which('winget'):
        raise RuntimeError('Automatic install needs Windows with winget. Install it manually.')
    command = ['winget', 'install', '--id', WINGET_IDS[tool], '--exact', '--silent',
               '--accept-package-agreements', '--accept-source-agreements']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors='replace', creationflags=NO_WINDOW)
    for line in process.stdout:
        if output and line.strip():
            output(line.strip())
    if process.wait():
        raise RuntimeError(f'winget could not install {WINGET_IDS[tool]} (code {process.returncode}).')
    if tool == 'ffmpeg':
        ensure_ffmpeg_on_path()
    return True


def start_ollama():
    """Start the Ollama server in the background if it is installed."""
    path = find_ollama()
    if not path:
        raise RuntimeError('Ollama is not installed.')
    subprocess.Popen([path, 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=NO_WINDOW)
    return True


# ---------- Remembered choices ----------

def config_path():
    """Small JSON settings file (tier choice, show-at-startup)."""
    base = os.environ.get('STROKESCRIBE_CONFIG_DIR')
    if base:
        root = Path(base)
    elif sys.platform == 'win32' and os.environ.get('APPDATA'):
        root = Path(os.environ['APPDATA']) / 'StrokeScribe'
    else:
        root = Path.home() / '.config' / 'StrokeScribe'
    return root / 'setup.json'


def load_setup():
    try:
        data = json.loads(config_path().read_text())
    except Exception:
        data = {}
    tier = data.get('tier') if data.get('tier') in TIERS else None
    return {'tier': tier, 'show_at_startup': bool(data.get('show_at_startup', True))}


def save_setup(tier, show_at_startup):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'tier': tier, 'show_at_startup': bool(show_at_startup)}, indent=2))
