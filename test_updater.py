"""Update in place from GitHub or a ZIP, keep everything else, and go back."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
SKIP = os.environ.get('STROKESCRIBE_SKIP_QT') == '1'

import updater


def version_py(v):
    return f'APP_NAME = "StrokeScribe"\nAPP_VERSION = "{v}"\n'


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = self.dir / 'StrokeScribe'
        self.app.mkdir()
        files = {'version.py': version_py('0.5.3-experimental.38'), 'app.py': 'old app', 'engine.py': 'same',
                 'requirements.txt': 'numpy\n', 'assets/hand.png': 'old png',
                 '.venv/Lib/site.py': 'my packages', 'my notes.txt': 'mine'}
        for rel, text in files.items():
            (self.app / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.app / rel).write_text(text)

    def tearDown(self):
        self.tmp.cleanup()

    def make_zip(self, top='StrokeDot-StrokeScribe-1a2b3c/', version='0.5.3-experimental.39', requirements='numpy\n'):
        path = self.dir / 'update.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr(top + 'version.py', version_py(version))
            z.writestr(top + 'app.py', 'new app')
            z.writestr(top + 'engine.py', 'same')
            z.writestr(top + 'new_feature.py', 'new')
            z.writestr(top + 'requirements.txt', requirements)
            z.writestr(top + 'assets/hand.png', 'new png')
            z.writestr(top + '.github/workflows/x.yml', 'ci')
            z.writestr(top + '.venv/Lib/site.py', 'NOT mine')
        return path

    def test_versions(self):
        self.assertEqual(updater.parse_version('0.5.3-experimental.38'), (0, 5, 3, 38))
        self.assertTrue(updater.is_newer('0.5.3-experimental.39', '0.5.3-experimental.38'))
        self.assertTrue(updater.is_newer('0.5.3-experimental.100', '0.5.3-experimental.99'))
        self.assertFalse(updater.is_newer('0.5.3-experimental.38', '0.5.3-experimental.38'))
        self.assertEqual(updater.current_version(self.app), '0.5.3-experimental.38')
        self.assertTrue(updater.current_version())                      # this real app has one

    def test_update_keeps_your_things_and_can_go_back(self):
        zip_path = self.make_zip()
        self.assertEqual(updater.zip_version(zip_path), '0.5.3-experimental.39')
        result = updater.apply_zip(zip_path, self.app)
        self.assertEqual((result['previous'], result['version']), ('0.5.3-experimental.38', '0.5.3-experimental.39'))
        self.assertFalse(result['requirements_changed'])
        self.assertEqual((self.app / 'app.py').read_text(), 'new app')
        self.assertEqual((self.app / 'new_feature.py').read_text(), 'new')
        self.assertEqual((self.app / 'assets/hand.png').read_text(), 'new png')
        self.assertEqual((self.app / '.venv/Lib/site.py').read_text(), 'my packages')   # never touched
        self.assertEqual((self.app / 'my notes.txt').read_text(), 'mine')
        self.assertFalse((self.app / '.github').exists())
        self.assertEqual(updater.current_version(self.app), '0.5.3-experimental.39')
        self.assertTrue(updater.can_roll_back(self.app))
        self.assertFalse((self.app / updater.BACKUP / 'engine.py').exists())             # unchanged: not copied
        # Go back.
        self.assertEqual(updater.roll_back(self.app), '0.5.3-experimental.38')
        self.assertEqual((self.app / 'app.py').read_text(), 'old app')
        self.assertEqual((self.app / 'assets/hand.png').read_text(), 'old png')
        self.assertFalse((self.app / 'new_feature.py').exists())
        self.assertEqual(updater.current_version(self.app), '0.5.3-experimental.38')
        self.assertFalse(updater.can_roll_back(self.app))

    def test_new_packages_are_noticed_and_package_zip_works(self):
        zip_path = self.make_zip(top='StrokeScribe-Prototype-v0.5.3-experimental.39/', requirements='numpy\nnewlib\n')
        self.assertTrue(updater.apply_zip(zip_path, self.app)['requirements_changed'])

    def test_wrong_zip_is_refused(self):
        path = self.dir / 'other.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('photos/a.txt', 'x')
        with self.assertRaises(updater.UpdateError):
            updater.apply_zip(path, self.app)
        self.assertEqual((self.app / 'app.py').read_text(), 'old app')

    def test_key_check(self):
        self.assertIn('too short', updater.key_problem('github_pat_ab'))
        self.assertIn('starts with', updater.key_problem('hello'))
        self.assertIsNone(updater.key_problem('github_pat_' + 'A' * 82))

    def test_github_answers(self):
        class Reply(io.BytesIO):
            headers = {'Content-Length': '0'}
            def __enter__(self): return self
            def __exit__(self, *a): return False
        calls = []
        def fake(request, timeout=0):
            calls.append(request)
            return Reply(version_py('0.5.3-experimental.40').encode())
        with mock.patch.object(updater.urllib.request, 'urlopen', fake):
            self.assertEqual(updater.latest_version('tok', 'my/branch'), '0.5.3-experimental.40')
        self.assertIn('contents/version.py?ref=my%2Fbranch', calls[0].full_url)
        self.assertEqual(calls[0].get_header('Authorization'), 'Bearer tok')
        import urllib.error
        def denied(request, timeout=0):
            raise urllib.error.HTTPError(request.full_url, 401, 'no', {}, None)
        with mock.patch.object(updater.urllib.request, 'urlopen', denied):
            with self.assertRaises(updater.UpdateError) as caught:
                updater.latest_version('bad')
            self.assertIn('key', str(caught.exception))
        # A wrong or expired key: the public project is read without it.
        tried = []
        def public(request, timeout=0):
            tried.append(request.get_header('Authorization'))
            if request.get_header('Authorization'):
                raise urllib.error.HTTPError(request.full_url, 401, 'bad key', {}, None)
            return Reply(version_py('0.5.3-experimental.48').encode())
        with mock.patch.object(updater.urllib.request, 'urlopen', public):
            self.assertEqual(updater.latest_version('github_pat_old'), '0.5.3-experimental.48')
            self.assertEqual(updater.latest_version(''), '0.5.3-experimental.48')
        self.assertEqual(tried[:2], ['Bearer github_pat_old', None])

    @unittest.skipUnless(os.environ.get('STROKESCRIBE_TEST_TOKEN'), 'needs a GitHub token (CI)')
    def test_real_github_check_and_download(self):
        token = os.environ['STROKESCRIBE_TEST_TOKEN']
        branch = os.environ.get('STROKESCRIBE_TEST_BRANCH') or updater.DEFAULT_BRANCH
        version = updater.latest_version(token, branch)
        self.assertGreaterEqual(updater.parse_version(version), (0, 5, 3, 38))
        zip_path = updater.download(token, self.dir / 'real.zip', branch)
        self.assertEqual(updater.zip_version(zip_path), version)
        updater.apply_zip(zip_path, self.app)
        self.assertNotEqual((self.app / 'app.py').read_text(), 'old app')
        self.assertEqual((self.app / '.venv/Lib/site.py').read_text(), 'my packages')


@unittest.skipIf(SKIP, 'needs Qt')
class UpdateWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['STROKESCRIBE_CONFIG_DIR'] = tmp
            try:
                from update_dialog import UpdateDialog, KeyDialog
                from PySide6.QtWidgets import QLineEdit
                d = UpdateDialog(None, latest='0.5.3-experimental.999', auto_check=False)
                self.assertTrue(d.update_button.isEnabled())              # public project: no key needed
                self.assertIn('999', d.version_label.text())
                self.assertEqual(d.key_button.text(), 'Key…')
                # The key is never shown in the update window itself.
                self.assertEqual(d.findChildren(QLineEdit), [])
                d.connected = True; d.refresh()
                self.assertTrue(d.connection.text().startswith('✓'))
                self.assertEqual(d.connection.objectName(), 'good')
                d.connected, d.connection_text = False, 'No connection to GitHub.'; d.refresh()
                self.assertTrue(d.connection.text().startswith('✗'))
                self.assertEqual(d.connection.objectName(), 'bad')
                # The key pop-up checks the key before saving it.
                k = KeyDialog(d, '')
                k.token.setText('hello'); k.save()
                self.assertTrue(k.problem.text().startswith('✗'))
                self.assertNotEqual(k.result(), KeyDialog.DialogCode.Accepted)
                k.token.setText('github_pat_' + 'x' * 82); k.save()
                self.assertEqual(k.result(), KeyDialog.DialogCode.Accepted)
                self.assertEqual(k.token.echoMode(), QLineEdit.EchoMode.Password)
                d.settings['token'] = k.value(); d.save(); d.refresh()
                self.assertEqual(d.key_button.text(), 'Change key…')
                d.close()
                self.assertEqual(updater.load_settings()['token'], 'github_pat_' + 'x' * 82)
                from app import Window
                w = Window(); w.update_found('0.5.3-experimental.999')
                self.assertTrue(w.update_banner.isVisibleTo(w))
                self.assertIn('experimental.999', w.update_banner_text.text())
                w.close()
            finally:
                del os.environ['STROKESCRIBE_CONFIG_DIR']


if __name__ == '__main__':
    unittest.main(verbosity=2)
