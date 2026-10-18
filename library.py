"""StrokeScribe Library: a safe home for your images and hands (like Canva uploads).

Files added to the library are COPIED into a folder you choose (default:
Documents/StrokeScribe Library), so they stay available even if the originals
are moved or deleted. Each category has its own sub-folder:

    Images/   pictures and SVGs to animate
    Hands/    hand PNGs (with their pen-tip position)
    Audio/    voiceovers and music

Deleted items go to a "Deleted items" folder inside the library, so nothing is
lost by accident. An index.json per category keeps names, dates and, for hands,
the pen tip.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIES = {'images': 'Images', 'hands': 'Hands', 'audio': 'Audio'}
TYPES = {'images': ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.svg'), 'hands': ('.png',),
         'audio': ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.opus', '.wma')}
DELETED = 'Deleted items'


def _settings_path():
    from preflight import config_path
    return config_path().parent / 'library.json'


def default_root():
    home = Path.home()
    docs = home / 'Documents'
    return (docs if docs.is_dir() else home) / 'StrokeScribe Library'


def load_settings():
    try:
        data = json.loads(_settings_path().read_text())
    except Exception:
        data = {}
    data.setdefault('root', str(default_root()))
    data.setdefault('keep_imports', True)
    return data


def save_settings(data):
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


@dataclass
class Item:
    category: str
    file: str                 # file name inside the category folder
    name: str                 # display name
    added: float
    original: str = ''
    tip: tuple | None = None  # hands: pen tip (x, y) fractions
    path: Path = field(default=None, repr=False)


class Library:
    def __init__(self, root=None):
        self.root = Path(root or load_settings()['root'])

    def folder(self, category):
        path = self.root / CATEGORIES[category]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _index_path(self, category):
        return self.folder(category) / 'index.json'

    def _read(self, category):
        try:
            data = json.loads(self._index_path(category).read_text(encoding='utf-8'))
        except Exception:
            data = {}
        return data

    def _write(self, category, data):
        path = self._index_path(category)
        temp = path.with_name('index.json.saving')
        temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temp.replace(path)

    def items(self, category, search=''):
        """Library items, newest first. Files dropped into the folder by hand appear too."""
        folder = self.folder(category)
        index = self._read(category)
        changed = False
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in TYPES[category] and path.name not in index:
                index[path.name] = {'name': path.stem, 'added': path.stat().st_mtime, 'original': ''}
                changed = True
        for name in [n for n in index if not (folder / n).is_file()]:
            del index[name]
            changed = True
        if changed:
            self._write(category, index)
        items = []
        for file, info in index.items():
            tip = info.get('tip')
            item = Item(category, file, info.get('name', Path(file).stem), float(info.get('added', 0)),
                        info.get('original', ''), tuple(tip) if tip else None, folder / file)
            if search.lower() in item.name.lower() or search.lower() in item.file.lower():
                items.append(item)
        return sorted(items, key=lambda i: i.added, reverse=True)

    def add(self, category, source, name=None, tip=None):
        """Copy a file into the library (a file already in it is returned as is)."""
        source = Path(source)
        if source.suffix.lower() not in TYPES[category]:
            raise ValueError(f'{source.name}: this kind of file cannot go into {CATEGORIES[category]}.')
        folder = self.folder(category)
        try:
            if source.resolve().parent == folder.resolve():
                return next(i for i in self.items(category) if i.file == source.name)
        except (OSError, StopIteration):
            pass
        # Same content already in the library? Reuse it instead of a duplicate.
        size = source.stat().st_size
        for existing in folder.iterdir():
            if existing.is_file() and existing.suffix.lower() == source.suffix.lower() \
                    and existing.stat().st_size == size and existing.read_bytes() == source.read_bytes():
                return next(i for i in self.items(category) if i.file == existing.name)
        target = folder / source.name
        n = 2
        while target.exists():
            target = folder / f'{source.stem} ({n}){source.suffix}'
            n += 1
        shutil.copy2(source, target)
        index = self._read(category)
        index[target.name] = {'name': name or source.stem, 'added': time.time(), 'original': str(source)}
        if tip:
            index[target.name]['tip'] = [float(tip[0]), float(tip[1])]
        self._write(category, index)
        return next(i for i in self.items(category) if i.file == target.name)

    def set_tip(self, item, tip):
        index = self._read(item.category)
        index.setdefault(item.file, {'name': item.name, 'added': item.added})
        index[item.file]['tip'] = [float(tip[0]), float(tip[1])]
        self._write(item.category, index)

    def tip_for(self, path):
        """Saved pen tip for a hand file in the library, or None."""
        path = Path(path)
        try:
            if path.resolve().parent != self.folder('hands').resolve():
                return None
        except OSError:
            return None
        tip = self._read('hands').get(path.name, {}).get('tip')
        return tuple(tip) if tip else None

    def rename(self, item, name):
        index = self._read(item.category)
        if item.file in index:
            index[item.file]['name'] = name.strip() or item.name
            self._write(item.category, index)

    def delete(self, item):
        """Move to 'Deleted items' (recoverable), never erase."""
        trash = self.root / DELETED / CATEGORIES[item.category]
        trash.mkdir(parents=True, exist_ok=True)
        target = trash / item.file
        n = 2
        while target.exists():
            target = trash / f'{Path(item.file).stem} ({n}){Path(item.file).suffix}'
            n += 1
        shutil.move(str(item.path), str(target))
        index = self._read(item.category)
        index.pop(item.file, None)
        self._write(item.category, index)
        return target

    def move_to(self, new_root):
        """Safely migrate the complete library, even into an existing library.

        Copy and verify *everything* before updating the configured root or
        deleting the old folder. A filename collision with different contents
        receives a numbered name, and its index metadata follows the rename.
        An interrupted copy leaves the original library fully usable.
        """
        import hashlib
        import uuid

        old_root = self.root.resolve()
        new_root = Path(new_root).resolve()
        if new_root == old_root:
            return self.root
        if new_root.is_relative_to(old_root) or old_root.is_relative_to(new_root):
            raise ValueError('Choose a Library folder outside the existing Library tree.')

        def identical(a, b):
            if a.stat().st_size != b.stat().st_size:
                return False
            def digest(path):
                h = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1 << 20), b''):
                        h.update(chunk)
                return h.digest()
            return digest(a) == digest(b)

        # A failed transfer must not switch the configured Library location.
        new_root.mkdir(parents=True, exist_ok=True)
        mappings = {}
        index_dirs = {Path(label) for label in CATEGORIES.values()}
        sources = sorted(p for p in old_root.rglob('*') if p.is_file() or p.is_symlink()) \
            if old_root.is_dir() else []
        for source in sources:
            if source.is_symlink():
                raise ValueError('Library contains a symlink; move it manually before relocation.')
            rel = source.relative_to(old_root)
            if len(rel.parts) == 2 and rel.parts[0] in index_dirs and rel.name == 'index.json':
                continue
            folder = new_root / rel.parent
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / source.name
            if target.exists() and not identical(source, target):
                number = 2
                while True:
                    other = folder / f'{source.stem} ({number}){source.suffix}'
                    if not other.exists() or identical(source, other):
                        target = other
                        break
                    number += 1
            if not target.exists():
                temporary = folder / ('.' + target.name + '.' + uuid.uuid4().hex + '.migrating')
                try:
                    shutil.copy2(source, temporary)
                    if not identical(source, temporary):
                        raise OSError('Library copy failed verification: ' + str(rel))
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            if not identical(source, target):
                raise OSError('Library destination failed verification: ' + str(rel))
            mappings[rel] = target.relative_to(new_root)

        # Merge every category index *after* the bytes have been verified.
        for label in CATEGORIES.values():
            source_index = old_root / label / 'index.json'
            destination_index = new_root / label / 'index.json'
            if not source_index.is_file() and not destination_index.is_file():
                continue
            old_data = json.loads(source_index.read_text(encoding='utf-8')) if source_index.is_file() else {}
            merged = json.loads(destination_index.read_text(encoding='utf-8')) if destination_index.is_file() else {}
            for name, metadata in old_data.items():
                mapped = mappings.get(Path(label) / name)
                if mapped is None:
                    continue
                target_name = mapped.name
                if target_name not in merged:
                    merged[target_name] = metadata
                elif target_name == name:
                    # Same file content already existed. Preserve destination
                    # metadata, adding missing source attributes (notably tip).
                    for key, value in metadata.items():
                        merged[target_name].setdefault(key, value)
            destination_index.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination_index.with_name('index.json.migrating')
            temporary.write_text(json.dumps(merged, indent=2), encoding='utf-8')
            os.replace(temporary, destination_index)

        settings = load_settings()
        settings['root'] = str(new_root)
        save_settings(settings)
        self.root = new_root
        if old_root.is_dir():
            shutil.rmtree(old_root)
        return new_root


def reveal(path):
    """Show a file or folder in Explorer / Finder."""
    import subprocess
    path = Path(path)
    if sys.platform == 'win32':
        subprocess.Popen(['explorer', '/select,', str(path)] if path.is_file() else ['explorer', str(path)])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path if path.is_dir() else path.parent)])
