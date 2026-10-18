"""Phase 2.2 RED regression tests for recoverable, staged updates.

Temporary fixtures only. These tests NEVER update the installed application.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import updater


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=self.root / 'app'
        self.app.mkdir()
        self.previous={
            'version.py': 'APP_VERSION = "1.0.0"\n',
            'app.py': 'old app',
            'core.py': 'old core',
            'requirements.txt': 'numpy\n',
            '.venv/keep.txt': 'virtual-env',
            'user-notes.txt': 'my notes',
            'assets/brush.txt': 'old brush',
        }
        for rel, data in self.previous.items():
            out=self.app / rel
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(data)
        self.new={
            'version.py': 'APP_VERSION = "1.0.1"\n',
            'app.py': 'new app',
            'core.py': 'new core',
            'requirements.txt': 'numpy\n',
            'assets/brush.txt': 'new brush',
            'fresh.py': 'new file',
        }

    def zip_with(self, entries=None):
        path=self.root/'candidate.zip'
        with zipfile.ZipFile(path,'w') as z:
            for rel, data in (self.new if entries is None else entries).items():
                z.writestr('repo/'+rel,data)
        return path

    def assert_old(self):
        for name, value in self.previous.items():
            self.assertEqual((self.app/name).read_text(),value,name)
        self.assertFalse((self.app/'fresh.py').exists())

    def test_journal_and_backup_are_flushed_before_live_file_replacement(self):
        original=updater.os.fsync
        calls=[]
        def observed(fd):
            calls.append(fd)
            return original(fd)
        with patch.object(updater.os,'fsync',side_effect=observed):
            updater.apply_zip(self.zip_with(),self.app)
        self.assertGreaterEqual(len(calls),2,
                                'Journal and staged files need disk flushes before commit')

    def test_failed_staging_write_does_not_touch_installed_app(self):
        candidate=self.zip_with()
        real=Path.write_bytes
        def fail_staging(target,payload):
            if any(part.startswith('.strokescribe-update-') for part in target.parts):
                raise OSError('disk full while staging')
            return real(target,payload)
        with patch.object(Path,'write_bytes',autospec=True,side_effect=fail_staging):
            with self.assertRaises(OSError):
                updater.stage_update(candidate,self.app)
        self.assert_old()
        self.assertFalse((self.app/updater.JOURNAL).exists())

    def test_stage_has_no_effect_on_active_application(self):
        staged=updater.stage_update(self.zip_with(),self.app)
        self.assertIsNotNone(staged)
        self.assert_old()
        self.assertFalse((self.app / '.strokescribe-update-journal.json').exists())

    def test_successful_commit_can_be_rolled_back(self):
        result=updater.commit_update(updater.stage_update(self.zip_with(),self.app))
        self.assertEqual(result['version'],'1.0.1')
        self.assertEqual((self.app/'app.py').read_text(),'new app')
        self.assertEqual((self.app/'fresh.py').read_text(),'new file')
        self.assertTrue(updater.can_roll_back(self.app))
        self.assertEqual(updater.roll_back(self.app),'1.0.0')
        self.assert_old()

    def test_midway_file_replace_exception_auto_restores_old_app(self):
        real=updater.os.replace
        writes=[0]
        def injected(source,dest):
            target=Path(dest)
            if target.parent==self.app and target.name in ('app.py','core.py','version.py'):
                writes[0]+=1
                if writes[0]==2:
                    raise OSError('simulated disk failure halfway through')
            return real(source,dest)
        with patch.object(updater.os,'replace',side_effect=injected):
            with self.assertRaises(updater.UpdateError):
                updater.apply_zip(self.zip_with(),self.app)
        self.assertGreaterEqual(writes[0],2)
        self.assert_old()
        self.assertFalse(updater.can_roll_back(self.app))

    def test_interrupted_process_is_restored_from_startup_journal(self):
        real=updater.os.replace
        writes=[0]
        def interrupted(source,dest):
            target=Path(dest)
            if target.parent==self.app and target.name in ('app.py','core.py','version.py'):
                writes[0]+=1
                if writes[0]==2:
                    raise KeyboardInterrupt('simulated power cut')
            return real(source,dest)
        with patch.object(updater.os,'replace',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                updater.apply_zip(self.zip_with(),self.app)
        self.assertTrue((self.app/'.strokescribe-update-journal.json').exists())
        status=updater.recover_interrupted_update(self.app)
        self.assertTrue(status['recovered'])
        self.assert_old()
        self.assertFalse((self.app/'.strokescribe-update-journal.json').exists())

    def test_launcher_recovers_interrupted_update_before_loading_ui(self):
        # The launcher must not attempt a potentially mixed Qt/application
        # import before inspecting the durable journal.
        import startup
        real=updater.os.replace
        called=[0]
        def interrupt(source,dest):
            target=Path(dest)
            if target.parent==self.app and target.name=='core.py':
                called[0]+=1
                if called[0]==1:
                    raise KeyboardInterrupt('power loss')
            return real(source,dest)
        with patch.object(updater.os,'replace',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                updater.apply_zip(self.zip_with(),self.app)
        with patch.object(startup,'root',self.app):
            result=startup.recover_pending_update()
        self.assertTrue(result['recovered'])
        self.assert_old()

    def test_power_loss_after_backup_rotation_preserves_old_install_and_rollback(self):
        previous_backup=self.app/updater.BACKUP
        previous_backup.mkdir()
        (previous_backup/'update.json').write_text(json.dumps({
            'from':'0.9.0','to':'1.0.0','added':[]
        }))
        (previous_backup/'app.py').write_text('previous previous version')
        real=updater.os.replace
        def lose_power(source,dest):
            if Path(dest)==previous_backup and Path(source).name=='backup':
                raise KeyboardInterrupt('power lost between backup renames')
            return real(source,dest)
        with patch.object(updater.os,'replace',side_effect=lose_power):
            with self.assertRaises(KeyboardInterrupt):
                updater.apply_zip(self.zip_with(),self.app)
        self.assertTrue((self.app/updater.JOURNAL).exists())
        result=updater.recover_interrupted_update(self.app)
        self.assertTrue(result['recovered'])
        self.assert_old()
        self.assertEqual((previous_backup/'app.py').read_text(),'previous previous version')

    def test_power_loss_after_new_backup_installed_can_still_recover(self):
        previous_backup=self.app/updater.BACKUP
        previous_backup.mkdir()
        (previous_backup/'update.json').write_text(json.dumps({
            'from':'0.9.0','to':'1.0.0','added':[]
        }))
        (previous_backup/'app.py').write_text('previous previous version')
        real=updater._atomic_json
        writes=[0]
        def interrupt(path,data):
            writes[0]+=1
            if writes[0]==2:
                raise KeyboardInterrupt('power lost after backup swap')
            return real(path,data)
        with patch.object(updater,'_atomic_json',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                updater.apply_zip(self.zip_with(),self.app)
        self.assertTrue((self.app/updater.JOURNAL).exists())
        self.assertTrue(updater.recover_interrupted_update(self.app)['recovered'])
        self.assert_old()
        self.assertEqual((previous_backup/'app.py').read_text(),'previous previous version')
        self.assertFalse(updater.recover_interrupted_update(self.app)['recovered'])

    def test_second_failed_attempt_retains_previous_backup(self):
        # A retry after an ordinary error must not destroy the prior
        # successful update's rollback snapshot.
        first = updater.apply_zip(self.zip_with(),self.app)
        self.assertEqual(first['version'],'1.0.1')
        old_backup=(self.app/updater.BACKUP/'app.py').read_bytes()
        newer=dict(self.new, **{'app.py':'newer app','version.py':'APP_VERSION = "1.0.2"\\n'})
        candidate=self.zip_with(newer)
        real=updater.os.replace
        def broken(source,dest):
            if Path(dest)==self.app/'app.py':
                raise OSError('disk full')
            return real(source,dest)
        with patch.object(updater.os,'replace',side_effect=broken):
            with self.assertRaises(updater.UpdateError):
                updater.apply_zip(candidate,self.app)
        self.assertEqual((self.app/'app.py').read_text(),'new app')
        self.assertEqual((self.app/updater.BACKUP/'app.py').read_bytes(),old_backup)

    def test_existing_rollback_backup_survives_failed_update(self):
        former=self.app/updater.BACKUP
        former.mkdir()
        (former/'update.json').write_text(json.dumps({'from':'0.9','to':'1.0.0','added':[]}))
        (former/'app.py').write_text('v0.9')
        with patch.object(updater.os,'replace',side_effect=lambda *_: (_ for _ in ()).throw(OSError('disk full'))):
            with self.assertRaises((OSError,updater.UpdateError)):
                updater.apply_zip(self.zip_with(),self.app)
        self.assert_old()
        self.assertEqual((former/'app.py').read_text(),'v0.9')

    def test_dependency_change_refuses_before_modifying_installed_app(self):
        data=dict(self.new, **{'requirements.txt':'numpy\nnew-dependency\n'})
        with self.assertRaisesRegex(updater.UpdateError,'installer|dependencies|packages'):
            updater.apply_zip(self.zip_with(data),self.app)
        self.assert_old()
        self.assertFalse(updater.can_roll_back(self.app))

    def test_bad_version_does_not_update_any_active_files(self):
        data=dict(self.new, **{'version.py':'not a version at all'})
        with self.assertRaises(updater.UpdateError):
            updater.apply_zip(self.zip_with(data),self.app)
        self.assert_old()

    def test_truncated_zip_does_not_change_installed_app(self):
        path=self.zip_with()
        path.write_bytes(path.read_bytes()[:-40])
        with self.assertRaises((updater.UpdateError,zipfile.BadZipFile)):
            updater.apply_zip(path,self.app)
        self.assert_old()

    def test_identical_files_are_not_rewritten(self):
        data=dict(self.new, **{'core.py':self.previous['core.py']})
        result=updater.apply_zip(self.zip_with(data),self.app)
        self.assertEqual(result['version'],'1.0.1')
        self.assertFalse((self.app/updater.BACKUP/'core.py').exists())
        self.assertEqual((self.app/'core.py').read_text(),'old core')
        updater.roll_back(self.app)
        self.assert_old()


if __name__=='__main__':
    unittest.main(verbosity=2)
