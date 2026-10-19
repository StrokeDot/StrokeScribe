"""Optional real ComfyUI CPU lifecycle evidence, without AI weights/inference.

Usage: python tools/verify_comfy_lifecycle.py COMFY_DIRECTORY DATA_DIRECTORY
Requires the real ComfyUI requirements and psutil in this Python environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_engine


def main():
    import psutil
    comfy, data = (Path(arg).resolve() for arg in sys.argv[1:3])
    if not (comfy / "main.py").is_file():
        raise SystemExit("Supply an installed real ComfyUI directory.")
    data.mkdir(parents=True, exist_ok=True)
    # App launch behavior stays unchanged: this verification-only entry point
    # adds --cpu while executing the real, unmodified ComfyUI main.py.
    with tempfile.TemporaryDirectory() as launch:
        launcher = Path(launch)
        (launcher / "main.py").write_text(
            "import os,runpy,sys\n"
            + "root=" + repr(str(comfy)) + "\n"
            + "sys.path.insert(0,root)\n"
            + "os.chdir(root)\n"
            + "sys.argv=[os.path.join(root,'main.py'),*sys.argv[1:],'--cpu']\n"
            + "runpy.run_path(sys.argv[0],run_name='__main__')\n")
        paths = SimpleNamespace(python=Path(sys.executable), comfy=launcher, data=data,
                                output=data / "output", engine_installed=lambda: True)
        engine = ai_engine.Engine(paths, log=print)
        processes = []
        evidence = {"kind": "Real ComfyUI procedural CPU lifecycle; no AI model inference",
                    "comfy_directory": str(comfy), "platform": sys.platform}
        try:
            engine.start(timeout=240)
            root = psutil.Process(engine.proc.pid)
            identity = (root.pid, root.create_time())
            processes = [root, *root.children(recursive=True)]
            evidence["owned_processes"] = [{"pid": p.pid, "created": p.create_time(),
                                           "rss_ready": p.memory_info().rss} for p in processes]
            workflow = {
                "1": {"class_type": "EmptyImage", "inputs": {
                    "width": 64, "height": 48, "batch_size": 1, "color": 16777215}},
                "2": {"class_type": "SaveImage", "inputs": {
                    "images": ["1", 0], "filename_prefix": "StrokeScribe-lifecycle-probe"}},
            }
            outputs = []
            for _ in range(2):
                engine.start(timeout=30)
                outputs.append(str(engine.run(workflow, timeout=120)))
                if (engine.proc.pid, psutil.Process(engine.proc.pid).create_time()) != identity:
                    raise AssertionError("Repeated generation restarted the server.")
            if not all(Path(path).is_file() for path in outputs):
                raise AssertionError("Real ComfyUI did not save both procedural images.")
            evidence["outputs"] = outputs
            evidence["same_owned_root_for_two_jobs"] = True
            evidence["rss_after_two_jobs"] = [{"pid": p.pid, "rss": p.memory_info().rss}
                                             for p in processes if p.is_running()]
            began = time.monotonic()
            engine.stop()
            _, alive = psutil.wait_procs(processes, timeout=10)
            alive = [p for p in alive if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
            evidence["all_recorded_owned_processes_exited"] = not alive
            evidence["stop_seconds"] = round(time.monotonic() - began, 3)
            if alive:
                raise AssertionError("Owned ComfyUI processes remain: " + str([p.pid for p in alive]))
            target = Path("samples/source-editing/comfy-lifecycle.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(evidence, indent=2))
            print(json.dumps(evidence, indent=2), flush=True)
        finally:
            engine.stop()


if __name__ == "__main__":
    main()
