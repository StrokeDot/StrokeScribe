"""Project lifecycle: accurate dirty tracking without depending on undo history.

The signature uses the *persisted* project payload (all scenes, drawings,
overlays, imported art, hands and settings). This catches edits that have not
yet entered the 450 ms undo-history debounce, and changes outside History.
"""
import hashlib
import json


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
        for chunk in encoder.iterencode(project):
            digest.update(chunk.encode('utf-8'))
        return digest.hexdigest()

    def changed(self, project):
        if self.saved_signature is None:
            return self.is_dirty
        return self.signature(project) != self.saved_signature
