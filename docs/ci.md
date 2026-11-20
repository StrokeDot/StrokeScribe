# Continuous integration

Pull requests get fast feedback; the full suite runs before anything is merged
or released.

| When | Workflow | What runs | Time |
| --- | --- | --- | --- |
| Every push to a pull request | **Quick checks** | Core Studio, layout and render tests plus the tests that import the changed files (`tools/select_tests.py`), Windows and Linux in parallel; failures are posted on the PR | ~3–6 min |
| Push touching a topic's files | Adaptive painting, AI engine, AI resources, Artwork workflow, Source editing, Image generator drawer, Updater transaction | That topic's focused tests | varies |
| PR labelled `full-tests`, or run by hand | **Full test suite** (image source review) | All test modules on Linux and Windows, previews and the prototype ZIP | ~15–20 min |
| Release (run by hand) | **Windows installer** | Full suite on Linux and Windows for the exact commit, then the installer; publishes only when approved (`tools/release_policy.py`) | ~35 min |

- A newer push cancels the older run of the same workflow.
- Before merging into `fix/svg-guide-coverage-experimental12` (the branch the
  in-app updater follows), add the `full-tests` label and wait for it to pass.
- To get a test installer for a branch, run **Windows installer** by hand on that
  branch with *publish* off and download the artifact.
- `app.py` is imported by almost every window test, so a change to it alone
  runs the core set rather than everything; the full suite covers the rest.
