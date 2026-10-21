"""Shell-open regressions using real project load/save and local IPC."""
import importlib.util,json,os,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import test_project_lifecycle as fixture
from PySide6.QtWidgets import QMessageBox
from PySide6.QtTest import QTest
import projects,startup
APP=fixture.APP

class ShellOpenTests(unittest.TestCase):
    setUp=fixture.WindowLifecycleTests.setUp
    tearDown=fixture.WindowLifecycleTests.tearDown
    def route(self,path):
        router=getattr(startup,'open_startup_path',None)
        self.assertTrue(callable(router),'Startup needs extension-aware project/SVG routing')
        return router(self.w,path)
    def project(self):
        path=Path(self.tmp.name)/'Downloads & Documents'/'Création 日本 #1.strokescribe'
        path.parent.mkdir()
        projects.save(path,self.w.project_state())
        return path
    def test_shell_project_preserves_real_save_format_and_unicode_path(self):
        path=self.project();payload=projects.load(path)
        self.assertTrue(self.route(path))
        self.assertEqual(Path(self.w.project_path),path)
        self.assertFalse(self.w.has_unsaved_changes())
        self.assertEqual(projects.load(path),payload)
    def test_shell_cancel_keeps_dirty_project_and_autosave(self):
        path=self.project();old=self.w.drawing
        self.w.duration.setValue(self.w.duration.value()+1)
        self.assertTrue(self.w.autosave_tick())
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.route(path))
        self.assertIs(self.w.drawing,old);self.assertTrue(self.w.has_unsaved_changes())
        import autosave
        self.assertIsNotNone(autosave.pending())
    def test_shell_failed_save_blocks_project_replacement(self):
        path=self.project();old=self.w.drawing
        self.w.duration.setValue(self.w.duration.value()+1)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save),patch.object(self.w,'save_project',return_value=None):
            self.assertFalse(self.route(path))
        self.assertIs(self.w.drawing,old);self.assertTrue(self.w.has_unsaved_changes())
    def test_shell_discard_opens_and_normal_interface_still_opens(self):
        path=self.project()
        self.w.duration.setValue(self.w.duration.value()+1)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.route(path))
        self.assertFalse(self.w.has_unsaved_changes())
        self.assertTrue(self.w.open_project(str(path)))
    def test_initial_shell_open_preserves_recovered_unsaved_work(self):
        path=self.project()
        self.w.duration.setValue(self.w.duration.value()+2)
        expected=self.w.duration.value();self.assertTrue(self.w.autosave_tick())
        router=getattr(startup,'open_startup_path',None)
        self.assertTrue(callable(router))
        with patch.object(QMessageBox,'question',side_effect=[QMessageBox.StandardButton.Yes,QMessageBox.StandardButton.Cancel]):
            self.assertFalse(router(self.w,path,initial=True))
        self.assertEqual(self.w.duration.value(),expected)
        self.assertTrue(self.w.has_unsaved_changes())
        import autosave
        self.assertIsNotNone(autosave.pending())
        self.assertFalse(self.w.offer_recovery())
    def test_failed_recovery_blocks_later_shell_opens_without_deleting_copy(self):
        path=self.project();self.w.duration.setValue(self.w.duration.value()+1)
        self.assertTrue(self.w.autosave_tick())
        self.w._keep_autosave=True;self.w._shell_recovery_offered=True
        import autosave
        pending=autosave.pending();old=self.w.drawing
        with patch.object(QMessageBox,'warning'):
            self.assertFalse(self.route(path))
        self.assertIs(self.w.drawing,old);self.assertEqual(autosave.pending(),pending)

    def test_svg_argument_still_loads_vector_drawing(self):
        self.assertTrue(self.route(Path(__file__).parent/'samples'/'drawing.svg'))
        self.assertGreater(len(self.w.drawing.strokes),0)
    def test_invalid_project_is_not_treated_as_svg(self):
        path=Path(self.tmp.name)/'broken.strokescribe';path.write_text('bad')
        old=self.w.drawing
        with patch.object(QMessageBox,'warning'):
            self.assertFalse(self.route(path))
        self.assertIs(self.w.drawing,old)

class LocalRequestTests(unittest.TestCase):
    def broker(self):
        self.assertIsNotNone(importlib.util.find_spec('shell_integration'),'Local project-open routing is missing')
        from shell_integration import ProjectBroker
        return ProjectBroker
    def test_only_primary_window_gets_complete_unicode_request(self):
        Broker=self.broker();name='StrokeScribe-test-'+uuid.uuid4().hex
        first=Broker(name);self.addCleanup(first.close);self.assertTrue(first.claim())
        received=[];first.requested.connect(received.append)
        path='C:/Documents & Downloads/日本 Création #1.strokescribe'
        self.assertTrue(Broker.forward(name,path))
        end=time.monotonic()+3
        while not received and time.monotonic()<end:APP.processEvents();QTest.qWait(10)
        self.assertEqual(received,[path])
        second=Broker(name);self.addCleanup(second.close);self.assertFalse(second.claim())
        first.close();self.assertFalse(Broker.forward(name,path))
    def test_fragmented_and_oversized_payloads_are_handled_safely(self):
        Broker=self.broker();name='StrokeScribe-test-'+uuid.uuid4().hex
        first=Broker(name);self.addCleanup(first.close);self.assertTrue(first.claim())
        received=[];first.requested.connect(received.append)
        from PySide6.QtNetwork import QLocalSocket
        client=QLocalSocket();client.connectToServer(name);self.assertTrue(client.waitForConnected(1000))
        payload=json.dumps({'path':'C:/Two words.strokescribe'}).encode()+b'\n'
        client.write(payload[:8]);client.flush();APP.processEvents();self.assertEqual(received,[])
        client.write(payload[8:]);client.flush()
        end=time.monotonic()+2
        while not received and time.monotonic()<end:APP.processEvents();QTest.qWait(10)
        self.assertEqual(received,['C:/Two words.strokescribe']);client.abort()
        self.assertFalse(Broker.forward(name,'x'*40000))
    def test_closed_secondary_does_not_delete_primary_server(self):
        Broker=self.broker();name='StrokeScribe-test-'+uuid.uuid4().hex
        first=Broker(name);self.addCleanup(first.close);self.assertTrue(first.claim())
        second=Broker(name);second.claim();second.close()
        self.assertTrue(Broker.forward(name,None))

if __name__=='__main__':unittest.main()
