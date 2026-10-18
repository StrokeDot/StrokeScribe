"""Security regression tests for untrusted StrokeScribe and ComfyUI archives."""
import io
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from archive_safety import validate_archive_member, validate_archive
import updater
import ai_engine


def make_zip(items):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        for name, data in items:
            z.writestr(name, data)
    return stream.getvalue()


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name) / "destination"
        self.root.mkdir()

    def test_valid_relative_member_paths(self):
        self.assertEqual(validate_archive_member("assets/hand.png", self.root),
                         self.root / "assets" / "hand.png")

    def test_path_traversal_drive_names_and_windows_aliases_are_rejected(self):
        invalid = ["../outside", "/absolute", "C:/escape", "C:\\escape",
                   "..\\escape", "prefix/../../outside", "\\\\server\\share",
                   "name\\file", "a/./b", "a//b", "a/../b", "x:stream",
                   "NUL.txt", "folder/COM1", "file. ", "file."]
        for name in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_archive_member(name, self.root)

    def test_symlink_escape_is_rejected(self):
        outside = Path(self.t.name) / "outside"
        outside.mkdir()
        try:
            (self.root / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unsupported")
        with self.assertRaises(ValueError):
            validate_archive_member("link/escape", self.root)

    def test_duplicates_case_collisions_and_symlink_entries_are_rejected(self):
        link = zipfile.ZipInfo("src/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for items in [[("src/A.py", b"1"), ("src/a.py", b"2")],
                      [("src/a.py", b"1"), ("src/a.py", b"2")],
                      [(link, b"../../outside")]]:
            with self.subTest(items=items):
                with zipfile.ZipFile(io.BytesIO(make_zip(items))) as archive:
                    with self.assertRaises(ValueError):
                        validate_archive(archive, self.root, prefix="src/")

    def test_count_and_expanded_size_limits(self):
        with zipfile.ZipFile(io.BytesIO(make_zip([
                ("one.py", b"12345"), ("two.py", b"12345")]))) as archive:
            with self.assertRaises(ValueError):
                validate_archive(archive, self.root, max_files=1)
            with self.assertRaises(ValueError):
                validate_archive(archive, self.root, max_bytes=9)

    def test_updater_validates_before_changing_any_app_file(self):
        (self.root / "app.py").write_text("old")
        (self.root / "version.py").write_text('APP_VERSION="1"')
        raw = make_zip([("repo/version.py", 'APP_VERSION="2"'),
                        ("repo/app.py", "new"), ("repo/../../outside", "attack")])
        zip_path = Path(self.t.name) / "unsafe.zip"
        zip_path.write_bytes(raw)
        with self.assertRaises(updater.UpdateError):
            updater.apply_zip(zip_path, self.root)
        self.assertEqual((self.root / "app.py").read_text(), "old")
        self.assertFalse((Path(self.t.name) / "outside").exists())

    def test_comfy_preflights_before_removing_old_engine(self):
        (self.root / "important.txt").write_text("user content")
        raw = make_zip([("comfy/start.py", "safe"),
                        ("comfy/../../outside", "attack")])
        with self.assertRaises(ValueError):
            ai_engine._extract_zip(raw, self.root)
        self.assertEqual((self.root / "important.txt").read_text(), "user content")
        self.assertFalse((Path(self.t.name) / "outside").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
