"""CI-only instrumentation injected into the disposable installed startup."""
def install(window,app,root):
    import json
    from pathlib import Path
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    import autosave
    out=Path(root)/'test-output'
    before=window.project_path
    window.duration.setValue(window.duration.value()+1)
    assert window.has_unsaved_changes()
    decisions=[]
    original_question=QMessageBox.question
    def cancel(*args,**kwargs):
        decisions.append(True)
        return QMessageBox.StandardButton.Cancel
    QMessageBox.question=cancel
    dialog=QMessageBox(window);dialog.setText('Disposable modal queue test')
    dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
    dialog.setWindowModality(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.WindowModality.ApplicationModal)
    dialog.open()
    window._identity_test_modal=dialog
    (out/'modal-ready').write_text('ready')
    def still_queued():
        assert not decisions,'Shell request reached project loader while modal was open'
        (out/'modal-queued').write_text('queued')
    QTimer.singleShot(800,still_queued)
    QTimer.singleShot(1600,dialog.reject)
    def checked():
        try:
            assert decisions,'Expected Save / Discard / Cancel for queued shell request'
            assert window.project_path==before,'Cancel replaced unsaved project'
            assert window.has_unsaved_changes(),'Cancel discarded edits'
            (out/'native-unsaved.json').write_text(json.dumps({'modal_queued':True,'cancel_kept_project':True,'unsaved_kept':True}))
        finally:
            QMessageBox.question=original_question
            window.project_changes.mark_saved(window.project_state())
            autosave.clear()
    QTimer.singleShot(2300,checked)
