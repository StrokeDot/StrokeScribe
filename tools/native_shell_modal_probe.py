"""CI-only instrumentation injected into the disposable installed startup."""
def install(window,app,root,broker):
    import json
    from pathlib import Path
    from PySide6.QtCore import QTimer,Qt
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
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal);dialog.open()
    window._identity_test_modal=dialog
    def delivered(path):
        assert app.activeModalWidget() is dialog,'Request did not arrive during modal dialog'
        assert not decisions,'Project loader ran before the modal dialog closed'
        (out/'modal-queued').write_text('queued')
    broker.requested.connect(delivered)
    timer=QTimer(window);timer.setInterval(50)
    state={'released':False}
    def check():
        if not state['released'] and (out/'modal-release').exists():
            state['released']=True;broker.requested.disconnect(delivered);dialog.reject()
        if state['released'] and decisions:
            try:
                assert window.project_path==before,'Cancel replaced unsaved project'
                assert window.has_unsaved_changes(),'Cancel discarded edits'
                (out/'native-unsaved.json').write_text(json.dumps({'modal_queued':True,'cancel_kept_project':True,'unsaved_kept':True}))
            finally:
                timer.stop();QMessageBox.question=original_question
                window.project_changes.mark_saved(window.project_state());autosave.clear()
    timer.timeout.connect(check);timer.start()
    window._identity_test_timer=timer
    (out/'modal-ready').write_text('ready')
