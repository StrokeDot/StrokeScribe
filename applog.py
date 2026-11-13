"""The StrokeScribe log: what happened and every error, with details.

    %APPDATA%\\StrokeScribe\\logs\\strokescribe.log   (plus .1 .2 .3 older ones)

Help → Open log folder shows it. Errors anywhere in the app (also the ones
that used to vanish silently) are written here with the full traceback, and
the window says that something went wrong instead of quietly breaking.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path

log = logging.getLogger('strokescribe')
_on_error = []                 # callbacks(text) — the window shows a short message
_recent = {}


def folder():
    from preflight import config_path
    path = config_path().parent / 'logs'
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file():
    return folder() / 'strokescribe.log'


def setup():
    """Start writing the log (once). Never fails: logging must not stop the app."""
    if getattr(log, '_ready', False):
        return log
    log.setLevel(logging.INFO)
    try:
        handler = logging.handlers.RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=3,
                                                       encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s  %(levelname)-7s %(message)s', '%Y-%m-%d %H:%M:%S'))
        log.addHandler(handler)
    except Exception:
        log.addHandler(logging.NullHandler())
    log._ready = True
    try:
        from version import APP_VERSION
        log.info('StrokeScribe %s started (Python %s, %s)', APP_VERSION, sys.version.split()[0], sys.platform)
    except Exception:
        pass
    previous = sys.excepthook

    def hook(kind, value, tb):
        error('Unexpected error', (kind, value, tb))
        if previous not in (None, sys.__excepthook__):
            try:
                previous(kind, value, tb)
            except Exception:
                pass
    sys.excepthook = hook
    threading.excepthook = lambda args: error(f'Unexpected error in a background task ({args.thread.name})',
                                              (args.exc_type, args.exc_value, args.exc_traceback))
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        def qt_message(kind, context, message):
            if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                log.warning('Qt: %s', message)
        qInstallMessageHandler(qt_message)
    except Exception:
        pass
    return log


def info(message, *args):
    log.info(message, *args)


def error(message, exc_info=None):
    """Write an error with its traceback (exc_info: True, an exception or a (type, value, tb) tuple)."""
    if exc_info is True or exc_info is None:
        exc_info = sys.exc_info()
    elif isinstance(exc_info, BaseException):
        exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
    details = ''.join(traceback.format_exception(*exc_info)) if exc_info and exc_info[0] else ''
    import time
    key = (message, str(exc_info[1]) if exc_info else '')
    now = time.time()
    if now - _recent.get(key, 0) < 15:            # the same error again (e.g. every frame): once
        return
    _recent[key] = now
    log.error('%s\n%s', message, details.rstrip())
    short = f'{message}: {exc_info[1]}' if exc_info and exc_info[1] is not None else message
    for callback in list(_on_error):
        try:
            callback(short)
        except Exception:
            pass


def tail(lines=200):
    """The last lines of the log (for a bug report)."""
    try:
        return ''.join(log_file().read_text(encoding='utf-8', errors='replace').splitlines(True)[-lines:])
    except OSError:
        return ''
