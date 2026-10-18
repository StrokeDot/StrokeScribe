"""UI regressions for live, one-card-per-model updates (offline Qt fixtures)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QMessageBox

import ai_engine
import ai_models
from create_image_dialog import CreateImageDialog
from image_generator_updates import UpdatePanel
from model_updates_live import ModelState, RemoteRevision

APP = QApplication.instance() or QApplication([])


class DrawerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"STROKESCRIBE_CONFIG_DIR": self.tmp.name})
        self.env.start()
        settings = ai_engine.load_settings()
        settings["root"] = str(Path(self.tmp.name) / "engine")
        ai_engine.save_settings(settings)
        self.scan_patch = patch("model_updates_live.inspect_models", return_value=())
        self.scan_mock = self.scan_patch.start()
        self.dialog = CreateImageDialog(hardware=ai_models.Hardware("Test GPU", 16, 64, True))
        self.addCleanup(self.scan_patch.stop)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        w = self.dialog.live_update_worker
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(8000)
        self.dialog.close()
        APP.processEvents()
        self.env.stop()
        self.tmp.cleanup()

    def wait_scan(self):
        for _ in range(150):
            APP.processEvents()
            if self.dialog.live_update_worker is None:
                return
            QTest.qWait(20)
        self.fail("The live model check did not finish.")

    def show_drawer(self):
        self.dialog.show()
        self.dialog.check_updates_button.click()
        self.wait_scan()
        self.assertTrue(self.dialog.updates_panel.isVisible())
        return self.dialog.updates_panel

    def test_header_triggers_real_background_check_and_keep_open(self):
        drawer = self.show_drawer()
        self.assertEqual(self.scan_mock.call_count, 1)
        self.dialog.check_updates_button.click()
        self.wait_scan()
        self.assertTrue(drawer.isVisible())
        self.assertEqual(self.scan_mock.call_count, 2)
        drawer.close_button.click()
        self.assertFalse(drawer.isVisible())

    def test_one_card_per_real_model_no_demo_duplicates(self):
        drawer = self.show_drawer()
        state = ModelState("qwen_edit_2511", "Qwen-Image-Edit 2511", "Qwen",
                           "Image editing", "q4", "GGUF Q4", "update_available",
                           "Publisher file differs", True,
                           RemoteRevision("a" * 64, 12), ai_models.QWEN_EDIT.variants[2].diffusion)
        drawer.set_items([state])
        text = " ".join(w.text() for w in drawer.findChildren(QLabel))
        self.assertIn("Updates available (1)", text)
        self.assertIn("Installed models (0)", text)
        self.assertEqual(len(drawer.cards), 1)
        self.assertEqual(sum(card.item.model_id == state.model_id for card in drawer.cards), 1)
        self.assertNotIn("Demonstration data", text)
        self.assertEqual(len([b for b in drawer.findChildren(QPushButton)
                              if b.text() == "Update"]), 1)

    def test_update_button_starts_real_verified_update_worker(self):
        drawer = self.show_drawer()
        state = ModelState("qwen_edit_2511", "Qwen-Image-Edit 2511", "Qwen",
                           "Image editing", "q4", "GGUF Q4", "update_available",
                           "different SHA", True, RemoteRevision("b" * 64, 100),
                           ai_models.QWEN_EDIT.variants[2].diffusion)
        drawer.set_items([state])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(self.dialog, "_run_live_model_worker") as launch, \
             patch.object(self.dialog.engine, "stop") as stop:
            button = next(b for b in drawer.findChildren(QPushButton) if b.text() == "Update")
            button.click()
            launch.assert_called_once()
            worker, mode = launch.call_args.args
            self.assertEqual(mode, "update")
            self.assertIs(worker.state, state)
            stop.assert_called_once()

    def test_unverified_model_never_shows_update_button(self):
        drawer = self.show_drawer()
        state = ModelState("qwen_edit_2511", "Qwen-Image-Edit 2511", "Qwen",
                           "Image editing", "q4", "GGUF Q4", "unverified",
                           "No internet", True,
                           file=ai_models.QWEN_EDIT.variants[2].diffusion)
        drawer.set_items([state])
        self.assertFalse(any(b.text() == "Update" for b in drawer.findChildren(QPushButton)))
        self.assertTrue(any(b.text() == "Check again" for b in drawer.findChildren(QPushButton)))

    def test_model_manager_still_selects_real_model(self):
        self.show_drawer()
        self.dialog.manage_models_button.click()
        APP.processEvents()
        manager = self.dialog.model_manager
        self.assertTrue(manager.isVisible())
        choose = next(b for b in manager.findChildren(QPushButton)
                      if b.property("modelId") == ai_models.QWEN_EDIT.id)
        choose.click()
        APP.processEvents()
        self.assertEqual(self.dialog.task, "edit")
        self.assertEqual(self.dialog.model_box.currentData(), ai_models.QWEN_EDIT.id)

    def test_escape_closes_drawer_preserving_result_and_prompt(self):
        d = self.dialog
        path = Path(self.tmp.name) / "result.png"
        pix = QPixmap(80, 60)
        pix.fill(QColor("#794fe8"))
        pix.save(str(path))
        d.prompt.setPlainText("keep this image prompt")
        d.seed.setValue(1701)
        d.result_path = str(path)
        d.show_result()
        self.show_drawer()
        QTest.keyClick(d.prompt, Qt.Key.Key_Escape)
        APP.processEvents()
        self.assertFalse(d.updates_panel.isVisible())
        self.assertTrue(d.isVisible())
        self.assertEqual(d.prompt.toPlainText(), "keep this image prompt")
        self.assertEqual(d.seed.value(), 1701)
        self.assertEqual(d.result_path, str(path))

    def test_image_only_panel_and_compact_layout(self):
        d = self.dialog
        d.set_task("sound")
        drawer = self.show_drawer()
        self.assertEqual(d.task, "sound")
        self.assertNotIn("Stable Audio", " ".join(x.text() for x in drawer.findChildren(QLabel)))
        for width, height in ((1000, 740), (1480, 900)):
            d.resize(width, height)
            APP.processEvents()
            self.assertLessEqual(d.minimumSizeHint().width(), 1000)
            self.assertLessEqual(d.main_panel.geometry().right(), drawer.geometry().left())
            self.assertGreaterEqual(d.preview.width(), 280)

    def test_title_bar_close_closes_dialog_not_just_panel(self):
        self.show_drawer()
        self.dialog.close()
        APP.processEvents()
        self.assertFalse(self.dialog.isVisible())


class PanelTests(unittest.TestCase):
    def test_injected_models_are_unique_and_actions_use_real_ids(self):
        item = ModelState("unique", "Example Image", "Publisher",
                          "Image generation", "fp8", "Full", "not_installed",
                          "Choose Install", False)
        panel = UpdatePanel(items=[item])
        try:
            self.assertEqual(len(panel.cards), 1)
            calls = []
            panel.action_requested.connect(lambda action, identity: calls.append((action, identity)))
            button = next(b for b in panel.findChildren(QPushButton) if b.text() == "Install")
            button.click()
            self.assertEqual(calls, [("install", "unique")])
        finally:
            panel.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
