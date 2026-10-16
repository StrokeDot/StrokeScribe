"""Update StrokeScribe in place: no unzipping, no Setup.

The newest version is read straight from the GitHub project (the branch where
new versions are published). The project is private, so a read-only GitHub
token is needed once; it is kept in this PC's StrokeScribe settings.

Updating:
  1. download the version as a ZIP (or use a ZIP you already have),
  2. keep a copy of every file it replaces in `_previous_version/`, so the
     update can be undone,
  3. copy the new files over the app folder. Nothing else is touched: the
     .venv packages, the Library, projects, settings and AI models stay,
  4. if the new version needs other Python packages (requirements.txt
     changed), install them into the existing .venv,
  5. restart.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO = 'StrokeDot/StrokeScribe'
DEFAULT_BRANCH = 'fix/svg-guide-coverage-experimental12'      # where new versions are published
BACKUP = '_previous_version'
# Never copied from an update: your packages, the backup, and repository-only parts.
SKIP_TOP = {'.venv', 'venv', BACKUP, '.git', '.github', 'dist', '__pycache__', 'test-output'}
TOKEN_HELP = 'https://github.com/settings/personal-access-tokens/new'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class UpdateError(Exception):
    pass


# ------------------------------------------------------------ versions

def parse_version(text):
    """'0.5.3-experimental.38' -> (0, 5, 3, 38); unknown parts count as 0."""
    numbers = [int(n) for n in re.findall(r'\d+', str(text or ''))]
    return tuple((numbers + [0, 0, 0, 0])[:4])


def is_newer(candidate, current):
    return parse_version(candidate) > parse_version(current)


def version_in(source):
    """APP_VERSION from the text of a version.py."""
    match = re.search(r'''APP_VERSION\s*=\s*['"]([^'"]+)['"]''', source)
    return match.group(1) if match else None


def current_version(app_dir=APP_DIR):
    try:
        return version_in((Path(app_dir) / 'version.py').read_text(encoding='utf-8'))
    except OSError:
        return None


# ------------------------------------------------------------ settings

def _settings_path():
    from preflight import config_path
    return config_path().parent / 'updates.json'


def load_settings():
    try:
        data = json.loads(_settings_path().read_text())
    except Exception:
        data = {}
    data.setdefault('token', '')
    data.setdefault('branch', DEFAULT_BRANCH)
    data.setdefault('check_at_start', True)
    return data


def save_settings(data):
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ------------------------------------------------------------ GitHub

def key_problem(token):
    """A plain-language problem with a pasted key, or None if it looks right."""
    token = (token or '').strip()
    if not token:
        return 'Paste your GitHub key first.'
    if not token.startswith(('github_pat_', 'ghp_')):
        return ('This does not look like a GitHub key: a key starts with “github_pat_”. '
                'Copy it again on GitHub (the copy button next to the key).')
    if len(token) < 40:
        return (f'The key is too short ({len(token)} characters; a GitHub key has about 90). '
                'It was not copied completely: copy it again with the copy button on GitHub.')
    return None


def _request(url, token, accept='application/vnd.github+json', timeout=30):
    headers = {'Accept': accept, 'User-Agent': 'StrokeScribe-updater', 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token.strip()
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise UpdateError('GitHub did not accept the key (token). Check that it is copied completely '
                              'and that it may read the StrokeScribe project.') from exc
        if exc.code == 404:
            raise UpdateError('StrokeScribe was not found on GitHub with this key. The key needs '
                              f'read access to {REPO} (Contents: Read-only).') from exc
        raise UpdateError(f'GitHub answered {exc.code}.') from exc
    except urllib.error.URLError as exc:
        raise UpdateError('No connection to GitHub. Check the internet connection.') from exc


def latest_version(token, branch=DEFAULT_BRANCH, repo=REPO):
    """Version number of the newest StrokeScribe on GitHub."""
    from urllib.parse import quote
    url = f'https://api.github.com/repos/{repo}/contents/version.py?ref={quote(branch, safe="")}'
    with _request(url, token, accept='application/vnd.github.raw') as response:
        version = version_in(response.read().decode('utf-8', 'replace'))
    if not version:
        raise UpdateError('The version number on GitHub could not be read.')
    return version


def download(token, target, branch=DEFAULT_BRANCH, repo=REPO, progress=lambda done, total: None):
    """The newest StrokeScribe as a ZIP file."""
    from urllib.parse import quote
    url = f'https://api.github.com/repos/{repo}/zipball/{quote(branch, safe="")}'
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _request(url, token, timeout=120) as response, open(target, 'wb') as out:
        total = int(response.headers.get('Content-Length') or 0)
        done = 0
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            out.write(block)
            done += len(block)
            progress(done, total)
    return target


# ------------------------------------------------------------ applying

def _members(archive):
    """(member, relative path) of the app files inside the ZIP (any top folder)."""
    names = [n for n in archive.namelist() if not n.endswith('/')]
    version = [n for n in names if n.rsplit('/', 1)[-1] == 'version.py' and n.count('/') <= 1]
    if not version or not any(n.rsplit('/', 1)[-1] == 'app.py' for n in names):
        raise UpdateError('This ZIP is not a StrokeScribe version (version.py and app.py are missing).')
    prefix = version[0][:-len('version.py')]
    out = []
    for name in names:
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        parts = Path(rel).parts
        if not parts or parts[0] in SKIP_TOP or '..' in parts or rel.endswith('.pyc'):
            continue
        out.append((name, rel))
    return out, prefix


def zip_version(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        _, prefix = _members(archive)
        return version_in(archive.read(prefix + 'version.py').decode('utf-8', 'replace'))


def apply_zip(zip_path, app_dir=APP_DIR, log=lambda text: None):
    """Copy the version in `zip_path` over `app_dir`. Returns
    {'version', 'previous', 'files', 'requirements_changed'}."""
    app_dir = Path(app_dir)
    previous = current_version(app_dir)
    with zipfile.ZipFile(zip_path) as archive:
        members, prefix = _members(archive)
        version = version_in(archive.read(prefix + 'version.py').decode('utf-8', 'replace'))
        old_requirements = _read(app_dir / 'requirements.txt')
        backup = app_dir / BACKUP
        if backup.exists():
            shutil.rmtree(backup)
        backup.mkdir()
        added = []
        for name, rel in members:
            target = app_dir / rel
            data = archive.read(name)
            if target.is_file():
                if target.read_bytes() == data:
                    continue
                saved = backup / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            else:
                added.append(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.updating')
            temp.write_bytes(data)
            os.replace(temp, target)
        (backup / 'update.json').write_text(json.dumps({'from': previous, 'to': version, 'added': added},
                                                       indent=2))
    changed = _read(app_dir / 'requirements.txt') != old_requirements
    log(f'Updated {previous} -> {version} ({len(members)} files checked, {len(added)} new).')
    return dict(version=version, previous=previous, files=len(members), requirements_changed=changed)


def _read(path):
    try:
        return Path(path).read_text(encoding='utf-8')
    except OSError:
        return ''


def can_roll_back(app_dir=APP_DIR):
    return (Path(app_dir) / BACKUP / 'update.json').is_file()


def roll_back(app_dir=APP_DIR):
    """Go back to the version before the last update."""
    app_dir = Path(app_dir)
    backup = app_dir / BACKUP
    info = json.loads((backup / 'update.json').read_text())
    for path in backup.rglob('*'):
        if path.is_file() and path.name != 'update.json':
            rel = path.relative_to(backup)
            target = app_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for rel in info.get('added', []):
        try:
            (app_dir / rel).unlink()
        except OSError:
            pass
    shutil.rmtree(backup)
    return info.get('from')


def install_requirements(app_dir=APP_DIR, log=lambda text: None):
    """New Python packages for the updated version, into the .venv already in use."""
    cmd = [sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '-r', str(Path(app_dir) / 'requirements.txt')]
    proc = subprocess.Popen(cmd, cwd=str(app_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors='replace', creationflags=NO_WINDOW)
    for line in proc.stdout:
        log(line.rstrip())
    if proc.wait() != 0:
        raise UpdateError('The new packages could not be installed (see the details). '
                          'Running Setup.cmd once fixes this.')


def restart(app_dir=APP_DIR):
    """Start the updated StrokeScribe (the caller then closes this one)."""
    flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
    subprocess.Popen([sys.executable, '-u', str(Path(app_dir) / 'startup.py')], cwd=str(app_dir),
                     creationflags=flags)
