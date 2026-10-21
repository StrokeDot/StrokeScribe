"""Build the real in-process Windows host using Visual Studio and private CPython."""
import os,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def build(stage):
    from version import APP_VERSION
    stage=Path(stage).resolve();runtime=stage/'runtime'
    out=ROOT/'build'/'native';out.mkdir(parents=True,exist_ok=True)
    numbers=tuple((list(map(int,re.findall(r'\d+',APP_VERSION)))+[0]*4)[:4])
    numeric=','.join(map(str,numbers))
    icon=(ROOT/'assets'/'strokescribe.ico').as_posix()
    rc=out/'StrokeScribe.rc'
    rc.write_text(f'''#include <windows.h>
1 ICON "{icon}"
1 VERSIONINFO
FILEVERSION {numeric}
PRODUCTVERSION {numeric}
FILEOS 0x40004L
FILETYPE 0x1L
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904B0"
    BEGIN
      VALUE "CompanyName", "StrokeDot\\0"
      VALUE "FileDescription", "StrokeScribe\\0"
      VALUE "FileVersion", "{APP_VERSION}\\0"
      VALUE "InternalName", "StrokeScribe\\0"
      VALUE "OriginalFilename", "StrokeScribe.exe\\0"
      VALUE "ProductName", "StrokeScribe\\0"
      VALUE "ProductVersion", "{APP_VERSION}\\0"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x0409, 1200
  END
END
''',encoding='utf-8')
    vswhere=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft Visual Studio'/'Installer'/'vswhere.exe'
    install=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    if not install:raise RuntimeError('Visual Studio C++ tools are required to build the native host.')
    vcvars=Path(install)/'VC'/'Auxiliary'/'Build'/'vcvars64.bat'
    resource=out/'StrokeScribe.res';target=stage/'StrokeScribe.exe'
    source=ROOT/'windows'/'StrokeScribe.cpp';manifest=ROOT/'windows'/'StrokeScribe.manifest'
    compile_args=['cl','/nologo','/O2','/MT','/EHsc','/std:c++17','/DUNICODE','/D_UNICODE',
                  '/I'+str(runtime/'include'),str(source),str(resource),
                  '/Fo'+str(out/'StrokeScribe.obj'),'/Fe'+str(target),'/link',
                  '/LIBPATH:'+str(runtime/'libs'),'python312.lib','shell32.lib','delayimp.lib',
                  '/DELAYLOAD:python312.dll','/SUBSYSTEM:WINDOWS','/MANIFEST:EMBED',
                  '/MANIFESTINPUT:'+str(manifest)]
    command='call '+subprocess.list2cmdline([str(vcvars)])+' >nul && '+subprocess.list2cmdline(['rc','/nologo','/fo',str(resource),str(rc)])+' && '+subprocess.list2cmdline(compile_args)
    subprocess.run(['cmd.exe','/d','/s','/c',command],check=True)
    if not target.is_file():raise RuntimeError('Native executable was not built.')
    return target
