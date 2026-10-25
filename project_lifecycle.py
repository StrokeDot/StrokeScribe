"""Project lifecycle: accurate dirty tracking without depending on undo history.

The signature uses the *persisted* project payload (all scenes, drawings,
overlays, imported art, hands and settings). This catches edits that have not
yet entered the 450 ms undo-history debounce, and changes outside History.
"""
import hashlib
import json


_BIG = {}


def _light(value):
    """exp.120: big texts (the pictures, in base64) stand in by a digest worked out once;
    a project of 100 MB was escaped and hashed in full on every autosave and close."""
    if isinstance(value, str):
        if len(value) < 4096:
            return value
        hit = _BIG.get(value)
        if hit is None:
            hit = '#' + hashlib.blake2b(value.encode('ascii', 'backslashreplace'), digest_size=16).hexdigest() + \
                  f':{len(value)}'
            _BIG[value] = hit
            while len(_BIG) > 64:
                _BIG.pop(next(iter(_BIG)))
        return hit
    if isinstance(value, dict):
        return {k: _light(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_light(v) for v in value]
    return value


class ProjectChangeTracker:
    def __init__(self):
        self.revision = 0
        self.saved_revision = 0
        self.saved_signature = None

    def mark_changed(self):
        self.revision += 1

    def mark_saved(self, project=None):
        self.saved_revision = self.revision
        if project is not None:
            self.saved_signature = self.signature(project)

    @property
    def is_dirty(self):
        return self.revision != self.saved_revision

    @staticmethod
    def signature(project):
        digest = hashlib.sha256()
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        for chunk in encoder.iterencode(_light(project)):
            digest.update(chunk.encode('utf-8'))
        return digest.hexdigest()

    def changed(self, project):
        if self.saved_signature is None:
            return self.is_dirty
        return self.signature(project) != self.saved_signature


def resolve_project_leave(is_dirty, ask, save, *,
                          save_choice, discard_choice, auto_discard=False):
    """Pure decision step shared by close, project-open and artwork replacement.

    No Qt types, dialogs, or I/O are imported into this module: callers supply
    the question and saving functions. Unknown responses fail closed.
    """
    if not is_dirty or auto_discard:
        return True
    answer = ask()
    if answer == save_choice:
        return bool(save())
    return answer == discard_choice
