"""Real, conservative Hugging Face model revision checks and verified replacement.

Only models explicitly registered in ai_models may be checked or updated.
A changed SHA-256 identifies a different official artifact, not necessarily a
semantically newer model version. Never overwrite an installed file before the
candidate has been downloaded and verified. No network use at import time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import ai_models

_SHA = re.compile(r"[0-9a-fA-F]{64}\Z")


@dataclass(frozen=True)
class RemoteRevision:
    sha256: str
    size: int


@dataclass(frozen=True)
class ModelState:
    model_id: str
    name: str
    provider: str
    category: str
    variant_id: str
    variant_label: str
    status: str
    note: str
    installed: bool
    remote: RemoteRevision | None = None
    file: object = None


def _check_cancel(cancelled):
    if cancelled():
        raise RuntimeError("Model update check cancelled.")


def official_revision(file, timeout=8):
    """Read verifiable LFS metadata for a registered huggingface.co file."""
    u = urlparse(file.url)
    if u.scheme != "https" or u.hostname != "huggingface.co" or not (
        "/resolve/" in u.path and u.path.startswith("/")
    ):
        raise ValueError("Model revision source is not a trusted Hugging Face URL.")
    req = urllib.request.Request(
        file.url, method="HEAD", headers={"User-Agent": "StrokeScribe-model-updates"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        headers = response.headers
        digest = (headers.get("X-Linked-Etag") or headers.get("ETag") or "").strip('"')
        raw_size = headers.get("X-Linked-Size") or headers.get("Content-Length")
    if not _SHA.fullmatch(digest):
        raise ValueError("The publisher did not provide a verifiable SHA-256.")
    size = int(raw_size or 0)
    if size <= 0:
        raise ValueError("The publisher did not provide a valid model file size.")
    return RemoteRevision(digest.lower(), size)


def digest_file(path, cancelled=lambda: False):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            _check_cancel(cancelled)
            part = stream.read(4 << 20)
            if not part:
                break
            digest.update(part)
    return digest.hexdigest()


def _manifest_path(paths):
    return Path(paths.root) / "verified-model-updates.json"


def _manifest(paths):
    try:
        data = json.loads(_manifest_path(paths).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def recorded_revision(paths, file):
    """A verified snapshot may have a different size from the built-in registry."""
    record = _manifest(paths).get(file.folder + "/" + file.name, {})
    if not isinstance(record, dict):
        return None
    path = paths.model_path(file)
    if not path.is_file():
        return None
    st = path.stat()
    if (st.st_size != record.get("size") or
            st.st_mtime_ns != record.get("mtime_ns") or
            not _SHA.fullmatch(str(record.get("sha256", "")))):
        return None
    return record


def is_model_file_ready(paths, file):
    path = paths.model_path(file)
    if not path.is_file():
        return False
    if path.stat().st_size == file.size:
        return True
    return recorded_revision(paths, file) is not None


def _save_record(paths, file, remote):
    manifest = _manifest(paths)
    st = paths.model_path(file).stat()
    manifest[file.folder + "/" + file.name] = {
        "sha256": remote.sha256, "size": remote.size, "mtime_ns": st.st_mtime_ns
    }
    path = _manifest_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".verified-model-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(manifest, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def recover_interrupted_update(paths, file):
    """Recover a model if power was lost between the two atomic renames."""
    target = paths.model_path(file)
    backup = target.with_name(target.name + ".previous")
    if target.is_symlink() or backup.is_symlink():
        raise RuntimeError("Unsafe symlink in model update folder.")
    if not target.exists() and backup.is_file():
        os.replace(backup, target)
        return True
    return False


def inspect_models(paths, hardware, progress=lambda message: None,
                   cancelled=lambda: False, remote_lookup=official_revision):
    states = []
    for model in ai_models.MODELS:
        if not set(model.tasks).intersection({"generate", "edit"}):
            continue
        _check_cancel(cancelled)
        preferred, fit = ai_models.choose_variant(model, hardware)
        # Inspect every known variant before deciding which one is installed:
        # a power cut may have left only its .previous recovery snapshot.
        for variant_to_check in model.variants:
            recover_interrupted_update(paths, variant_to_check.diffusion)
        available = [v for v in model.variants if paths.model_path(v.diffusion).is_file()]
        variant = (preferred if preferred in available else available[0]) if available else preferred
        file = variant.diffusion
        installed = paths.model_path(file).is_file()
        category = "Image editing" if model.tasks == ("edit",) else "Image generation"
        if not installed:
            states.append(ModelState(model.id, model.name, model.maker, category,
                                     variant.id, variant.label, "not_installed",
                                     "Not installed. Use Install to download the recommended variant.",
                                     False, file=file))
            continue
        if not all(is_model_file_ready(paths, f)
                   for f in model.shared_files(hardware.ram_gb)):
            states.append(ModelState(model.id, model.name, model.maker, category,
                                     variant.id, variant.label, "incomplete",
                                     "Some supporting files are missing. Open Manage models to repair.",
                                     True, file=file))
            continue
        progress("Checking " + model.name + " against its official file…")
        try:
            remote = remote_lookup(file)
            _check_cancel(cancelled)
            existing = recorded_revision(paths, file)
            if existing and existing["sha256"] == remote.sha256:
                matching = True
            elif (paths.model_path(file).stat().st_size != remote.size):
                matching = False
            else:
                progress("Verifying local " + model.name + " (this can take time)…")
                matching = digest_file(paths.model_path(file), cancelled) == remote.sha256
            status = "up_to_date" if matching else "update_available"
            note = ("Installed weights match the official published file." if matching else
                    "Installed weights differ from the official published file. "
                    "This may be a changed revision; verify before updating.")
            backup = paths.model_path(file).with_name(file.name + ".previous")
            if backup.exists() and not matching:
                status = "backup_pending"
                note = "An older model backup exists. Restore or manage it before another update."
            states.append(ModelState(model.id, model.name, model.maker, category,
                                     variant.id, variant.label, status, note,
                                     True, remote, file))
        except Exception as exc:
            if cancelled():
                raise
            states.append(ModelState(model.id, model.name, model.maker, category,
                                     variant.id, variant.label, "unverified",
                                     "Could not verify publisher revision: " + str(exc),
                                     True, file=file))
    return tuple(states)


def install_verified_revision(paths, state, progress=lambda done, total, name: None,
                              cancelled=lambda: False, fetch=official_revision):
    """Resumable verified download, then atomic swap retaining the old model."""
    import ai_engine
    if state.status != "update_available" or state.remote is None:
        raise RuntimeError("No verified replacement is available for this model.")
    file, revision = state.file, state.remote
    if file not in [v.diffusion for m in ai_models.MODELS
                    for v in m.variants if set(m.tasks).intersection({"generate", "edit"})]:
        raise ValueError("Only registered image-model weights may be updated.")
    latest = fetch(file)
    if latest != revision:
        raise RuntimeError("Publisher revision changed during the check. Check again first.")
    target = paths.model_path(file)
    backup = target.with_name(target.name + ".previous")
    stage = target.with_name(target.name + ".verified-update")
    if target.is_symlink() or backup.is_symlink() or stage.is_symlink():
        raise RuntimeError("Unsafe model update path.")
    if not target.is_file() or backup.exists():
        raise RuntimeError("Original model or unresolved previous-version backup prevents updating.")
    free = ai_engine.free_space_gb(paths.root)
    if free is not None and free * 1e9 < revision.size + 2_000_000_000:
        raise RuntimeError("Not enough free disk space to safely stage the model update.")
    _check_cancel(cancelled)
    # A .part beside stage remains resumable across cancellation or failure.
    ai_engine.download(file.url, stage, revision.size,
                       lambda done, total: progress(done, total, file.name),
                       cancelled=cancelled, sha256=revision.sha256)
    _check_cancel(cancelled)
    os.replace(target, backup)
    try:
        os.replace(stage, target)
        _save_record(paths, file, revision)
    except BaseException:
        # Preserve both files rather than silently losing either on failure.
        if target.exists():
            os.replace(target, stage)
        if backup.is_file():
            os.replace(backup, target)
        raise
    return target
