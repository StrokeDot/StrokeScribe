"""Real download from Hugging Face with the app's downloader: 1 connection vs 8,
plus Cancel and resume. Writes download-check.txt."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_engine
import ai_models

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
f = ai_models.FLUX2_VAE                                   # 336 MB
lines = []
for connections in (1, 8):
    target = out / f'c{connections}' / f.name
    began = time.time()
    ai_engine.download(f.url, target, f.size, connections=connections)
    took = max(.1, time.time() - began)
    assert target.stat().st_size == f.size
    lines.append(f'{connections} connection(s): {f.size / 1e6:.0f} MB in {took:.1f} s = {f.size / took / 1e6:.0f} MB/s')
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
