# Windows identity integration

Base: experimental.73 (ed3a16c), existing CI green. Remote GitHub/Actions only.

1. Verify RED shell project/SVG and local IPC tests.
2. Build a branded GUI executable embedding existing CPython in process; preserve private Python for AI/export workers. Embed official ICO, PE identity and version metadata.
3. Route .strokescribe through the current loader and Save/Discard/Cancel guards. Local-user single-instance delivery protects unsaved work. Safe native restart waits for the old process to exit.
4. Register current-user ProgID/icon/quoted open command, Open With and capabilities. Preserve UserChoice and unrelated defaults; clean only owned entries, notify Explorer.
5. Test actual installed executable metadata, multi-resolution icon, native process identity, Unicode/spaced shell opening, associations/upgrade/uninstall on hosted Windows; run full Linux/Windows suites. Record remaining Task Manager/Explorer visual checks.
6. Deliver experimental.74 candidate and PR; no main merge or publication. Full installer is required for native host/registry integration. App UI, project format and worker architecture stay intact.
