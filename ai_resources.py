"""Read-only advisory resource checks. Values are GiB, shown as GB like Windows."""
from __future__ import annotations
import math,os,subprocess
from pathlib import Path
DEFAULTS=dict(enabled=True,ram_gb=8.,vram_gb=2.,stall_seconds=30.)

def limits(settings=None):
    settings=settings if isinstance(settings,dict) else {}
    out=dict(DEFAULTS)
    out['enabled']=settings.get('enabled',True) is not False
    for key,ceiling in (('ram_gb',1024.),('vram_gb',256.),('stall_seconds',3600.)):
        try:
            value=float(settings.get(key,out[key]))
            if math.isfinite(value):out[key]=max(0.,min(ceiling,value))
        except (TypeError,ValueError):pass
    out['stall_seconds']=max(5.,out['stall_seconds'])
    return out

def ram_available_gb():
    try:
        if os.name=='nt':
            import ctypes
            class Status(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
                    ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
            status=Status();status.length=ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):return None
            return status.available/1024**3
        values=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line)
        return float(values['MemAvailable'].split()[0])/1024**2
    except (OSError,KeyError,ValueError,AttributeError):return None

def gpu_available_gb():
    # Match ComfyUI's default first visible CUDA device, rather than warning
    # about an unrelated GPU. No monitoring utility is required.
    visible=os.environ.get('CUDA_VISIBLE_DEVICES','0').split(',')[0].strip()
    if not visible or visible=='-1':return None
    try:
        result=subprocess.run(['nvidia-smi','--id='+visible,'--query-gpu=memory.free,memory.total',
                    '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=1.5,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:return None
        free,total=(float(x.strip()) for x in result.stdout.strip().splitlines()[0].split(','))
        if not all(math.isfinite(v) for v in (free,total)) or not 0<=free<=total or total<=0:return None
        return free/1024
    except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):return None

def probe():
    return dict(ram_gb=ram_available_gb(),gpu_gb=gpu_available_gb())

def describe(metrics):
    def value(key):
        v=metrics.get(key)
        return f'{v:.1f} GB available' if isinstance(v,(int,float)) and math.isfinite(v) and v>=0 else 'measurement unavailable'
    return 'System RAM: '+value('ram_gb')+' • Dedicated GPU memory: '+value('gpu_gb')

def warning_for(metrics,settings=None):
    cfg=limits(settings)
    if not cfg['enabled']:return ''
    low=[]
    for key,threshold,label in (('ram_gb',cfg['ram_gb'],'system RAM'),('gpu_gb',cfg['vram_gb'],'dedicated GPU memory')):
        value=metrics.get(key)
        if isinstance(value,(int,float)) and math.isfinite(value) and 0<=value<threshold:
            low.append(f'{label}: {value:.1f} GB available (warning below {threshold:g} GB)')
    if not low:return ''
    return ('Low available memory — '+ '; '.join(low)+'. Consider saving work, then close memory-heavy applications. '
            'You can generate anyway. These are advisory limits, not a prediction of model requirements.')
