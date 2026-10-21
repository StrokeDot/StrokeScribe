"""Installed-host test harness, copied only to a disposable runner's startup.py.
Never installed by the application package and never used on a user's PC.
"""
import os,sys,json,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'test-output'
def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from shell_integration import ProjectBroker,server_name
    app=QApplication(sys.argv)
    mode=sys.argv[1] if len(sys.argv)>1 else 'replacement'
    if mode=='secondary-hold':
        import time
        assert os.environ.get('STROKESCRIBE_SECONDARY_LAUNCH')=='1'
        (OUT/'native-secondary-ready').write_text(str(os.getpid()))
        deadline=time.monotonic()+20
        while not (OUT/'native-restarted.json').exists() and time.monotonic()<deadline:time.sleep(.02)
        assert (OUT/'native-restarted.json').exists(),'Restart failed while secondary retained a native handle'
        return 0
    assert os.environ.get('STROKESCRIBE_SECONDARY_LAUNCH')=='0'
    broker=ProjectBroker(server_name(ROOT),app)
    assert broker.claim(),'Replacement failed to acquire project broker'
    app.aboutToQuit.connect(broker.close)
    if mode=='workers':
        assert Path(sys.executable)==ROOT/'runtime'/'pythonw.exe',sys.executable
        from engine import import_svg,export_frames
        from PIL import Image
        drawing=import_svg(ROOT/'samples'/'drawing.svg')
        count=export_frames(drawing,OUT/'native-export',duration=.3,fps=60,
                            width=160,height=90,hold_duration=0,workers=2)
        sequence=json.loads((OUT/'native-export'/'sequence.json').read_text())
        assert sequence['cpu_workers']==2,sequence
        frames=sorted((OUT/'native-export').glob('frame_*.png'))
        assert len(frames)==count
        assert Image.open(frames[0]).getchannel('A').getextrema()==(0,0)
        lo,hi=Image.open(frames[-1]).getchannel('A').getextrema()
        assert lo==0 and hi>0
        import ai_engine
        lines=[]
        ai_engine._run([ai_engine._base_python(),'-c',
            'import PySide6.QtWidgets, numpy, cv2, onnxruntime; print("AI subprocess imports OK")'],
            lines.append,lambda:False,cwd=str(ROOT))
        assert 'AI subprocess imports OK' in lines,lines
        (OUT/'native-workers.json').write_text(json.dumps({
            'sys_executable':sys.executable,'frames':count,'cpu_workers':2,
            'alpha_extrema':[lo,hi],'ai_subprocess':'real imports; no GPU model inference'}))
        broker.close();return 0
    if mode=='restart':
        import updater,subprocess,time
        secondary=subprocess.Popen([str(ROOT/'StrokeScribe.exe'),'secondary-hold'],cwd=str(ROOT))
        deadline=time.monotonic()+10
        while not (OUT/'native-secondary-ready').exists() and time.monotonic()<deadline:time.sleep(.02)
        assert (OUT/'native-secondary-ready').exists()
        def restart():
            updater.restart(ROOT)
            # The replacement is required to wait for this process and mutex.
            QTimer.singleShot(250,app.quit)
        QTimer.singleShot(10,restart)
        return app.exec()
    assert mode=='replacement',mode
    (OUT/'native-restarted.json').write_text(json.dumps({'pid':os.getpid(),'broker_claimed':True}))
    QTimer.singleShot(200,app.quit)
    return app.exec()
if __name__=='__main__':
    try:sys.exit(main())
    except BaseException as exc:
        if not isinstance(exc,SystemExit) or exc.code:
            (OUT/'native-probe-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
