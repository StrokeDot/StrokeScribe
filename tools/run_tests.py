"""Run unittest modules with a watchdog (used by CI).

If one test runs longer than the limit (for example a window waiting for a
click that never comes), print where every thread is, name the test, and stop
with an error instead of hanging until the CI job times out.

    python tools/run_tests.py [--limit SECONDS] module [module ...]
"""
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


def main(argv):
    limit = 420.
    if argv[:1] == ['--limit']:
        limit = float(argv[1]); argv = argv[2:]
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
