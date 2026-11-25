"""Release authorization: explicit user approval + independently tested exact SHA.

This policy is used by the release job *after* the cross-platform test jobs
have succeeded. It is deliberately independent of Qt and external packages.
"""
from __future__ import annotations

import argparse
import re

ALLOWED_RELEASE_REFS = frozenset({
    'refs/heads/main',
    'refs/heads/fix/svg-guide-coverage-experimental12',
})


class ReleasePolicyError(ValueError):
    pass


def authorize_publish(event, ref, requested, commit_sha, linux_sha, windows_sha):
    if event != 'workflow_dispatch':
        raise ReleasePolicyError('Publishing must be a manually approved workflow dispatch.')
    if type(requested) is not bool or not requested:
        raise ReleasePolicyError('Publishing requires an explicit approved boolean input.')
    if ref not in ALLOWED_RELEASE_REFS:
        raise ReleasePolicyError('Publishing is disabled for this development branch.')
    if not isinstance(commit_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', commit_sha):
        raise ReleasePolicyError('Invalid release commit SHA.')
    if linux_sha != commit_sha or windows_sha != commit_sha:
        raise ReleasePolicyError('Both Linux and Windows tests must pass for this exact commit.')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description='Authorize publishing a tested StrokeScribe installer.')
    parser.add_argument('--event', required=True)
    parser.add_argument('--ref', required=True)
    parser.add_argument('--publish', required=True, choices=('true', 'false'))
    parser.add_argument('--sha', required=True)
    parser.add_argument('--linux-sha', required=True)
    parser.add_argument('--windows-sha', required=True)
    args = parser.parse_args(argv)
    authorize_publish(args.event, args.ref, args.publish == 'true',
                      args.sha, args.linux_sha, args.windows_sha)
    print('Release authorized: explicit approval and exact Linux/Windows commit match.')


if __name__ == '__main__':
    main()
