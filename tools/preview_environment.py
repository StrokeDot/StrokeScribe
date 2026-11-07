"""Headless preview-only behavior: never applies to the installed desktop app."""
from __future__ import annotations


def configure_preview_environment(environ):
    """Allow test preview windows to close without an unattended modal prompt.

    App.confirm_leave_project additionally checks Qt's *actual* offscreen
    platform. This helper never changes the settings of a real GUI session.
    """
    if environ.get('QT_QPA_PLATFORM') != 'offscreen':
        return False
    environ.setdefault('STROKESCRIBE_TEST_AUTODISCARD', '1')
    return True
