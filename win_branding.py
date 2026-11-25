"""StrokeScribe.exe: the app's own launcher on Windows (1.0.1-experimental.8).

The user: in Task Manager the app showed as "Python" (with Python's icon), "fix it for good".

Task Manager names a process after its program file's description, and the installed app ran
on the private Python's own pythonw.exe ("Python"). Setting an app ID only changes the taskbar.
So the app gets its own program file: an exact copy of pythonw.exe, named StrokeScribe.exe,
next to it in the private runtime (Python finds its files from the folder, whatever the
program is called), with StrokeScribe's name, description and icon written into it. Windows'
own resource functions do the writing (kernel32 UpdateResource), so nothing extra is needed.

* The installer makes it when it is built and its shortcuts start it.
* An installation made before this starts on pythonw.exe once: startup.py makes the launcher
  and starts the app again through it (startup_launcher), so nobody has to reinstall.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

NAME = 'StrokeScribe'
EXE = 'StrokeScribe.exe'
BRAND = 1                       # change to make every installation write its launcher again
RT_ICON, RT_GROUP_ICON, RT_VERSION, RT_MANIFEST = 3, 14, 16, 24
LANG = 1033                     # English (United States)


# ------------------------------------------------------------------ resource data (any OS)
def _node(key, value=b'', children=(), text=False):
    """One VS_VERSIONINFO block: header, key, value, children, each 32-bit aligned."""
    def pad(b):
        return b + b'\0' * (-len(b) % 4)
    body = pad(b'\0' * 6 + (key + '\0').encode('utf-16-le'))
    body += value
    if children:
        body = pad(body)
        for i, child in enumerate(children):
            body += pad(child) if i < len(children) - 1 else child
    length = len(body)
    value_length = len(value) // 2 if text else len(value)
    return struct.pack('<HHH', length, value_length, 1 if text else 0) + body[6:]


def version_resource(version='1.0.0', description=NAME):
    """The binary VS_VERSIONINFO resource naming the program StrokeScribe."""
    nums = [int(''.join(c for c in part if c.isdigit()) or 0) for part in str(version).split('-')[0].split('.')]
    nums = (nums + [0, 0, 0, 0])[:4]
    ms, ls = (nums[0] << 16) | nums[1], (nums[2] << 16) | nums[3]
    fixed = struct.pack('<13I', 0xFEEF04BD, 0x00010000, ms, ls, ms, ls, 0x3F, 0, 0x00040004, 1, 0, 0, 0)
    strings = {
        'CompanyName': 'StrokeDot',
        'FileDescription': description,
        'FileVersion': str(version),
        'InternalName': NAME,
        'LegalCopyright': 'StrokeDot',
        'OriginalFilename': EXE,
        'ProductName': NAME,
        'ProductVersion': str(version),
    }
    table = _node('040904B0', children=tuple(
        _node(k, (v + '\0').encode('utf-16-le'), text=True) for k, v in strings.items()))
    string_info = _node('StringFileInfo', children=(table,), text=True)
    var_info = _node('VarFileInfo', children=(_node('Translation', struct.pack('<HH', LANG, 1200)),), text=True)
    return _node('VS_VERSION_INFO', fixed, (string_info, var_info))


def icon_resources(ico_bytes):
    """(group icon data, [(icon id, image data)]) from a .ico file."""
    reserved, kind, count = struct.unpack_from('<HHH', ico_bytes, 0)
    if reserved != 0 or kind != 1 or count == 0:
        raise ValueError('not an icon file')
    group = struct.pack('<HHH', 0, 1, count)
    images = []
    for i in range(count):
        w, h, colours, res, planes, bits, size, offset = struct.unpack_from('<BBBBHHII', ico_bytes, 6 + 16 * i)
        images.append((i + 1, ico_bytes[offset:offset + size]))
        group += struct.pack('<BBBBHHIH', w, h, colours, res, planes, bits, size, i + 1)
    return group, images


# ------------------------------------------------------------------ Windows
def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k.BeginUpdateResourceW.restype = wintypes.HANDLE
    k.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD,
                                  ctypes.c_void_p, wintypes.DWORD]
    k.UpdateResourceW.restype = wintypes.BOOL
    k.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    k.EndUpdateResourceW.restype = wintypes.BOOL
    k.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k.LoadLibraryExW.restype = wintypes.HMODULE
    k.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    k.FindResourceW.restype = ctypes.c_void_p
    k.SizeofResource.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
    k.SizeofResource.restype = wintypes.DWORD
    k.LoadResource.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
    k.LoadResource.restype = ctypes.c_void_p
    k.LockResource.argtypes = [ctypes.c_void_p]
    k.LockResource.restype = ctypes.c_void_p
    k.FreeLibrary.argtypes = [wintypes.HMODULE]
    return k


def _read_resource(path, kind, name):
    """The bytes of one resource of a program file, or None."""
    import ctypes
    k = _kernel32()
    module = k.LoadLibraryExW(str(path), None, 0x2 | 0x20)     # as data, as image resources
    if not module:
        return None
    try:
        found = k.FindResourceW(module, ctypes.c_void_p(name), ctypes.c_void_p(kind))
        if not found:
            return None
        size = k.SizeofResource(module, found)
        data = k.LockResource(k.LoadResource(module, found))
        return ctypes.string_at(data, size) if data and size else None
    finally:
        k.FreeLibrary(module)


def brand(source, target, icon, version='1.0.0'):
    """Writes target: a copy of the program `source` named StrokeScribe, with `icon` (.ico)."""
    import ctypes
    import shutil
    source, target = Path(source), Path(target)
    manifest = _read_resource(source, RT_MANIFEST, 1)          # keep how Windows should run it
    work = target.with_name(target.stem + '.new' + target.suffix)
    shutil.copyfile(source, work)
    k = _kernel32()
    handle = k.BeginUpdateResourceW(str(work), True)           # Python's own name and icon out
    if not handle:
        raise OSError(ctypes.get_last_error(), 'cannot open the launcher for writing')
    keep = []

    def put(kind, name, data):
        buf = ctypes.create_string_buffer(data, len(data))
        keep.append(buf)
        if not k.UpdateResourceW(handle, ctypes.c_void_p(kind), ctypes.c_void_p(name), LANG, buf, len(data)):
            raise OSError(ctypes.get_last_error(), 'cannot write the launcher')
    try:
        group, images = icon_resources(Path(icon).read_bytes())
        for number, data in images:
            put(RT_ICON, number, data)
        put(RT_GROUP_ICON, 1, group)
        put(RT_VERSION, 1, version_resource(version))
        if manifest:
            put(RT_MANIFEST, 1, manifest)
    except BaseException:
        k.EndUpdateResourceW(handle, True)
        work.unlink(missing_ok=True)
        raise
    if not k.EndUpdateResourceW(handle, False):
        work.unlink(missing_ok=True)
        raise OSError(ctypes.get_last_error(), 'cannot finish the launcher')
    os.replace(work, target)
    return target


def description(path):
    """The FileDescription Windows (and Task Manager) shows for a program file."""
    import ctypes
    from ctypes import wintypes
    v = ctypes.WinDLL('version')
    size = v.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    block = ctypes.create_string_buffer(size)
    if not v.GetFileVersionInfoW(str(path), 0, size, block):
        return None
    ptr, length = ctypes.c_void_p(), wintypes.UINT()
    for lang in ('040904B0', '040904E4', '000004B0'):
        if v.VerQueryValueW(block, f'\\StringFileInfo\\{lang}\\FileDescription', ctypes.byref(ptr),
                            ctypes.byref(length)) and length.value:
            return ctypes.wstring_at(ptr, length.value).rstrip('\0')
    return None


def _marker(runtime):
    return runtime / 'StrokeScribe.brand'


def ensure_launcher(runtime, icon, version='1.0.0'):
    """runtime/StrokeScribe.exe, written when it is missing or out of date (None if it cannot
    be made here)."""
    runtime = Path(runtime)
    source = runtime / 'pythonw.exe'
    target = runtime / EXE
    if not source.is_file() or not Path(icon).is_file():
        return None
    stamp = f'{BRAND} {source.stat().st_size} {int(source.stat().st_mtime)}'
    try:
        current = target.is_file() and _marker(runtime).read_text(encoding='utf-8').strip() == stamp
    except OSError:
        current = False
    if not current:
        brand(source, target, icon, version)
        _marker(runtime).write_text(stamp, encoding='utf-8')
    return target


def startup_launcher(app_dir):
    """For startup.py: the launcher to start the app again through, or None to go on here.

    Only the installed app (its private runtime's pythonw.exe) is moved; a development copy
    and a second start through the launcher go on as they are."""
    if sys.platform != 'win32' or os.environ.get('STROKESCRIBE_LAUNCHER'):
        return None
    app_dir = Path(app_dir)
    exe = Path(sys.executable)
    runtime = app_dir / 'runtime'
    if exe.name.lower() != 'pythonw.exe' or exe.parent.resolve() != runtime.resolve():
        return None
    try:
        from version import APP_VERSION
        return ensure_launcher(runtime, app_dir / 'assets' / 'strokescribe.ico', APP_VERSION)
    except Exception:
        return None


def windowless(executable=None):
    """True for the installed app's windowless programs (pythonw.exe, StrokeScribe.exe)."""
    return Path(executable or sys.executable).name.lower() in ('pythonw.exe', EXE.lower())
