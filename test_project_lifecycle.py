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
        if self.old_discard is not None:
            os.environ["STROKESCRIBE_TEST_AUTODISCARD"] = self.old_discard

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

    def test_failed_open_restores_original_project_state(self):
        import projects
        other = Path(self.tmp.name) / 'valid.strokescribe'
        projects.save(other, self.w.project_state())
        self.w.duration.setValue(self.w.duration.value() + 1)
        old = self.w.drawing
        old_duration = self.w.duration.value()
        actual_apply = self.w.apply_project
        called = [False]
        def fail_once(data):
            if not called[0]:
                called[0] = True
                self.w.drawing = None
                raise ValueError('Cannot load a damaged artwork component')
            return actual_apply(data)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard), \
             patch.object(self.w, 'apply_project', side_effect=fail_once):
            with patch.object(QMessageBox, 'warning'):
                self.assertFalse(self.w.open_project(str(other)))
        self.assertIsNotNone(self.w.drawing)
        self.assertEqual(self.w.duration.value(), old_duration)
        self.assertTrue(self.w.has_unsaved_changes())

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


    def test_cancelled_library_replacement_keeps_current_artwork(self):
        from types import SimpleNamespace
        source = Path(__file__).parent / 'samples' / 'drawing.svg'
        old = self.w.drawing
        self.w.duration.setValue(self.w.duration.value() + .5)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.w.use_library_item('images', SimpleNamespace(path=source, name='Other SVG'),placement='replace')
        self.assertIs(self.w.drawing, old)

    def test_cancelled_ai_replacement_never_starts_image_builder(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel), \
             patch.object(self.w, 'build_image') as started:
            self.w.use_ai_result('image', 'not-started.png',placement='replace')
        started.assert_not_called()

    def test_cancelled_restart_does_not_launch_new_app(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel), \
             patch('updater.restart') as restart:
            self.w.restart_after_update()
        self.assertTrue(self.w.isVisible())
        restart.assert_not_called()

    def test_scene_reorder_and_transition_are_persisted_dirty(self):
        self.w.add_scene()
        self.w.project_changes.mark_saved(self.w.project_state())
        self.w.move_scene(-1)
        self.assertTrue(self.w.has_unsaved_changes())
        self.w.project_changes.mark_saved(self.w.project_state())
        self.w.scene_transition.setCurrentText('Pan right')
        self.w.scene_transition_changed()
        self.assertTrue(self.w.has_unsaved_changes())

    def test_rejecting_crash_restore_does_not_silently_delete_backup(self):
        self.w.duration.setValue(self.w.duration.value() + .5)
        self.assertTrue(self.w.autosave_tick())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.w.offer_recovery())
        archived = sorted((Path(self.tmp.name) / 'autosave' / 'Recovered copies').glob('*.strokescribe'))
        self.assertEqual(len(archived), 1, 'Declined recovery must be archived rather than deleted')
        import projects
        self.assertIsNotNone(projects.load(archived[0]).get('drawing'))
        self.assertIsNone(autosave.pending())


if __name__ == "__main__":
    unittest.main(verbosity=2)
