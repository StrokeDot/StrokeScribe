"""Visible startup diagnostics for the Windows launcher."""
import sys, os, time, traceback, faulthandler
T0 = time.perf_counter()
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


def main():
    # Only when started by the launcher: export worker processes import this
    # file under another name and must not open a window or touch the log.
    os.chdir(root)
    if sys.platform=='win32':
        try:
            # Own taskbar icon (matches the Start menu shortcut of the installer).
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('StrokeDot.StrokeScribe')
        except Exception:
            pass
    log_dir=root
    try:
        (root/'startup.log').open('a').close()
    except OSError:
        log_dir=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'StrokeScribe'
        log_dir.mkdir(parents=True,exist_ok=True)
    log=(log_dir/'startup.log').open('w',encoding='utf-8')
    def stage(message):
        print(message,flush=True)
        log.write(message+'\n'); log.flush()

    try:
        faulthandler.enable(file=log)
        faulthandler.dump_traceback_later(20,file=log)
        stage('Checking unfinished updates...')
        recovered = recover_pending_update()
        if recovered['recovered']:
            stage('Recovered interrupted update; restored version ' + str(recovered.get('version')))
        stage('Starting StrokeScribe...')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from app import Window
        from engine import import_svg
        t_imports = time.perf_counter()
        stage('Creating the Windows interface...')
        app=QApplication(sys.argv); app.setStyle('Fusion')
        stage('Loading controls...')
        window=Window()
        t_window = time.perf_counter()
        if len(sys.argv)>1:
            stage('Loading drawing: '+sys.argv[1])
            window.set_drawing(import_svg(Path(sys.argv[1])))
        window.showMaximized(); window.raise_(); window.activateWindow()   # exp.171: always full screen (it sometimes opened half off the screen)
        if len(sys.argv)<=1:
            window.show_home()          # exp.107: start on Home, not in a project
        window.close_to_home=True       # exp.109: X in a project goes back to Home
        def shown():
            # exp.130: how long starting took, in the user's log (to make it faster).
            try:
                import applog
                applog.info('Start: window on screen after %.1f s (loading the program %.1f s, '
                            'building the window %.1f s)' % (time.perf_counter() - T0, t_imports - T0,
                                                             t_window - t_imports))
            except Exception:
                pass
        QTimer.singleShot(0, shown)
        def compile_ahead():
            # exp.130: after an update, every part of the program is read and prepared the
            # first time it is used (a pause when you first open a panel or export). Here
            # it is prepared in the background, at low priority, while you look at Home.
            try:
                import subprocess
                flags = 0
                if sys.platform == 'win32':
                    flags = 0x08000000 | 0x00004000      # no window, below normal priority
                subprocess.Popen([sys.executable, '-m', 'compileall', '-q', '-l', str(root)],
                                 cwd=str(root), creationflags=flags, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        if os.environ.get('STROKESCRIBE_STARTUP_TEST') != '1':
            QTimer.singleShot(6000, compile_ahead)
        def ready():
            stage(f'Ready: {len(window.drawing.strokes)} strokes loaded. Press Play in the StrokeScribe window.')
            faulthandler.cancel_dump_traceback_later()
            if os.environ.get('STROKESCRIBE_STARTUP_TEST')=='1':
                window.grab().save(str(root/'test-output'/'native-startup.png'))
                QTimer.singleShot(1000,app.quit)
        QTimer.singleShot(500,ready)
        result=app.exec()
        log.close(); sys.exit(result)
    except Exception:
        if sys.stderr is not None: traceback.print_exc()
        traceback.print_exc(file=log); log.flush()
        print('Startup failed. Details are saved in startup.log beside this launcher.',flush=True)
        _error_box('StrokeScribe could not start.\n\n'+traceback.format_exc()[-1500:]+
                   '\n\nDetails: '+str(log_dir/'startup.log'))
        sys.exit(1)


if __name__=='__main__':
    main()
