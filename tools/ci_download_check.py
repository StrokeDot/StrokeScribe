"""Real download from Hugging Face with the app's downloader: 1 connection vs 8,
plus Cancel and resume. Writes download-check.txt."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_engine
import ai_models

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
f = ai_models.FLUX2_VAE                                   # 336 MB
lines = []

# Where does the time go? One piece: first byte and speed, on the address after redirects.
final = ai_engine._resolve(f.url)
lines.append('final host: ' + final.split('/')[2])
for label, url in (('final', final), ('original', f.url)):
    began = time.time()
    with ai_engine._open(url, 32 << 20, (64 << 20) - 1) as r:
        first = r.read(1); t1 = time.time() - began
        n = 1
        while True:
            b = r.read(ai_engine.BLOCK)
            if not b: break
            n += len(b)
    took = time.time() - began
    lines.append(f'one 32 MB piece ({label} address): first byte {t1:.2f} s, {n / took / 1e6:.0f} MB/s')

# Several pieces at once, without writing to disk.
def fetch(a, b, res):
    began = time.time()
    with ai_engine._open(final, a, b) as r:
        n = 0
        while True:
            x = r.read(ai_engine.BLOCK)
            if not x: break
            n += len(x)
    res.append((n, time.time() - began))
for k in (2, 4, 8):
    res = []; began = time.time()
    ts = [threading.Thread(target=fetch, args=(i * (32 << 20), (i + 1) * (32 << 20) - 1, res)) for i in range(k)]
    [t.start() for t in ts]; [t.join() for t in ts]
    took = time.time() - began
    lines.append(f'{k} pieces at once: {sum(n for n, _ in res) / took / 1e6:.0f} MB/s total, '
                 f'slowest piece {max(t for _, t in res):.1f} s')

for connections in (1, 4, 8):
    target = out / f'c{connections}' / f.name
    began = time.time()
    ai_engine.download(f.url, target, f.size, connections=connections)
    took = max(.1, time.time() - began)
    assert target.stat().st_size == f.size
    lines.append(f'app download, {connections} connection(s): {f.size / 1e6:.0f} MB in {took:.1f} s = {f.size / took / 1e6:.0f} MB/s')
    for name, piece, problem in ai_engine.RETRIES:
        lines.append(f'    retried piece {piece}: {problem}')
    ai_engine.RETRIES.clear()
    target.unlink()
# Cancel after 1.5 s, then resume.
target = out / 'resume' / f.name
began = time.time()
try:
    ai_engine.download(f.url, target, f.size, cancelled=lambda: time.time() - began > 1.5)
    lines.append('cancel: finished before the cancel')
except ai_engine.Cancelled:
    lines.append(f'cancel: stopped {time.time() - began - 1.5:.2f} s after Cancel')
ai_engine.download(f.url, target, f.size)
assert target.stat().st_size == f.size
import hashlib
lines.append('resume: complete, sha256 ' + hashlib.sha256(target.read_bytes()).hexdigest()[:16])
(out / 'download-check.txt').write_text('\n'.join(lines) + '\n')
print('\n'.join(lines))
