"""Autosave, recovery after a crash, and the list of recent projects.

Every minute, if something changed, the whole project is saved to a backup
file in StrokeScribe's settings folder (never over your own project file).
Closing StrokeScribe normally removes the backup; if it is still there at the
next start, StrokeScribe crashed or Windows stopped it, and it offers to bring
the work back.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

MAX_RECENT = 10


def _folder():
    from preflight import config_path
    return config_path().parent


def backup_path():
    return _folder() / 'autosave' / 'autosave.strokescribe'


def _meta_path():
    return _folder() / 'autosave' / 'autosave.json'


def save(state, project_path=None, title=''):
    """Write the backup (atomically, like a normal project save)."""
    import projects
    path = backup_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    projects.save(path, state)
    metadata=_meta_path()
    temporary=metadata.with_name(metadata.name+'.saving')
    temporary.write_text(json.dumps({'project_path': str(project_path or ''), 'title': title,
                                     'time': time.time()}))
    os.replace(temporary,metadata)
    return path


def archive_pending():
    """Keep declined crash recovery as a normal, manually openable project.

    It is copied out of the active autosave slot *before* that slot can be
    cleared or reused, so later edits cannot overwrite the old recovery.
    A failed copy leaves the active backup untouched.
    """
    source=backup_path()
    if not source.is_file():
        return None
    folder=source.parent / 'Recovered copies'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder / f'recovery-{time.time_ns()}.strokescribe'
    temporary=target.with_name(target.name+'.copying')
    try:
        shutil.copy2(source,temporary)
        if source.read_bytes()!=temporary.read_bytes():
            raise OSError('Recovery copy failed verification.')
        os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def pending():
    """{'path', 'project_path', 'title', 'time'} of a backup left by a crash, or None."""
    path = backup_path()
    if not path.is_file():
        return None
    try:
        meta = json.loads(_meta_path().read_text())
    except Exception:
        meta = {}
    if meta.get('cleared'):
        return None                       # closed normally; the file just could not be deleted
    meta['path'] = str(path)
    meta.setdefault('time', path.stat().st_mtime)
    return meta


def clear():
    """Remove the backup (a normal close). On Windows a file can be held open for a
    moment (antivirus, indexing), so the delete is retried; if it still cannot be
    deleted, the backup is marked as cleared so it is not offered for recovery."""
    for attempt in range(10):
        left = []
        for path in (backup_path(), _meta_path()):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                left.append(path)
        if not left:
            return
        time.sleep(.1)
    try:
        _meta_path().write_text(json.dumps({'cleared': True}))
    except OSError:
        pass


# ------------------------------------------------------------ recent projects

def _recent_path():
    return _folder() / 'recent.json'


def recent():
    """Recent project files that still exist, newest first."""
    try:
        paths = json.loads(_recent_path().read_text())
    except Exception:
        paths = []
    return [p for p in paths if Path(p).is_file()][:MAX_RECENT]


def add_recent(path):
    path = str(Path(path).resolve())
    paths = [p for p in recent() if Path(p).resolve() != Path(path)]
    paths.insert(0, path)
    target = _recent_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(paths[:MAX_RECENT], indent=1))
