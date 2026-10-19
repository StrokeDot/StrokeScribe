"""Real CPU-only process ownership checks; no ComfyUI, weights, or GPU."""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

try:
    from owned_process import OwnedProcess
except ImportError:
    OwnedProcess = None

# Each worker commits/touches 12 MiB so evidence is about real resident memory.
FIXTURE = r'''
import base64, http.server, json, os, signal, subprocess, sys, time
from pathlib import Path
here = Path(__file__).parent
role = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "server"
ram = bytearray(12 * 1024 * 1024)
for offset in range(0, len(ram), 4096): ram[offset] = 127
(here / (role + ".pid")).write_text(str(os.getpid()))
if role in ("server", "idle", "early"):
    subprocess.Popen([sys.executable, __file__, "child"], stdin=subprocess.DEVNULL)
elif role == "child":
    subprocess.Popen([sys.executable, __file__, "grandchild"], stdin=subprocess.DEVNULL)
if role in ("child", "grandchild"):
    if os.name != "nt": signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (here / (role + ".ready")).write_text("ready")
    while True: time.sleep(.1)
if role == "early":
    until = time.monotonic() + 10
    while not (here / "grandchild.ready").exists() and time.monotonic() < until: time.sleep(.02)
    sys.exit(0)
if role == "idle":
    while True: time.sleep(.1)
port = int(sys.argv[sys.argv.index("--port") + 1])
out = here / "output"
out.mkdir(exist_ok=True)
# A tiny valid image avoids any inference or external services.
from PIL import Image
Image.new("RGB", (20, 16), "white").save(out / "result.png")
generations = 0
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == "/system_stats": body = {"pid": os.getpid(), "generations": generations}
        elif self.path.startswith("/history/"):
            key = self.path.split("/")[-1]
            body = {key: {"status": {"completed": True},
                          "outputs": {"1": {"images": [{"filename": "result.png"}]}}}}
        else: body = {}
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        global generations
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/prompt":
            generations += 1
            body = {"prompt_id": str(generations)}
        else: body = {}
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''

def until(predicate, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.02)
    return bool(predicate())


class ProcessProbe:
    """Stable Windows handle; Linux /proc state treats reaped-memory zombies as dead."""
    def __init__(self, pid):
        self.pid = pid
        self.handle = None
        if os.name == "nt":
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel = kernel
            self.handle = kernel.OpenProcess(0x00100000 | 0x0400 | 0x0010, False, pid)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())

    def alive(self):
        if os.name == "nt":
            return self.kernel.WaitForSingleObject(self.handle, 0) == 0x102
        try:
            state = Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
            return state != "Z"
        except FileNotFoundError:
            return False

    def resident_bytes(self):
        if os.name != "nt":
            return int(Path(f"/proc/{self.pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        info = Counters()
        info.cb = ctypes.sizeof(info)
        fn = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        fn.restype = wintypes.BOOL
        if not fn(self.handle, ctypes.byref(info), info.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.WorkingSetSize

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class ProcessFixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "main.py").write_text(FIXTURE)
        self.paths = SimpleNamespace(python=Path(sys.executable), comfy=self.root,
                                     data=self.root, output=self.root / "output",
                                     engine_installed=lambda: True)
        self.probes = []

    def workers(self, role="server"):
        expected = [role, "child", "grandchild"]
        if not until(lambda: all((self.root / (x + ".pid")).exists() for x in expected)
                     and (self.root / "grandchild.ready").exists()):
            raise AssertionError("CPU process fixture did not start")
        self.probes = [ProcessProbe(int((self.root / (x + ".pid")).read_text())) for x in expected]
        return self.probes

    def close(self):
        for probe in self.probes:
            # Test emergency cleanup is deliberately scoped to exact fixture PIDs.
            if probe.alive():
                try: os.kill(probe.pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
                except ProcessLookupError: pass
            probe.close()
        self.tmp.cleanup()


class OwnedProcessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ProcessFixture()
        self.addCleanup(self.fixture.close)
        self.assertIsNotNone(OwnedProcess, "Owned process-tree containment must be implemented")

    def test_owned_tree_releases_real_memory_without_stopping_unrelated_process(self):
        sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def stop_sentinel():
            if sentinel.poll() is None:
                sentinel.kill()
            sentinel.wait(timeout=5)
        self.addCleanup(stop_sentinel)
        owner = OwnedProcess([sys.executable, str(self.fixture.root / "main.py"), "idle"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(owner.stop)
        workers = self.fixture.workers("idle")
        resident = [probe.resident_bytes() for probe in workers]
        self.assertTrue(all(value >= 12 * 1024 * 1024 for value in resident), resident)
        before = time.monotonic()
        owner.stop(timeout=1)
        self.assertTrue(until(lambda: all(not p.alive() for p in workers), 5),
                        "Owned descendants must not retain RAM after stop")
        self.assertIsNotNone(owner.proc.poll(), "The owned root must be waited/reaped")
        self.assertIsNone(sentinel.poll(), "Unrelated Python must remain alive")
        owner.stop(timeout=1)
        print(json.dumps({"evidence": "CPU fixture process RAM released", "platform": sys.platform,
                          "pids": [p.pid for p in workers], "resident_bytes_before": resident,
                          "all_owned_exited": True, "unrelated_alive": True,
                          "elapsed_seconds": round(time.monotonic() - before, 3)}), flush=True)

    def test_descendants_are_released_even_when_root_exits_first(self):
        owner = OwnedProcess([sys.executable, str(self.fixture.root / "main.py"), "early"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(owner.stop)
        workers = self.fixture.workers("early")
        owner.proc.wait(timeout=10)
        self.assertTrue(all(p.alive() for p in workers[1:]), "Fixture children must outlive root")
        owner.stop(timeout=1)
        self.assertTrue(until(lambda: all(not p.alive() for p in workers), 5))

    def test_repeated_stop_and_restart_keeps_ownership_separate(self):
        first = OwnedProcess([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(first.stop)
        first.stop(timeout=1)
        first.stop(timeout=1)
        second = OwnedProcess([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(second.stop)
        self.assertIsNone(second.proc.poll())
        first.stop(timeout=1)
        self.assertIsNone(second.proc.poll(), "Old ownership must not stop a replacement")
        second.stop(timeout=1)
        self.assertIsNotNone(second.proc.poll())


if __name__ == "__main__":
    unittest.main(verbosity=2)
