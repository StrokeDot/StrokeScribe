"""Run unittest modules with a watchdog (used by CI).

If one test runs longer than the limit (for example a window waiting for a
click that never comes), print where every thread is, name the test, and stop
with an error instead of hanging until the CI job times out.

    python tools/run_tests.py [--limit SECONDS] [--each] module [module ...]

--each (1.0.0 release suite): every module runs in its own fresh process. In one
process the whole suite slowed down from window to window (two minutes for the
first fifty tests, more than half an hour for fifty later ones) and could not
finish in the release time; separate processes keep every module as fast as alone.
"""
import subprocess
import os
import sys
import threading
import time
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_current = {'name': None, 'since': time.monotonic()}


class _Result(unittest.TextTestResult):
    def startTest(self, test):
        _current['name'] = test.id()
        _current['since'] = time.monotonic()
        super().startTest(test)


def _watch(limit):
    while True:
        time.sleep(5)
        if _current['name'] and time.monotonic() - _current['since'] > limit:
            frames = sys._current_frames()
            main = threading.main_thread().ident
            out = sys.stderr
            print(f'\nERROR: WATCHDOG: {_current["name"]} still running after {limit} s', file=out)
            print('\n--- main thread ---', file=out)
            traceback.print_stack(frames.get(main), file=out)
            for ident, frame in frames.items():
                if ident in (main, threading.get_ident()):
                    continue
                print(f'\n--- thread {ident} ---', file=out)
                traceback.print_stack(frame, file=out)
            out.flush()
            os._exit(3)


# Every module's process starts the app log first, as the single-process suite did: a
# window started without it opens its log inside the test's temporary folder, and
# Windows cannot delete that folder while the log is open.
_CHILD = ("import sys,runpy,applog; applog.setup(); script=sys.argv[1]; sys.argv=sys.argv[1:]; "
          "runpy.run_path(script, run_name='__main__')")


def _each(modules, limit):
    failed = []
    for name in modules:
        started = time.monotonic()
        print(f'\n===== {name} =====', flush=True)
        code = subprocess.call([sys.executable, '-X', 'faulthandler', '-c', _CHILD,
                                str(Path(__file__).resolve()), '--limit', str(limit), name], cwd=str(ROOT))
        print(f'===== {name}: {"ok" if code == 0 else f"FAILED ({code})"} '
              f'in {time.monotonic() - started:.0f} s =====', flush=True)
        if code != 0:
            failed.append(name)
    print(f'\n{len(modules) - len(failed)} of {len(modules)} modules passed', flush=True)
    if failed:
        print('FAILED modules: ' + ' '.join(failed), flush=True)
    return 1 if failed else 0


def main(argv):
    limit = 420.
    each = False
    while argv[:1] in (['--limit'], ['--each']):
        if argv[0] == '--each':
            each = True; argv = argv[1:]
        else:
            limit = float(argv[1]); argv = argv[2:]
    if each:
        return _each(argv, limit)
    threading.Thread(target=_watch, args=(limit,), daemon=True).start()
    if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        # Only the headless regression harness opts into unattended shutdown;
        # production keeps the Save / Discard / Cancel dialog.
        os.environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
    suite = unittest.defaultTestLoader.loadTestsFromNames(argv)
    runner = unittest.TextTestRunner(verbosity=2, resultclass=_Result)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
