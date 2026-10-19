"""Process ownership for the local AI server, with no process-name based killing.

Windows uses a Job Object. A tiny stdin-gated launcher is assigned to the job
before it can spawn the target; descendants therefore inherit containment even
if the target/root exits early. POSIX uses a new session/process group.
"""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import time


class _WindowsJob:
    def __init__(self):
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel = self.kernel
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(kernel, name)
            fn.argtypes, fn.restype = args, result

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in
                        ("TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [
                        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

        self.Accounting = Accounting
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, pid):
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE are required by AssignProcessToJobObject.
        process = self.kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(process)

    def terminate(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def active(self):
        info = self.Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.ActiveProcesses

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


# No target code can run until the parent has successfully assigned the launcher
# to its Job Object. EOF (including a parent crash before assignment) exits safely.
_WINDOWS_LAUNCHER = (
    "import subprocess,sys; "
    "token=sys.stdin.buffer.read(1); "
    "child=subprocess.Popen(sys.argv[1:],stdin=subprocess.DEVNULL) if token==b'1' else None; "
    "sys.exit(child.wait() if child is not None else 125)"
)


class OwnedProcess:
    """Own one server launch and its descendants; caller owns any output pipes.

    The command must start with the Python interpreter used by the target.
    Do not pass shell=True or stdin: the Windows launcher owns its input gate.
    """
    def __init__(self, command, **kwargs):
        self._stopped = False
        self._job = None
        self._pgid = None
        self.proc = None
        if kwargs.get("shell") or "stdin" in kwargs:
            raise ValueError("Owned launches require an argument list and their own stdin gate.")
        command = [str(item) for item in command]
        if os.name != "nt":
            kwargs["start_new_session"] = True
            self.proc = subprocess.Popen(command, **kwargs)
            self._pgid = self.proc.pid
            return
        self._job = _WindowsJob()
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        try:
            self.proc = subprocess.Popen(
                [command[0], "-u", "-c", _WINDOWS_LAUNCHER, *command],
                stdin=subprocess.PIPE, **kwargs)
            self._job.assign(self.proc.pid)
            self.proc.stdin.write("1" if kwargs.get("text") or kwargs.get("universal_newlines") else b"1")
            self.proc.stdin.flush()
            self.proc.stdin.close()
        except BaseException:
            if self.proc is not None:
                if self.proc.stdin and not self.proc.stdin.closed:
                    self.proc.stdin.close()  # EOF prevents any uncontained target launch.
                if self.proc.poll() is None:
                    self.proc.terminate()
                self.proc.wait(timeout=5)
            self._job.close()
            self._job = None
            raise

    def _signal_group(self, sig):
        try:
            os.killpg(self._pgid, sig)
            return True
        except ProcessLookupError:
            return False

    def stop(self, timeout=3):
        """Stop only this owned tree, including descendants of an exited root.

        Failed cleanup keeps the ownership fields intact so callers can retry.
        Forced termination is always followed by a wait on the owned root.
        """
        if self._stopped:
            return
        timeout = max(0.05, timeout)
        if self._job is not None:
            self._job.terminate()
            self.proc.wait(timeout=timeout)
            end = time.monotonic() + timeout
            while self._job.active():
                if time.monotonic() >= end:
                    raise TimeoutError("Owned AI processes have not exited yet.")
                time.sleep(.02)
            self._job.close()
            self._job = None
        else:
            exists = self._signal_group(signal.SIGTERM)
            end = time.monotonic() + timeout
            while exists and time.monotonic() < end:
                self.proc.poll()  # Reap an exited root while descendants finish.
                exists = self._signal_group(0)
                if exists:
                    time.sleep(.02)
            if exists:
                self._signal_group(signal.SIGKILL)
            self.proc.wait(timeout=timeout)
        self._stopped = True
