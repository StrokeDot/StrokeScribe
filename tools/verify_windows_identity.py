"""Hosted Windows installation/shell verification. NEVER run on a user's installation."""
import ctypes,json,os,subprocess,sys,time,winreg
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PROGID='StrokeDot.StrokeScribe.Project'
EXT=r'Software\Classes\.strokescribe'
CLASSES='Software'+chr(92)+'Classes'+chr(92)
NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)

def read(key,name=''):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as handle:
            return winreg.QueryValueEx(handle,name)[0]
    except FileNotFoundError:return None

def write(key,value,name=''):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_WRITE|winreg.KEY_WOW64_64KEY) as handle:
        winreg.SetValueEx(handle,name,0,winreg.REG_SZ,value)

def wait_for(predicate,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.05)
    raise AssertionError('Timed out waiting for installed app behavior')

def log_text(target):
    try:return (target/'startup.log').read_text(encoding='utf-8')
    except (OSError,UnicodeError):return ''

def powershell(text,env=None):
    raw=subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command','[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; '+text],
            env=env,creationflags=NO_WINDOW)
    return json.loads(raw.decode('utf-8-sig'))

class SHFILEINFOW(ctypes.Structure):
    _fields_=[('icon',ctypes.c_void_p),('index',ctypes.c_int),('attributes',ctypes.c_uint32),
              ('display',ctypes.c_wchar*260),('type',ctypes.c_wchar*80)]

def shell_icon(path):
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    shell.SHGetFileInfoW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.POINTER(SHFILEINFOW),ctypes.c_uint32,ctypes.c_uint32]
    shell.SHGetFileInfoW.restype=ctypes.c_size_t
    info=SHFILEINFOW()
    result=shell.SHGetFileInfoW(str(path),0,ctypes.byref(info),ctypes.sizeof(info),0x100|0x400|0x1)
    if not result or not info.icon:raise AssertionError('Shell did not return a project icon')
    user=ctypes.WinDLL('user32');user.DestroyIcon.argtypes=[ctypes.c_void_p];user.DestroyIcon(info.icon)
    return info.type

