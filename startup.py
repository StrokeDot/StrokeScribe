"""Visible startup diagnostics for the Windows launcher."""
import sys, os, traceback, faulthandler
from pathlib import Path

root=Path(__file__).resolve().parent


def main():
    # Only when started by the launcher: export worker processes import this
    # file under another name and must not open a window or touch the log.
    os.chdir(root)
    log=(root/'startup.log').open('w',encoding='utf-8')
    def stage(message):
        print(message,flush=True)
        log.write(message+'\n'); log.flush()

    try:
        faulthandler.enable(file=log)
        faulthandler.dump_traceback_later(20,file=log)
        stage('Starting StrokeScribe...')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from app import Window
        from engine import import_svg
        stage('Creating the Windows interface...')
        app=QApplication(sys.argv); app.setStyle('Fusion')
        stage('Loading controls...')
        window=Window()
        if len(sys.argv)>1:
            stage('Loading drawing: '+sys.argv[1])
            window.set_drawing(import_svg(Path(sys.argv[1])))
        window.showNormal(); window.raise_(); window.activateWindow()
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
        traceback.print_exc(); traceback.print_exc(file=log); log.flush()
        print('Startup failed. Details are saved in startup.log beside this launcher.',flush=True)
        sys.exit(1)


if __name__=='__main__':
    main()
