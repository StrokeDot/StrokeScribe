"""Choose the quick-check test modules for a pull request.

    python tools/select_tests.py CHANGED_FILE [CHANGED_FILE ...]

Prints test module names (one line, space separated) for tools/run_tests.py:

- a small core set that guards the Studio window, its layout and the render
  pipeline (run on every pull request);
- every changed test file;
- every test file that imports a changed module (``import x`` / ``from x``),
  unless that module is a hub imported by more than HUB_LIMIT test files
  (``app.py``: almost every window test) — the core set covers hubs.

The full suite still runs on request (the ``full-tests`` label or a manual
run) and always before an installer is published.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CORE = (
    'test_studio', 'test_workspace_layout', 'test_ui_control_regression',
    'test_menus', 'test_timeline_autosave', 'test_render_pipeline_smoke',
)
# Optional core modules that exist only on some branches.
CORE_IF_PRESENT = ('test_element_kinds', 'test_dual_sidebar')
HUB_LIMIT = 12


def _imports(text, module):
    pattern = rf'^\s*(?:from\s+{re.escape(module)}\s+import|import\s+[^\n#]*\b{re.escape(module)}\b)'
    return re.search(pattern, text, re.MULTILINE) is not None


def select(changed, root=ROOT):
    tests = sorted(p for p in root.glob('test_*.py'))
    present = {p.stem for p in tests}
    chosen = [name for name in CORE if name in present]
    chosen += [name for name in CORE_IF_PRESENT if name in present]
    texts = {}
    for path in changed:
        path = Path(path)
        if path.parent != Path('.') and str(path.parent) not in ('', '.'):
            continue                      # top-level Python modules only
        if path.suffix != '.py':
            continue
        stem = path.stem
        if stem.startswith('test_'):
            if stem in present:
                chosen.append(stem)
            continue
        importers = []
        for test in tests:
            if test.stem not in texts:
                texts[test.stem] = test.read_text(encoding='utf-8', errors='replace')
            if _imports(texts[test.stem], stem):
                importers.append(test.stem)
        if len(importers) <= HUB_LIMIT:
            chosen += importers
    seen, out = set(), []
    for name in chosen:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


if __name__ == '__main__':
    print(' '.join(select(sys.argv[1:])))
