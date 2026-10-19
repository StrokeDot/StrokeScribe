"""Dialog and Engine lifecycle regression checks using real CPU fixture processes."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
import ai_engine
import ai_models
from create_image_dialog import AIWorker, CreateImageDialog
from test_owned_process import ProcessFixture, until

APP = QApplication.instance() or QApplication([])


class NativeFinishing:
    """Models Qt's documented finished-before-native-cleanup interval."""
    def __init__(self):
        self.ready = False
        self.cancelled = False
    def isRunning(self): return False
    def wait(self, timeout=0): return self.ready
    def cancel(self): self.cancelled = True


class SlowWorker(QThread):
    def __init__(self):
        super().__init__()
        self.cancel_requested = threading.Event()
        self.release = threading.Event()
    def run(self): self.release.wait(10)
    def cancel(self): self.cancel_requested.set()


class AILifecycleTests(unittest.TestCase):
    def setUp(self):
        self.config = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"STROKESCRIBE_CONFIG_DIR": self.config.name})
        self.env.start()
        self.fixture = ProcessFixture()
        settings = ai_engine.load_settings()
        settings["root"] = str(self.fixture.root)
        ai_engine.save_settings(settings)
        self.engine = ai_engine.Engine(self.fixture.paths)
        self.dialog = CreateImageDialog(engine=self.engine,
                                       hardware=ai_models.Hardware("Test GPU", 16, 64, True))
        self.dialog.show()
        APP.processEvents()

    def tearDown(self):
        for name in ("worker", "live_update_worker"):
            worker = getattr(self.dialog, name)
            if isinstance(worker, SlowWorker):
                worker.release.set()
                worker.wait(5000)
            setattr(self.dialog, name, None)
        self.engine.stop()
        self.dialog.close()
        self.dialog.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        self.fixture.close()
        self.env.stop()
        self.config.cleanup()

    def start_engine(self):
        self.engine.start(timeout=10)
        return self.fixture.workers()

    def test_two_real_generations_keep_one_engine_warm_until_dialog_exit(self):
        self.start_engine()
        first = self.engine._get("/system_stats")["pid"]
        worker = AIWorker("generate")
        worker._generate(self.engine, {}, None)
        worker._generate(self.engine, {}, None)
        stats = self.engine._get("/system_stats")
        self.assertEqual(stats, {"pid": first, "generations": 2})
        self.dialog.close()
        self.assertTrue(until(lambda: all(not p.alive() for p in self.fixture.probes), 5))

    def test_default_release_covers_each_genuine_dialog_exit(self):
        # Each subcase owns a fresh CPU server; accepted/rejected must both release it.
        for route in ("close", "reject", "accept", "done_accept", "done_reject"):
            with self.subTest(route=route):
                self.dialog.show()
                self.start_engine()
                workers = list(self.fixture.probes)
                if route.startswith("done_"):
                    self.dialog.done(QDialog.DialogCode.Accepted if route == "done_accept"
                                     else QDialog.DialogCode.Rejected)
                else:
                    getattr(self.dialog, route)()
                APP.processEvents()
                self.assertFalse(self.dialog.isVisible())
                self.assertTrue(until(lambda: all(not p.alive() for p in workers), 5),
                                route + " left owned AI memory alive")
                for probe in workers: probe.close()
                self.fixture.probes = []
                for path in self.fixture.root.glob("*.pid"): path.unlink()
                for path in self.fixture.root.glob("*.ready"): path.unlink()

    def test_saved_optout_keeps_engine_between_dialog_sessions(self):
        workers = self.start_engine()
        self.assertTrue(hasattr(self.dialog, "release_ai_memory"),
                        "Default-on memory release preference must be visible")
        self.assertTrue(self.dialog.release_ai_memory.isChecked())
        self.dialog.release_ai_memory.setChecked(False)
        self.assertFalse(ai_engine.load_settings()["release_ai_memory_on_close"])
        self.dialog.close()
        self.assertTrue(all(p.alive() for p in workers))
        next_dialog = CreateImageDialog(engine=self.engine,
                                       hardware=ai_models.Hardware("Test GPU", 16, 64, True))
        try:
            self.assertFalse(next_dialog.release_ai_memory.isChecked())
            next_dialog.show()
            next_dialog.close()
            self.assertTrue(all(p.alive() for p in workers))
        finally:
            next_dialog.deleteLater()
            APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        # Application shutdown still owns an explicit stop independently of preference.
        self.engine.stop()
        self.assertTrue(until(lambda: all(not p.alive() for p in workers), 5))

    def test_accept_done_and_use_preserve_running_worker_and_result_callback(self):
        worker = SlowWorker()
        self.dialog.worker = worker
        worker.start()
        self.assertTrue(until(worker.isRunning))
        delivered = []
        self.dialog.use_result = lambda *a: delivered.append(a)
        self.dialog.result_path = "pending.png"
        for route in ("accept", "done", "use", "reject", "close"):
            with self.subTest(route=route):
                if route == "done": self.dialog.done(QDialog.DialogCode.Accepted)
                else: getattr(self.dialog, route)()
                APP.processEvents()
                self.assertTrue(self.dialog.isVisible(), route + " dismissed active QThread")
                self.assertEqual(delivered, [], "Result must not be applied before a safe exit")
        self.assertTrue(worker.cancel_requested.is_set())

    def test_all_routes_wait_for_both_workers_native_cleanup(self):
        for name in ("worker", "live_update_worker"):
            for route in ("accept", "done", "use", "reject", "close"):
                with self.subTest(worker=name, route=route):
                    worker = NativeFinishing()
                    setattr(self.dialog, name, worker)
                    self.dialog.show()
                    delivered = []
                    self.dialog.use_result = lambda *a: delivered.append(a)
                    self.dialog.result_path = "pending.png"
                    if route == "done": self.dialog.done(QDialog.DialogCode.Accepted)
                    else: getattr(self.dialog, route)()
                    APP.processEvents()
                    self.assertTrue(self.dialog.isVisible(), "Native QThread cleanup still pending")
                    self.assertEqual(delivered, [])
                    worker.ready = True
                    setattr(self.dialog, name, None)

    def test_regular_worker_reference_is_retained_until_native_cleanup(self):
        finishing = NativeFinishing()
        self.dialog.worker = finishing
        self.assertTrue(hasattr(self.dialog, "on_worker_finished"),
                        "Regular AI workers need the same native cleanup safeguard as model workers")
        with patch("create_image_dialog.QTimer.singleShot") as retry:
            self.dialog.on_worker_finished()
            self.assertIs(self.dialog.worker, finishing)
            self.assertTrue(retry.called)
            finishing.ready = True
            self.dialog.on_worker_finished()
        self.assertIsNone(self.dialog.worker)

    def test_start_cannot_replace_a_worker_still_in_native_cleanup(self):
        finishing = NativeFinishing()
        self.dialog.worker = finishing
        replacement = AIWorker("download", paths=self.fixture.paths, files=[], name="fixture")
        try:
            self.dialog._start(replacement, lambda _: None)
            self.assertIs(self.dialog.worker, finishing)
            self.assertFalse(replacement.isRunning())
        finally:
            replacement.wait(5000)

    def test_escape_only_closing_drawer_keeps_engine_and_dialog_alive(self):
        workers = self.start_engine()
        self.dialog._drawer_open = True
        self.dialog.updates_panel.show()
        self.dialog.reject()
        APP.processEvents()
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(all(p.alive() for p in workers))

    def test_reader_is_reaped_across_server_restart(self):
        self.start_engine()
        self.assertTrue(hasattr(self.engine, "_reader"),
                        "Engine must retain its reader until owned process cleanup completes")
        reader = self.engine._reader
        proc = self.engine.proc
        self.engine.stop()
        self.assertFalse(reader.is_alive())
        self.assertTrue(proc.stdout.closed)
        self.engine.start(timeout=10)
        self.assertTrue(self.engine.running())
        self.assertIsNot(self.engine._reader, reader)

    def test_cancelled_start_releases_owned_descendants(self):
        with self.assertRaises(ai_engine.Cancelled):
            self.engine.start(timeout=10, cancelled=lambda: True)
        self.assertFalse(self.engine.running())


if __name__ == "__main__":
    unittest.main(verbosity=2)
