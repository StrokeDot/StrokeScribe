"""exp.8: StrokeScribe.exe, the app's own launcher (Task Manager shows "StrokeScribe")."""
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import win_branding as B

ROOT = Path(__file__).resolve().parent
ICON = ROOT / 'assets' / 'strokescribe.ico'


def strings(resource):
    """The text values of a VS_VERSIONINFO (a quick reader for the test)."""
    text = resource.decode('utf-16-le', errors='ignore')
    return text


class ResourceTests(unittest.TestCase):
    def test_version_resource_names_the_program(self):
        data = B.version_resource('1.0.1-experimental.8')
        length, value_length, kind = struct.unpack_from('<HHH', data, 0)
        self.assertEqual(length, len(data))                    # one complete block
        self.assertEqual(value_length, 52)                     # VS_FIXEDFILEINFO
        self.assertEqual(kind, 0)
        self.assertEqual(data[6:6 + 30].decode('utf-16-le'), 'VS_VERSION_INFO')
        signature, = struct.unpack_from('<I', data, 40)
        self.assertEqual(signature, 0xFEEF04BD)
        ms, ls = struct.unpack_from('<II', data, 48)
        self.assertEqual((ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF), (1, 0, 1, 0))
        text = strings(data)
        for word in ('FileDescription', 'StrokeScribe', 'ProductName', 'StrokeScribe.exe', '040904B0'):
            self.assertIn(word, text)
        self.assertEqual(len(data) % 2, 0)

    def test_icon_resources_from_the_app_icon(self):
        group, images = B.icon_resources(ICON.read_bytes())
        reserved, kind, count = struct.unpack_from('<HHH', group, 0)
        self.assertEqual((reserved, kind), (0, 1))
        self.assertEqual(count, len(images))
        self.assertEqual(len(group), 6 + 14 * count)
        self.assertEqual([n for n, _ in images], list(range(1, count + 1)))
        self.assertTrue(all(len(d) > 0 for _, d in images))

    def test_only_the_installed_app_is_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(B.startup_launcher(tmp))         # a development copy goes on as it is
        self.assertTrue(B.windowless('C:/x/runtime/StrokeScribe.exe'))
        self.assertTrue(B.windowless('C:/x/runtime/pythonw.exe'))
        self.assertFalse(B.windowless('C:/x/runtime/python.exe'))


@unittest.skipUnless(sys.platform == 'win32', 'Windows only')
class WindowsLauncherTests(unittest.TestCase):
    def test_the_launcher_is_named_strokescribe_and_still_runs_python(self):
        source = Path(sys.executable)
        with tempfile.TemporaryDirectory() as tmp:
            target = B.brand(source, Path(tmp) / B.EXE, ICON, '1.0.1')
            self.assertEqual(B.description(target), 'StrokeScribe')
            self.assertNotEqual(B.description(source), 'StrokeScribe')
        # next to Python's own files (as in the app's runtime) it runs Python itself
        beside = source.parent / 'StrokeScribeTest.exe'
        try:
            B.brand(source, beside, ICON, '1.0.1')
        except OSError:
            self.skipTest('Python folder not writable here')
        try:
            out = subprocess.run([str(beside), '-c', 'import sys; print(sys.prefix)'],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(os.path.normcase(out.stdout.strip()), os.path.normcase(sys.prefix))
        finally:
            beside.unlink(missing_ok=True)

    def test_ensure_launcher_writes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            import shutil
            shutil.copyfile(sys.executable, runtime / 'pythonw.exe')
            first = B.ensure_launcher(runtime, ICON, '1.0.1')
            stamp = first.stat().st_mtime_ns
            again = B.ensure_launcher(runtime, ICON, '1.0.1')
            self.assertEqual(again.stat().st_mtime_ns, stamp)    # up to date: not written again
            self.assertEqual(B.description(first), 'StrokeScribe')


if __name__ == '__main__':
    unittest.main()
