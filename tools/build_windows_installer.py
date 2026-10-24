"""Prepare everything the Windows installer contains (run on Windows, by CI).

    python tools/build_windows_installer.py

Makes build/stage/:
    the app files (the same files as the ZIP package),
    runtime/   a complete private Python (python.org's official NuGet build)
               with StrokeScribe's packages already installed,
so the installed StrokeScribe needs nothing else: no Python, no Setup.cmd.
Then Inno Setup (installer/StrokeScribe.iss) turns build/stage into
dist/StrokeScribe-Setup-<version>.exe.
"""
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PYTHON_VERSION = '3.12.10'
PYTHON_NUPKG = f'https://api.nuget.org/v3-flatcontainer/python/{PYTHON_VERSION}/python.{PYTHON_VERSION}.nupkg'
STAGE = ROOT / 'build' / 'stage'


def run(*cmd):
    print('>', ' '.join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def main():
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    # App files: exactly what the ZIP package contains.
    from package_prototype import SOURCE_FILES
    for path in sorted(set(SOURCE_FILES)):
        target = STAGE / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(ROOT / 'assets' / 'strokescribe.ico', STAGE / 'assets' / 'strokescribe.ico')
    # Private Python.
    print('Downloading Python', PYTHON_VERSION, flush=True)
    data = urllib.request.urlopen(PYTHON_NUPKG, timeout=300).read()
    runtime = STAGE / 'runtime'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            if not member.filename.startswith('tools/') or member.is_dir():
                continue
            out = runtime / member.filename[len('tools/'):]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(member))
    python = runtime / 'python.exe'
    run(python, '-m', 'ensurepip', '--upgrade')
    run(python, '-m', 'pip', 'install', '--upgrade', '--no-warn-script-location', 'pip')
    run(python, '-m', 'pip', 'install', '--only-binary=:all:', '--no-warn-script-location',
        '-r', ROOT / 'requirements.txt')
    run(python, '-c', 'import PySide6.QtWidgets, PySide6.QtMultimedia, numpy, cv2, onnxruntime, PIL, '
                      'svgelements; print("packages OK")')
    for cache in runtime.rglob('__pycache__'):
        shutil.rmtree(cache, ignore_errors=True)
    size = sum(p.stat().st_size for p in STAGE.rglob('*') if p.is_file())
    print(f'Stage ready: {size / 1e6:.0f} MB in {STAGE}')


if __name__ == '__main__':
    main()
