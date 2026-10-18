"""Update StrokeScribe in place: no unzipping, no Setup.

The newest version is read straight from the GitHub project (the branch where
new versions are published). The project is public, so no key is needed; a
read-only GitHub key (token) is only used if the project is made private again.
It is kept in this PC's StrokeScribe settings.

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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO = 'StrokeDot/StrokeScribe'
DEFAULT_BRANCH = 'fix/svg-guide-coverage-experimental12'      # where new versions are published
BACKUP = '_previous_version'
# Never copied from an update: your packages, the backup, and repository-only parts.
SKIP_TOP = {'.venv', 'venv', 'runtime', BACKUP, '.strokescribe-update-journal.json', '.git', '.github', 'dist', '__pycache__', 'test-output', 'build'}
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
        if token and exc.code in (401, 403, 404):
            # An old or wrong key: the public project can still be read without it.
            try:
                return _request(url, None, accept, timeout)
            except UpdateError:
                pass
        if exc.code == 403 and exc.headers.get('X-RateLimit-Remaining') == '0':
            raise UpdateError('GitHub is busy: too many checks from this internet connection this hour. '
                              'Try again later.') from exc
        if exc.code in (401, 403) and token:
            raise UpdateError('GitHub did not accept the key (token). Check that it is copied completely '
                              'and that it may read the StrokeScribe project.') from exc
        if exc.code in (401, 403, 404):
            if not token:
                raise UpdateError('StrokeScribe could not be read on GitHub. If the project is private, '
                                  'add a GitHub key (Key… button).') from exc
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


def whats_new(token, version, branch=DEFAULT_BRANCH, repo=REPO):
    """The README notes of `version` (plain text), or ''."""
    from urllib.parse import quote
    url = f'https://api.github.com/repos/{repo}/contents/README.md?ref={quote(branch, safe="")}'
    with _request(url, token, accept='application/vnd.github.raw') as response:
        text = response.read().decode('utf-8', 'replace')
    return notes_for(text, version)


def notes_for(readme, version):
    """The '## … (vVERSION)' section of the README, without markdown marks."""
    lines = readme.splitlines()
    out, inside = [], False
    for line in lines:
        if line.startswith('## '):
            if inside:
                break
            inside = f'(v{version})' in line
            if inside:
                out.append(line[3:].replace(f' (v{version})', '').strip())
            continue
        if inside:
            out.append(line)
    text = '\n'.join(out).strip()
    return re.sub(r'\*\*|`', '', text)


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

def _members(archive, destination_root=APP_DIR):
    """Preflight the ENTIRE ZIP before returning its eligible application files."""
    from archive_safety import validate_archive
    names = [n for n in archive.namelist() if not n.endswith('/')]
    version = [n for n in names if n.rsplit('/', 1)[-1] == 'version.py' and n.count('/') <= 1]
    if not version or not any(n.rsplit('/', 1)[-1] == 'app.py' for n in names):
        raise UpdateError('This ZIP is not a StrokeScribe version (version.py and app.py are missing).')
    prefix = version[0][:-len('version.py')]
    try:
        checked = validate_archive(archive, destination_root, prefix=prefix,
                                   max_files=30000, max_bytes=3 * 1024 ** 3)
    except ValueError as exc:
        raise UpdateError('Unsafe or oversized StrokeScribe ZIP: ' + str(exc)) from exc
    out = []
    for info, rel, _ in checked:
        parts = rel.split('/')
        if parts[0] in SKIP_TOP or parts[0].startswith('.strokescribe-update-') or rel.endswith('.pyc'):
            continue
        out.append((info.filename, rel))
    return out, prefix


def zip_version(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        _, prefix = _members(archive)
        return version_in(archive.read(prefix + 'version.py').decode('utf-8', 'replace'))


JOURNAL = '.strokescribe-update-journal.json'


@dataclass
class StagedUpdate:
    app_dir: Path
    stage_dir: Path
    version: str
    previous: str | None
    files: tuple[str, ...]
    changed: tuple[str, ...]
    backups: tuple[str, ...]
    added: tuple[str, ...]


def _atomic_json(path, data):
    """Write the journal through a same-directory rename."""
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.writing')
    try:
        temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _journal_path(app_dir):
    return Path(app_dir) / JOURNAL


def _safe_transaction_dir(app_dir, name):
    """Never follow a malicious/stale journal path outside the app folder."""
    folder = Path(app_dir)
    if not isinstance(name, str) or not name.startswith('.strokescribe-update-') or '/' in name or '\\' in name:
        raise UpdateError('The incomplete update journal has an invalid staging path.')
    path = folder / name
    if path.is_symlink() or path.resolve().parent != folder.resolve():
        raise UpdateError('The incomplete update journal points outside the application.')
    return path


def stage_update(zip_path, app_dir=APP_DIR):
    """Validate and unpack a complete candidate away from the live application.

    Existing dependencies cannot be updated safely in-place because pip is not
    transactional. Require a verified Windows installer instead.
    """
    app_dir = Path(app_dir)
    if _journal_path(app_dir).exists():
        raise UpdateError('An interrupted update must be recovered before installing another.')
    old_version = current_version(app_dir)
    stage = None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members, prefix = _members(archive, app_dir)
            if not members:
                raise UpdateError('This ZIP has no eligible application files.')
            new_version = version_in(archive.read(prefix + 'version.py').decode('utf-8', 'replace'))
            if not new_version or not re.fullmatch(r'\\d+\\.\\d+\\.\\d+(?:[-.][A-Za-z0-9.]+)?', new_version):
                raise UpdateError('The ZIP contains malformed version metadata.')
            incoming_req = next((name for name, rel in members if rel == 'requirements.txt'), None)
            if incoming_req is None:
                raise UpdateError('The ZIP does not include dependency metadata (requirements.txt).')
            if archive.read(incoming_req).decode('utf-8', 'replace') != _read(app_dir / 'requirements.txt'):
                raise UpdateError('This update changes Python packages. Use the verified full Windows installer.')
            bad = archive.testzip()
            if bad:
                raise UpdateError('The update ZIP is damaged at ' + bad)
            stage = Path(tempfile.mkdtemp(prefix='.strokescribe-update-', dir=str(app_dir)))
            payload = stage / 'payload'
            changed, backups, added = [], [], []
            for name, rel in members:
                from archive_safety import validate_archive_member
                target = validate_archive_member(rel, app_dir)
                data = archive.read(name)
                if target.is_file() and target.read_bytes() == data:
                    continue
                destination = payload / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                if hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256(data).digest():
                    raise UpdateError('Failed to verify staged update file: ' + rel)
                changed.append(rel)
                if target.exists():
                    if not target.is_file():
                        raise UpdateError('Update destination is not a normal file: ' + rel)
                    backups.append(rel)
                else:
                    added.append(rel)
        return StagedUpdate(app_dir, stage, new_version, old_version,
                            tuple(rel for _, rel in members), tuple(changed),
                            tuple(backups), tuple(added))
    except Exception:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        raise


def recover_interrupted_update(app_dir=APP_DIR):
    """Restore a previously working installation from the durable journal.

    Recovery is idempotent: backups are copied (not consumed) until all
    restored files and the previous rollback snapshot are in place. Keep the
    journal and backup on any failure so the next startup can retry.
    """
    from archive_safety import validate_archive_member
    app_dir = Path(app_dir)
    journal_path = _journal_path(app_dir)
    if not journal_path.is_file():
        return {'recovered': False}
    try:
        journal = json.loads(journal_path.read_text(encoding='utf-8'))
        stage = _safe_transaction_dir(app_dir, journal['stage'])
        transaction_id = journal['transaction_id']
        staged_backup = stage / 'backup'
        active_backup = app_dir / BACKUP
        if staged_backup.is_dir():
            backing = staged_backup
        elif (active_backup / 'update.json').is_file():
            data = json.loads((active_backup / 'update.json').read_text(encoding='utf-8'))
            if data.get('transaction_id') != transaction_id:
                raise UpdateError('The update rollback folder does not match the journal.')
            backing = active_backup
        else:
            raise UpdateError('Recovery backup is missing; do not restart or reinstall yet.')
        names = list(journal.get('backups', ()))
        added = list(journal.get('added', ()))
        # Validate all targets, and ensure all required backups exist, before
        # writing any live file. This also makes retry after failed recovery safe.
        for rel in names:
            target = validate_archive_member(rel, app_dir)
            if not (backing / rel).is_file():
                raise UpdateError('Recovery backup is incomplete: ' + rel)
        for rel in added:
            validate_archive_member(rel, app_dir)
        for rel in names:
            source = backing / rel
            target = validate_archive_member(rel, app_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.restoring')
            try:
                shutil.copy2(source, temp)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        for rel in added:
            target = validate_archive_member(rel, app_dir)
            if target.is_file():
                target.unlink()
        prior = stage / 'old_previous_version'
        if prior.is_dir():
            if active_backup.is_dir():
                shutil.rmtree(active_backup)
            os.replace(prior, active_backup)
        elif active_backup.is_dir() and backing == active_backup:
            shutil.rmtree(active_backup)
        journal_path.unlink()
        shutil.rmtree(stage, ignore_errors=True)
        return {'recovered': True, 'version': journal.get('from')}
    except Exception as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError('Recovery failed; original backup and journal were preserved: ' + str(exc)) from exc


def commit_update(staged, log=lambda text: None):
    """Install a prepared candidate with a restart-recoverable transaction."""
    app_dir = staged.app_dir
    stage = staged.stage_dir
    journal_path = _journal_path(app_dir)
    if journal_path.exists():
        raise UpdateError('An earlier update must be recovered first.')
    backup = stage / 'backup'
    backup.mkdir(exist_ok=True)
    # Snapshot all originals BEFORE the first file replacement.
    try:
        for rel in staged.backups:
            original = app_dir / rel
            snapshot = backup / rel
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, snapshot)
            if original.read_bytes() != snapshot.read_bytes():
                raise UpdateError('Could not verify rollback copy: ' + rel)
        transaction_id = uuid.uuid4().hex
        (backup / 'update.json').write_text(json.dumps({
            'from': staged.previous, 'to': staged.version,
            'added': list(staged.added), 'transaction_id': transaction_id
        }, indent=2), encoding='utf-8')
        journal = {
            'phase': 'applying', 'from': staged.previous, 'to': staged.version,
            'transaction_id': transaction_id, 'stage': stage.name,
            'backups': list(staged.backups), 'added': list(staged.added)
        }
        _atomic_json(journal_path, journal)
        # Each rename is atomic and source payload lives on the app filesystem.
        for rel in staged.changed:
            from archive_safety import validate_archive_member
            target = validate_archive_member(rel, app_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / 'payload' / rel, target)

        current_backup = app_dir / BACKUP
        prior = stage / 'old_previous_version'
        if current_backup.exists():
            os.replace(current_backup, prior)
        os.replace(backup, current_backup)
        journal['phase'] = 'installed'
        _atomic_json(journal_path, journal)
        # This final unlink is the transaction commit point.
        journal_path.unlink()
        shutil.rmtree(stage, ignore_errors=True)
        result = {'version': staged.version, 'previous': staged.previous,
                  'files': len(staged.files), 'requirements_changed': False}
        log(f"Updated {staged.previous} -> {staged.version} ({len(staged.files)} files verified).")
        return result
    except Exception as exc:
        if journal_path.exists():
            try:
                recover_interrupted_update(app_dir)
            except Exception as restore_error:
                raise UpdateError('Update failed; recovery also failed. Keep the recovery files: '
                                  + str(restore_error)) from exc
        else:
            # Failure during backup preparation: no live application files changed.
            shutil.rmtree(stage, ignore_errors=True)
        raise UpdateError('Update failed; the previous application was retained/restored: ' + str(exc)) from exc


def apply_zip(zip_path, app_dir=APP_DIR, log=lambda text: None):
    """Compatible API for fully staged, rollback-safe file updates."""
    return commit_update(stage_update(zip_path, app_dir), log=log)


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
    cmd = [console_python(), '-m', 'pip', 'install', '--only-binary=:all:', '-r', str(Path(app_dir) / 'requirements.txt')]
    proc = subprocess.Popen(cmd, cwd=str(app_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors='replace', creationflags=NO_WINDOW)
    for line in proc.stdout:
        log(line.rstrip())
    if proc.wait() != 0:
        raise UpdateError('The new packages could not be installed (see the details). '
                          'Running Setup.cmd once fixes this.')


def console_python():
    """python.exe next to pythonw.exe (the installed app runs windowless)."""
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and (exe.parent / 'python.exe').is_file():
        return str(exe.parent / 'python.exe')
    return sys.executable


def restart(app_dir=APP_DIR):
    """Start the updated StrokeScribe (the caller then closes this one)."""
    windowless = Path(sys.executable).name.lower() == 'pythonw.exe'     # installed version
    flags = 0 if windowless else getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
    subprocess.Popen([sys.executable, '-u', str(Path(app_dir) / 'startup.py')], cwd=str(app_dir),
                     creationflags=flags)
