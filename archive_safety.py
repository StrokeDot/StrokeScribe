"""Preflight untrusted ZIP metadata before writing a single application file."""
from __future__ import annotations

import re
import stat
import unicodedata
from pathlib import Path
from zipfile import ZipFile, ZipInfo

WINDOWS_SPECIAL = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\\..*)?$', re.I)


def validate_archive_member(member_name: str, destination_root: Path) -> Path:
    """Return a safe destination; reject paths ambiguous on Windows or POSIX."""
    if not isinstance(member_name, str) or not member_name:
        raise ValueError('ZIP member has no name')
    if '\\' in member_name or '\x00' in member_name or member_name.startswith('/'):
        raise ValueError(f'ZIP member uses an unsafe path: {member_name!r}')
    parts = member_name.split('/')
    if any(not part or part in ('.', '..') or ':' in part or
           part.rstrip(' .') != part or WINDOWS_SPECIAL.fullmatch(part) or
           any(ord(ch) < 32 for ch in part) for part in parts):
        raise ValueError(f'ZIP member contains an unsafe path segment: {member_name!r}')
    root = Path(destination_root)
    dest = root.joinpath(*parts)
    absolute_root = root.resolve()
    if not dest.resolve().is_relative_to(absolute_root):
        raise ValueError(f'ZIP member would escape the destination: {member_name!r}')
    scan = root
    for part in parts:
        scan = scan / part
        if scan.is_symlink():
            raise ValueError(f'ZIP member targets a filesystem link: {member_name!r}')
    return dest


def validate_archive(archive: ZipFile, destination_root: Path,
                     *, prefix: str = '', max_files: int = 20000,
                     max_bytes: int = 2 * 1024 ** 3) -> list[tuple[ZipInfo, str, Path]]:
    """Validate all archive entries, bound expansion, and return selected files.

    The optional prefix removes the one enclosing GitHub folder AFTER all
    original ZIP names have been checked for unsafe paths and symlinks.
    """
    if prefix and (not prefix.endswith('/') or prefix.startswith('/')):
        raise ValueError('Invalid archive prefix')
    root = Path(destination_root)
    members = []
    seen_files = set()
    total_bytes, count = 0, 0
    for info in archive.infolist():
        name = info.filename
        if info.is_dir():
            if not name.endswith('/'):
                raise ValueError('Malformed archive directory')
            name = name[:-1]
        validate_archive_member(name, root)
        kind = (info.external_attr >> 16) & 0o170000
        if kind == stat.S_IFLNK:
            raise ValueError('ZIP symlinks are not allowed')
        if info.is_dir():
            continue
        count += 1
        total_bytes += info.file_size
        if count > max_files or total_bytes > max_bytes:
            raise ValueError('Archive exceeds the safe file count or expanded-byte limit')
        if prefix and not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        if not rel:
            continue
        target = validate_archive_member(rel, root)
        normalized = unicodedata.normalize('NFC', rel).casefold()
        if normalized in seen_files:
            raise ValueError(f'Duplicate or case-colliding ZIP destination: {rel!r}')
        seen_files.add(normalized)
        members.append((info, rel, target))
    for rel in seen_files:
        parts = rel.split('/')
        for i in range(1, len(parts)):
            if '/'.join(parts[:i]) in seen_files:
                raise ValueError('ZIP file collides with a parent directory')
    return members
