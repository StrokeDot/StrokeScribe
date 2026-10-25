"""System preflight: what StrokeScribe needs, what this computer has, and where.

Pure Python (no Qt) so it can be tested headless. Nothing is installed here
unless a caller explicitly runs winget_install(); the setup window asks the
user first.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
APP_DIR = Path(__file__).resolve().parent
LINE_MODEL = APP_DIR / 'models' / 'teed.onnx'

# Each level sets the Line art detail used for imported images.
TIERS = {
    'fast': dict(label='Fast', detail='low',
                 summary='Fewest lines and quickest preparation. Good for simple '
                         'artwork, icons and older computers.'),
    'balanced': dict(label='Balanced', detail='medium',
                     summary='Recommended. Clean outlines plus the main inner details.'),
    'quality': dict(label='Quality', detail='high',
                    summary='More inner lines and finer details for detailed artwork.'),
    'max': dict(label='Max', detail='max',
                summary='The most lines and finest detail. Takes a little longer to '
                        'prepare; best for large, detailed images.'),
}
TIER_ORDER = ('fast', 'balanced', 'quality', 'max')

PACKAGES = (('PySide6', 'PySide6'), ('svgelements', 'svgelements'),
            ('Pillow', 'PIL'), ('numpy', 'numpy'),
            ('opencv-python-headless', 'cv2'), ('onnxruntime', 'onnxruntime'))
ENCODERS = (('libx264', 'MP4 export'), ('libvpx-vp9', 'WebM export'),
            ('prores_ks', 'ProRes MOV export'))
WINGET_IDS = {'ffmpeg': 'Gyan.FFmpeg'}


@dataclass
class CheckItem:
    key: str
    name: str
    purpose: str
    status: str            # 'ok', 'missing', 'warning'
    detail: str = ''
    location: str = ''
    required: bool = True
    action: str = ''       # '' or 'winget_ffmpeg'
    size_gb: float = 0.


@dataclass
class SystemInfo:
    os_name: str
    ram_total_gb: float | None
    ram_free_gb: float | None
    disk_free_gb: float | None
    disk_path: str


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


def system_info():
    total, free = memory_gb()
    target = Path.home()
    try:
        disk = shutil.disk_usage(target).free / 2**30
    except OSError:
        disk = None
    return SystemInfo(f'{platform.system()} {platform.release()}', total, free,
                      disk, str(target))


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


# ---------- Checklist ----------

def run_checks(tier='balanced'):
    """Everything StrokeScribe needs, each with status and location."""
    TIERS[tier]  # validate
    items = []
    for dist, module in PACKAGES:
        try:
            from importlib import metadata      # exp.120: only when asked (faster start)
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
    if LINE_MODEL.is_file():
        items.append(CheckItem('line_model', 'Line art model (TEED)', 'Draws lines from images',
                               'ok', f'{LINE_MODEL.stat().st_size // 1024} KB, built in',
                               str(LINE_MODEL)))
    else:
        items.append(CheckItem('line_model', 'Line art model (TEED)', 'Draws lines from images',
                               'missing', 'Extract the full StrokeScribe ZIP again; '
                               'the models folder is missing.', str(LINE_MODEL)))

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
    return items


def advice(info, tier):
    """Plain warnings about this computer."""
    notes = []
    if info.disk_free_gb is not None and info.disk_free_gb < 2:
        notes.append(f'Only {info.disk_free_gb:.1f} GB free on {info.disk_path}; video '
                     'exports need space for their frames.')
    return notes


# ---------- Installing (only when the user agreed) ----------

def winget_install(tool, output=None):
    """Install FFmpeg with Windows' own package manager (winget)."""
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


# ---------- Remembered choices ----------

def config_path():
    """Small JSON settings file (level choice, show-at-startup)."""
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