def main():
    if sys.platform!='win32' or os.environ.get('GITHUB_ACTIONS')!='true':
        raise SystemExit('This registry/install test is for disposable GitHub Windows runners only.')
    area=Path(os.environ['RUNNER_TEMP']).resolve()
    target=(area/'StrokeScribe identité & shell test').resolve()
    if not target.is_relative_to(area) or target==area:raise SystemExit('Unsafe installer test target')
    setup=Path(sys.argv[1]).resolve()
    saved_default=read(EXT)
    if saved_default:raise SystemExit('Runner already has a project association; refusing to alter it.')
    evidence={};child=None;installed=False
    def install():
        nonlocal installed
        subprocess.run([str(setup),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/DIR='+str(target)],check=True)
        installed=True
    def uninstall():
        nonlocal installed
        subprocess.run([str(target/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True)
        wait_for(lambda:not (target/'StrokeScribe.exe').exists())
        installed=False
    try:
        install()
        exe=target/'StrokeScribe.exe';python=target/'runtime'/'python.exe'
        assert exe.is_file() and python.is_file()
        env=dict(os.environ,STROKESCRIBE_IDENTITY_EXE=str(exe))
        metadata=powershell("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; (Get-Item -LiteralPath $env:STROKESCRIBE_IDENTITY_EXE).VersionInfo | Select-Object FileDescription,ProductName,FileVersion,ProductVersion,OriginalFilename | ConvertTo-Json -Compress",env)
        from version import APP_VERSION
        assert metadata['FileDescription']=='StrokeScribe' and metadata['ProductName']=='StrokeScribe',metadata
        assert metadata['OriginalFilename']=='StrokeScribe.exe' and metadata['ProductVersion']==APP_VERSION,metadata
        evidence['exe_version_info']=metadata
        assert read(EXT)==PROGID
        command=read(CLASSES+PROGID+r'\shell\open\command')
        assert command=='"'+str(exe)+'" "%1"',command
        assert read(CLASSES+PROGID)=='StrokeScribe Project'
        assert 'assets\\strokescribe.ico' in read(CLASSES+PROGID+r'\DefaultIcon')
        assert read(EXT+r'\OpenWithProgids',PROGID)==''
        # Old projects use the exact current project encoder, not a test-only format.
        projectdir=area/'Documents & Downloads';projectdir.mkdir(exist_ok=True)
        project1=projectdir/'Création 日本 #1.strokescribe'
        project2=projectdir/'Second project & colors.strokescribe'
        seed=projectdir/'make_projects.py'
        seed.write_text("""import os,sys
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,sys.argv[1])
from PySide6.QtWidgets import QApplication
from app import Window
import projects
app=QApplication([]);window=Window()
for value in sys.argv[2:]:projects.save(Path(value),window.project_state())
window.close()
""",encoding='utf-8')
        config=area/'identity-config';config.mkdir(exist_ok=True)
        run_env=dict(os.environ,QT_QPA_PLATFORM='offscreen',STROKESCRIBE_CONFIG_DIR=str(config),
                     STROKESCRIBE_STARTUP_TEST='1',STROKESCRIBE_STARTUP_TEST_MS='10000')
        subprocess.run([str(python),str(seed),str(target),str(project1),str(project2)],env=run_env,check=True)
        sizes={tuple(value) for value in json.loads(subprocess.check_output(
            [str(python),'-c','import json,sys; from PIL import Image; print(json.dumps(sorted(Image.open(sys.argv[1]).ico.sizes())))',
             str(target/'assets'/'strokescribe.ico')],text=True))}
        assert {(16,16),(32,32),(48,48),(256,256)}<=sizes,sizes
        evidence['official_ico_sizes']=sorted(sizes)
        icon_types=[shell_icon(path) for path in (project1,project2)]
        assert icon_types==['StrokeScribe Project']*2,icon_types
        evidence['shell_file_type']=icon_types
        # Instrument only the existing startup-test screenshot branch in this
        # disposable install to create a dirty document and a real modal dialog.
        pristine=(target/'startup.py').read_text(encoding='utf-8')
        hook=(ROOT/'tools'/'native_shell_modal_probe.py').read_text(encoding='utf-8')
        (target/'native_shell_modal_probe.py').write_text(hook,encoding='utf-8')
        instrumented=pristine.replace(
            "                window.grab().save(str(root/'test-output'/'native-startup.png'))",
            "                window.grab().save(str(root/'test-output'/'native-startup.png'))\n                import native_shell_modal_probe; native_shell_modal_probe.install(window,app,root)")
        assert instrumented!=pristine
        (target/'startup.py').write_text(instrumented,encoding='utf-8')
        child=subprocess.Popen([str(exe),str(project1)],cwd=str(area),env=run_env)
        wait_for(lambda:'Opened file: '+str(project1) in log_text(target) and 'Ready:' in log_text(target))
        env_pid=dict(os.environ,STROKESCRIBE_TEST_PROCESS=str(child.pid))
        proc=powershell("Get-Process -Id $env:STROKESCRIBE_TEST_PROCESS | Select-Object ProcessName,Path | ConvertTo-Json -Compress",env_pid)
        assert proc['ProcessName']=='StrokeScribe' and Path(proc['Path'])==exe,proc
        evidence['real_process']=proc
        # Same Windows shell API used by Explorer; spaces, &, # and Unicode
        # are passed as a single filename without a command shell.
        wait_for(lambda:(target/'test-output'/'modal-ready').exists())
        os.startfile(str(project2))
        wait_for(lambda:(target/'test-output'/'modal-queued').exists(),timeout=8)
        wait_for(lambda:(target/'test-output'/'native-unsaved.json').exists(),timeout=8)
        evidence['shell_unsaved_and_modal']=json.loads((target/'test-output'/'native-unsaved.json').read_text())
        # A later request after cancelling still uses the existing primary.
        os.startfile(str(project2))
        wait_for(lambda:'Opened file: '+str(project2) in log_text(target),timeout=8)
        assert child.poll() is None,'Primary exited instead of opening in its existing window'
        assert log_text(target).count('Starting StrokeScribe...')==1
        evidence['shell_open_existing_instance']=True
        child.wait(timeout=20);assert child.returncode==0;child=None
        (target/'startup.py').write_text(pristine,encoding='utf-8')
        (target/'native_shell_modal_probe.py').unlink(missing_ok=True)
        # Cold Explorer open is independent of the earlier subprocess argv test.
        (target/'startup.log').unlink(missing_ok=True)
        old=os.environ.copy()
        os.environ.update(run_env)
        try:os.startfile(str(project1))
        finally:os.environ.clear();os.environ.update(old)
        wait_for(lambda:'Opened file: '+str(project1) in log_text(target) and 'Ready:' in log_text(target))
        time.sleep(12)
        evidence['shell_open_cold']=True
        # Exercise multiprocessing/AI subprocesses and real native restart in
        # the installed host. Only this disposable installation is instrumented;
        # the shipped startup.py and application engine remain unchanged.
        original_startup=(target/'startup.py').read_bytes()
        try:
            (target/'startup.py').write_bytes((ROOT/'tools'/'native_identity_probe.py').read_bytes())
            child=subprocess.Popen([str(exe),'workers'],cwd=str(target),env=run_env)
            assert child.wait(timeout=60)==0,(target/'test-output'/'native-probe-error.txt').read_text(encoding='utf-8') if (target/'test-output'/'native-probe-error.txt').exists() else 'Worker probe failed'
            child=None
            evidence['native_workers']=json.loads((target/'test-output'/'native-workers.json').read_text())
            child=subprocess.Popen([str(exe),'restart'],cwd=str(target),env=run_env)
            old_pid=child.pid
            assert child.wait(timeout=15)==0
            child=None
            wait_for(lambda:(target/'test-output'/'native-restarted.json').exists(),timeout=15)
            restarted=json.loads((target/'test-output'/'native-restarted.json').read_text())
            assert restarted['pid']!=old_pid and restarted['broker_claimed']
            evidence['native_restart']=restarted
            time.sleep(1)
        finally:
            (target/'startup.py').write_bytes(original_startup)
        # External project/config/model locations survive repair and uninstall.
        sentinel=config/'preserve-me.json';sentinel.write_text('{"keep":true}')
        model=area/'Existing AI models';model.mkdir(exist_ok=True)
        weight=model/'existing-model.safetensors';weight.write_bytes(b'keep-model-sentinel')
        original_project=project1.read_bytes()
        # Repair/upgrade does not change an unrelated default chosen afterwards.
        write(EXT,'StrokeScribe.Integration.Other')
        install();assert read(EXT)=='StrokeScribe.Integration.Other'
        evidence['upgrade_preserves_other_default']=True
        uninstall()
        assert read(EXT)=='StrokeScribe.Integration.Other'
        assert read(CLASSES+PROGID) is None
        assert read(EXT+r'\OpenWithProgids',PROGID) is None
        evidence['uninstall_preserves_other_default']=True
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,EXT,0,winreg.KEY_SET_VALUE) as handle:winreg.DeleteValue(handle,'')
        # A fresh own default is removed on uninstall, not left pointing to a missing app.
        install();assert read(EXT)==PROGID
        uninstall();assert read(EXT) is None
        evidence['own_registration_cleanup']=True
        assert project1.read_bytes()==original_project
        assert sentinel.read_text()=='{"keep":true}' and weight.read_bytes()==b'keep-model-sentinel'
        evidence['external_projects_settings_models_preserved']=True
        evidence['manual_visual_checks']='Task Manager friendly label and Explorer icon-cache appearance after desktop restart require manual visual acceptance.'
        out=ROOT/'test-output'/'windows-identity.json';out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(evidence,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(evidence,indent=2,ensure_ascii=True))
    finally:
        if child is not None and child.poll() is None:
            child.wait(timeout=25)
        if installed:uninstall()
        if read(EXT)=='StrokeScribe.Integration.Other':
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,EXT,0,winreg.KEY_SET_VALUE) as handle:winreg.DeleteValue(handle,'')

if __name__=='__main__':main()
