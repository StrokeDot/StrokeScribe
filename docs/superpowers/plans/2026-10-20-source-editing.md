# Source editing and AI lifecycle — experimental.65

User brief: supplied engineering ticket, phases1–4. Prior authorization delegates implementation judgment; proceed incrementally without repeating authorization questions. Remote GitHub/Actions only. Base experimental.64 ab055714d4e635e47659cfdbb82021518a75558c; PR20 selectively integrated, never overwritten or merged into its branch.

1. Prove paint-source type restriction, then implement one shared replace_paint_source action. Preserve stroke objects/bounds, timing/hand/painting settings and other scenes; retain immutable original/guide bytes, recompute regions and invalidate cached plans; source changes use the existing per-element undo architecture.
2. Integrate PR20 preference and menu visibility changes onto .64. Keep one warm engine while a dialog is open. Protect every genuine dismissal and result-use path until both generation and model workers finish native cleanup. Own process trees and reader threads, stop only owned subprocesses, wait after kill, retain retryable ownership on cleanup errors.
3. Add drawing-source replacement and simple staged source editors. Timeline Draw/Paint hit tests match painted part rectangles in both scopes, target the clicked scene, and leave press/drag/overlay/audio behavior intact. Keyboard/context actions share the same editor/backend.
4. Regression evidence at every stage, then existing full Windows/Linux suites and installer. Prepare .65 review artifacts; do not merge main, force-push, publish stable or advance the installed update channel without release approval.

Architecture: a source-editing mixin owns transactional prepared replacements and source history; no renderer rewrite. Existing ArtworkWorkflow handles whole-artwork placement. Paint-source changes fit the new original proportionally to unchanged drawing bounds, recalculate paint support, and explain when a differently composed image needs Draw reconstruction. Image-mode SVG guides retain native source in drawing attributes and use the existing original-color image as painting authority. Existing schema1 metadata remains usable.

Undo: cache a small immutable source-context record by source identity alongside existing settings/stroke snapshots; no PNG/base64 re-encoding on every scrub/history sample. Restore source context before stroke/settings replay. Source edits make shallow Drawing copies, retaining stroke identity unless explicitly reconstructed.

Process verification: run real PID/tree/RAM fixtures on Windows/Linux and, where practical, two requests on real CPU ComfyUI. A procedural CPU graph or fixture is NOT real model inference; no claims of freeing the user's actual6.1GB allocation without the matching environment. We will report any GPU/model limitation honestly.

Scope: no major UI overhaul; retain .64 projects, Library pairing, SVG fills, fonts, hand calibration, sound and exports. New branch feature/source-edit-ai-lifecycle-experimental65.

Execution ledger:
- Read PR20. It is based on .63 and cannot replace full .64 files: doing so loses original/guide handoff.
- Root causes: explicit image-type disable in sync_workspace/load_color; only-root Engine.stop and mutable reader process; incomplete native-finish and accept/done guards; stage timeline double-click currently dispatches whole-element settings and single-scope current_scene defaults0.
- Phase1 RED tests added before implementation.
