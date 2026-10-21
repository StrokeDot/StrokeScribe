"""Visible startup diagnostics for the Windows launcher."""
import sys, os, traceback, faulthandler
from pathlib import Path

root=Path(__file__).resolve().parent


def _error_box(text):
    """The installed app has no console: show start-up problems in a window."""
    if sys.platform=='win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,text,'StrokeScribe could not start',0x10)
        except Exception:
            pass


def recover_pending_update():
    """Recover an interrupted file transaction before any GUI or render imports.

    This uses the already-present updater module from the application folder.
    It is safe to call repeatedly: no pending journal is a normal no-op.
    """
    import updater
    return updater.recover_interrupted_update(root)



def open_startup_path(window,path,*,initial=False):
    """Use the real project loader, including its unsaved-work protection."""
    from PySide6.QtWidgets import QMessageBox
    path=Path(path)
    if initial:
        import autosave
        if autosave.pending():
            restored=window.offer_recovery()
            window._shell_recovery_offered=True
            if not restored and autosave.pending():
                window._keep_autosave=True
                return False
    if path.suffix.lower()=='.strokescribe':
        return bool(window.open_project(str(path)))
    if path.suffix.lower()=='.svg':
        from engine import import_svg
        try:drawing=import_svg(path)
        except Exception as exc:
            QMessageBox.warning(window,'Cannot import',str(exc));return False
        if not window.confirm_leave_project('open another drawing'):return False
        window.set_drawing(drawing)
        window.project_path=None
        return True
    QMessageBox.warning(window,'Open file','Choose a .strokescribe project or an SVG drawing.')
    return False

def main():
    # Recovery remains before app/render imports. Native secondary instances
    # forward before creating a Window or touching the primary's startup log.
    incoming=str(Path(sys.argv[1]).resolve()) if len(sys.argv)>1 else None
    os.chdir(root)
    log=None;broker=None
    try:
        recovered=recover_pending_update()
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('StrokeDot.StrokeScribe')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QIcon
        app=QApplication(sys.argv);app.setStyle('Fusion')
        app.setApplicationName('StrokeScribe');app.setOrganizationName('StrokeDot')
        from version import APP_VERSION
        app.setApplicationVersion(APP_VERSION)
        app.setWindowIcon(QIcon(str(root/'assets'/'strokescribe.ico')))
        pending=[incoming];initial=[True];dispatching=[False]
        if os.environ.get('STROKESCRIBE_NATIVE_HOST')=='1':
            from shell_integration import ProjectBroker,server_name
            broker=ProjectBroker(server_name(root),app)
            if not broker.claim():
                if ProjectBroker.forward(broker.name,incoming):return 0
                _error_box('StrokeScribe is starting or busy. Please try opening the project again.')
                return 1
            broker.requested.connect(pending.append)
            app.aboutToQuit.connect(broker.close)
        log_dir=root
        try:(root/'startup.log').open('a').close()
        except OSError:
            log_dir=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'StrokeScribe'
            log_dir.mkdir(parents=True,exist_ok=True)
        log=(log_dir/'startup.log').open('w',encoding='utf-8')
        def stage(message):
            if sys.stdout is not None:
                try:print(message,flush=True)
                except (OSError,UnicodeError):pass
            log.write(message+'\n');log.flush()
        faulthandler.enable(file=log)
        faulthandler.dump_traceback_later(20,file=log)
        stage('Checking unfinished updates...')
        if recovered['recovered']:stage('Recovered interrupted update; restored version '+str(recovered.get('version')))
        stage('Starting StrokeScribe...')
        from app import Window
        stage('Creating the Windows interface...')
        import autosave
        needs_recovery=bool(autosave.pending())
        window=Window();window.setWindowIcon(app.windowIcon())
        window.showNormal();window.raise_();window.activateWindow()
        def open_pending():
            if dispatching[0] or not pending or QApplication.activeModalWidget() is not None:return
            for work in (window.builder,window.worker):
                if work is not None and work.isRunning():return
            path=pending.pop(0);first=initial[0];initial[0]=False
            dispatching[0]=True
            try:
                if path:
                    if open_startup_path(window,path,initial=needs_recovery and not getattr(window,'_shell_recovery_offered',False)):stage('Opened file: '+str(path))
                    else:stage('File open cancelled or failed: '+str(path))
                window.showNormal();window.raise_();window.activateWindow()
            finally:dispatching[0]=False
        requests=QTimer(app);requests.setInterval(50);requests.timeout.connect(open_pending);requests.start()
        def ready():
            stage(f'Ready: {len(window.drawing.strokes)} strokes loaded. Press Play in the StrokeScribe window.')
            faulthandler.cancel_dump_traceback_later()
            if os.environ.get('STROKESCRIBE_STARTUP_TEST')=='1':
                (root/'test-output').mkdir(exist_ok=True)
                window.grab().save(str(root/'test-output'/'native-startup.png'))
                delay=max(1000,min(15000,int(os.environ.get('STROKESCRIBE_STARTUP_TEST_MS','1000'))))
                QTimer.singleShot(delay,app.quit)
        QTimer.singleShot(500,ready)
        result=app.exec()
        if broker:broker.close()
        faulthandler.cancel_dump_traceback_later();faulthandler.disable();log.close();log=None
        return result
    except Exception:
        if sys.stderr is not None:traceback.print_exc()
        if log is not None:traceback.print_exc(file=log);log.flush()
        _error_box('StrokeScribe could not start.\n\n'+traceback.format_exc()[-1500:])
        if broker:broker.close()
        return 1
    finally:
        if log is not None:log.close()

if __name__=='__main__':
    sys.exit(main())
