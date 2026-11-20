"""Bounded asynchronous local logs; producers never wait for disk or UI callbacks."""
from __future__ import annotations
import queue,re,threading,time
from pathlib import Path

class DiagnosticLog:
    def __init__(self,path,max_bytes=4*1024*1024,capacity=512):
        self.path=Path(path);self.max_bytes=max(512,int(max_bytes))
        self.queue=queue.Queue(maxsize=max(4,int(capacity)))
        self._lock=threading.Lock();self._thread=None;self.dropped=0
    def emit(self,text,callback=None):
        text=str(text)[:min(4096,self.max_bytes//8)]
        with self._lock:
            try:self.queue.put_nowait((text,callback))
            except queue.Full:
                self.dropped+=1;return False
            if self._thread is None or not self._thread.is_alive():
                self._thread=threading.Thread(target=self._run,daemon=True,name='StrokeScribe AI diagnostics')
                self._thread.start()
        return True
    def _run(self):
        while True:
            try:item=self.queue.get(timeout=.25)
            except queue.Empty:
                with self._lock:
                    if self.queue.empty():
                        self._thread=None;return
                continue
            try:
                if isinstance(item,threading.Event):item.set();continue
                text,callback=item
                try:
                    dropped=self.dropped
                    if dropped:self._write(f'[diagnostics busy: {dropped} lines omitted]');self.dropped=0
                    self._write(text)
                except OSError:pass
                if callback:
                    try:callback(text)
                    except Exception:pass
            finally:self.queue.task_done()
    def _write(self,text):
        raw=(time.strftime('%Y-%m-%d %H:%M:%S')+'  '+text+'\n').encode('utf-8',errors='replace')
        if len(raw)>self.max_bytes:raw=raw[:self.max_bytes-1]+b'\n'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.exists() and self.path.stat().st_size+len(raw)>self.max_bytes:
            self.path.replace(self.path.with_name(self.path.name+'.1'))
        with self.path.open('ab') as output:output.write(raw)
    def flush(self,timeout=.2):
        done=threading.Event();end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                self.queue.put(done,timeout=max(.001,end-time.monotonic()))
                with self._lock:
                    if self._thread is None or not self._thread.is_alive():
                        self._thread=threading.Thread(target=self._run,daemon=True);self._thread.start()
                return done.wait(max(0.,end-time.monotonic()))
            except queue.Full:pass
        return False

def sanitize(text,roots=()):
    text=str(text)
    candidates=list(roots)+[str(Path.home())]
    for root in sorted({str(p) for p in candidates if p},key=len,reverse=True):
        variants={root,root.replace('\\','/'),root.replace('/','\\')}
        variants|={value.replace('\\','\\\\') for value in list(variants)}
        for value in sorted(variants,key=len,reverse=True):
            text=re.sub(re.escape(value),'[local folder]',text,flags=re.I)
    text=re.sub(r"""(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s"']+""",'[user folder]',text)
    text=re.sub(r'(?i)(https?://)[^/@\s:]+:[^/@\s]+@',r'\1[redacted]@',text)
    credentials=r"""(?i)(["']?(?:authorization|api[_-]?key|access[_-]?token|token|password|secret)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|(?:Bearer\s+)?[^\s,;&]+)"""
    text=re.sub(credentials,r'\1[redacted]',text)
    text=re.sub(r'\bhf_[A-Za-z0-9]{12,}\b','[redacted token]',text)
    return text

def diagnostic_excerpt(path,roots=(),limit=64*1024):
    path=Path(path)
    try:
        with path.open('rb') as source:
            source.seek(max(0,path.stat().st_size-limit));raw=source.read(limit)
        return sanitize(raw.decode('utf-8',errors='replace'),roots)
    except OSError:return 'No engine diagnostics have been recorded yet.'
