"""Phase 1 RED tests: unsaved artwork, scene edits, close/open and recovery."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox

import autosave
from project_lifecycle import ProjectChangeTracker

APP = QApplication.instance() or QApplication([])


class TrackerTests(unittest.TestCase):
    def test_setting_edit_marks_dirty_and_save_clears(self):
        c = ProjectChangeTracker()
        self.assertFalse(c.is_dirty)
        c.mark_changed()
        self.assertTrue(c.is_dirty)
        c.mark_saved()
        self.assertFalse(c.is_dirty)

    def test_change_during_pending_history_is_not_missed(self):
        c = ProjectChangeTracker()
        c.mark_saved()
        c.mark_changed()
        self.assertTrue(c.is_dirty)
        self.assertTrue(c.revision > c.saved_revision)


class WindowLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_discard = os.environ.pop("STROKESCRIBE_TEST_AUTODISCARD", None)
        self.old = os.environ.get("STROKESCRIBE_CONFIG_DIR")
        os.environ["STROKESCRIBE_CONFIG_DIR"] = self.tmp.name
        from app import Window
        self.w = Window()
        self.w.show()
        APP.processEvents()

    def tearDown(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.w.close()
        APP.processEvents()
        if self.old is None:
            os.environ.pop("STROKESCRIBE_CONFIG_DIR", None)
        else:
            os.environ["STROKESCRIBE_CONFIG_DIR"] = self.old
        self.tmp.cleanup()

    def test_setting_change_is_dirty_before_history_debounce(self):
        self.assertFalse(self.w.has_unsaved_changes())
        self.w.duration.setValue(self.w.duration.value() + .5)
        self.assertTrue(self.w.has_unsaved_changes())

    def test_scene_and_overlay_edits_mark_dirty(self):
        self.w.add_scene()
        self.assertTrue(self.w.has_unsaved_changes())
        self.w.project_changes.mark_saved()
        import overlays
        self.w.add_overlay(overlays.new_text())
        self.assertTrue(self.w.has_unsaved_changes())

    def test_save_cancel_and_failed_save_keep_project_open(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.w.close())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
             patch.object(self.w, "save_project", return_value=None):
            self.assertFalse(self.w.close())
        self.assertTrue(self.w.isVisible())
        self.assertTrue(self.w.has_unsaved_changes())

    def test_discard_closes_and_clears_autosave(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        self.assertTrue(self.w.autosave_tick())
        self.assertIsNotNone(autosave.pending())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.w.close())
        self.assertIsNone(autosave.pending())

    def test_cancelled_open_preserves_edit_and_recovery(self):
        from projects import save
        other = Path(self.tmp.name) / "other.strokescribe"
        save(other, self.w.project_state())
        self.w.duration.setValue(self.w.duration.value() + .5)
        self.assertTrue(self.w.autosave_tick())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.w.open_project(str(other)))
        self.assertTrue(self.w.has_unsaved_changes())
        self.assertIsNotNone(autosave.pending())

    def test_successful_save_marks_clean(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        with patch.object(self.w, "project_path", str(Path(self.tmp.name) / "saved.strokescribe"), create=True):
            self.w.save_project()
        self.assertFalse(self.w.has_unsaved_changes())
        self.assertIsNone(autosave.pending())

    def test_unsaved_setting_change_is_autosaved_before_history_timer(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        self.assertTrue(self.w.history_timer.isActive())
        self.assertTrue(self.w.autosave_tick())
        self.assertIsNotNone(autosave.pending())

    def test_rejecting_crash_restore_does_not_silently_delete_backup(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        self.assertTrue(self.w.autosave_tick())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.w.offer_recovery())
        self.assertIsNotNone(autosave.pending())


if __name__ == "__main__":
    unittest.main(verbosity=2)
