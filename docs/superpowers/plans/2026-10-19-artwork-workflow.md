# Artwork Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add artwork without losing other elements, preserve drawing/original pairs, and paint supported native SVG fills consistently.
**Architecture:** One prepared artwork record feeds the existing scene model and frame renderer. File/Library/AI entry points share transactional placement; durable source metadata extends existing version-1 project fields. Native SVG geometry stays in engine.py and a bounded SVG appearance helper provides paint pixels.
**Tech Stack:** Existing Python, PySide6/QtSvg, Pillow, OpenCV, svgelements and GitHub Actions; no additional dependencies.
**Spec:** docs/superpowers/specs/2026-10-19-artwork-workflow-draw-paint-design.md

## Global constraints
- Remote GitHub/CI only; no user Windows installation access.
- Based on experimental.63; preserve its sampler, 5 MB SVG source limit and 500,000 sampled-point maximum.
- No main merge or update-channel publication. User release approval remains required after passing tests.
- Keep existing version-1 drawing/image/color_png/settings fields usable; metadata is additive.
- SVG cached surface maximum: 8 million pixels; retained SVG appearance cache maximum: 128 MiB.
- No new models, paid APIs, dependency updates or unrelated UI redesign.
- Execute inline using the user's authorization to exercise judgment; an independent whole-branch review follows.

## Review focus
- Failed asynchronous import must leave both the current and other elements unchanged: task 2.
- Library pairing must survive external-file removal and library migration: tasks 1 and 3.
- Older projects with missing guides must still render from embedded image/strokes: task 3.
- Nonzero viewBox, unequal source/output aspect ratios and transparent holes must align: task 4.
- A huge SVG intrinsic size must not drive raster allocation or bypass parser protections: task 4.

## Task 1 — durable artwork assets
Files: create artwork_assets.py and test_artwork_assets.py.
Interfaces: capture_assets(original_path, guide_path=None) -> dict; validate_assets(data) -> dict; materialize_assets(data, root=None) -> (original_path, guide_path|None). Metadata schema=1, kind=raster, original/guide entries contain base64 source bytes and a whitelisted extension. Original files remain byte-identical. Managed materialization names derive from SHA-256, never metadata paths.
- [ ] Write tests: paired capture, materialization after external deletion, malformed metadata, path traversal, bounded image/source sizes.
- [ ] Run remotely and observe failure before implementing.
- [ ] Implement guarded capture/validation and atomic managed-cache materialization; use existing image/project storage conventions.
- [ ] Re-run focused tests; commit the verified stage and ledger result.
Limits for raster source records: 64 MiB encoded source bytes per asset before base64, 16 million decoded pixels per image; reject clearly rather than truncate. This is a bounded intake policy, not downsampling of the original.

## Task 2 — transactional placement and New Project
Files: create artwork_workflow.py (Window mixin), test_artwork_workflow.py; modify app.py and menus.py.
Interfaces: Window.request_artwork(path, kind='image', original=None, placement=None, name=None, same_spot=False) -> bool; Window.new_project() -> bool. Placement values add, replace, new. Prepared raster completion uses the existing ImageBuilder with an attached request context; old direct build_image behavior remains available for reconstruction controls.
- [ ] Write failing UI tests for default Add, explicit Replace/New, cancellation/failed Save, empty project, invalid SVG and late raster completion.
- [ ] Run tests and inspect RED failures.
- [ ] Prepare SVG before mutation; prepare raster through ImageBuilder without changing current source/path state. Capture project-generation token and selected element identity. Commit only on successful preparation and valid context.
- [ ] Reuse project-leave confirmation only for destructive choices. New Project clears assets/scene state with an empty Drawing, clears project path, and marks an untitled project clean; it does not restart the application or touch settings/models/library.
- [ ] Route load(), use_library_item(), use_ai_result(), import_artwork() and new_element() through the shared path. Avoid duplicate placement prompts for already explicit Add actions.
- [ ] Test and commit stage; ensure failures/cancellation do not create copied scene shells.

## Task 3 — original/guide pairing and presentation modes
Files: modify app.py, artwork_workflow.py, artwork_assets.py, library.py, create_image_dialog.py, studio_workspace.py, export_job.py, image_reconstruct.py, ai_lineart.py, projects.py; add test_artwork_pairing.py.
Interfaces: artwork metadata is embedded per scene and attached to prepared drawings; Library.set_artwork(item, metadata) stores pairing in its existing managed index; Item.artwork defaults to None. New readers materialize embedded assets for rebuild without trusting provenance paths.
- [ ] Reproduce lost AI kind/original arguments; test import/Add/Replace/Library/save/reopen equivalence and drawing-only.
- [ ] Capture pairing on generated line-art Library retention and on committed intake. Preserve original and guide bytes, normalized frame/crop data and registration diagnostics.
- [ ] Keep original pixels immutable. Correct guide framing only where a representative regression proves a mismatch; use aspect-preserving framing and bounded registration, reporting poor match.
- [ ] Add Drawing only to the existing image-animation choice without changing existing Draw, then Paint / Paint Only values; default newly committed paired artwork to Draw, then Paint and preserve old saved settings.
- [ ] Validate metadata on load; old projects lacking metadata keep embedded image/strokes. Rebuild prefers managed embedded assets when external originals are unavailable.
- [ ] Verify paired Library migration, external path deletion, old projects and render modes; commit stage.

## Task 4 — native SVG appearance
Files: create svg_appearance.py and test_svg_appearance.py; modify engine.py, artwork_workflow.py, app.py, projects.py, export_job.py as required.
Interfaces: SVG drawing retains svg_source, svg_viewport and svg_has_fill serializable attributes. svg_appearance.render_appearance(drawing, max_side=2048) -> QImage; clear_cache() and cache_bytes() expose bounded cache behavior to consumers/tests.
- [ ] Write failing tests for black fill, multiple fills, compound holes, fill opacity, inherited styles, transformed paths, viewBox origin/margins, outline-only and hostile dimensions/references.
- [ ] Observe RED remotely.
- [ ] Share the engine's validated/sanitized source between svgelements and QtSvg. Preserve .63 sampling; no forced PNG import. Detect computed fill presence and preserve vector strokes.
- [ ] Render original appearance with the same viewport-to-stroke-bounds mapping; bound pixel allocations and cache accounting/eviction. Block external resources and retain entity protections.
- [ ] On committed filled SVG enable original appearance painting; outline-only remains drawing-only. Preserve selected mode on project restore and allow explicit matching-image overrides.
- [ ] Verify source retention, old-project fallback, frame alignment and cache budgets; commit stage.

## Task 5 — full animation acceptance and delivery
Files: add render_artwork_workflow.py and test_artwork_rendering.py; modify relevant CI test lists, version.py, README.md and the execution ledger.
- [ ] Add representative transparent and opaque illustrations and paired guides generated as original test fixtures.
- [ ] Verify empty/partial/completed drawing, painting at 25/50/75 percent and final RGBA appearance through each entry point. Compare preview and exported PNG frames from the same options.
- [ ] Verify drawing-only, old project load, native SVG fill completion, transparency and existing WebM/ProRes paths with FFmpeg.
- [ ] Run focused tests then existing complete Windows/Linux suites including new modules. Surface logs and skips; normal test-process exit is required.
- [ ] Render labeled frame/contact-sheet artifacts; package a source ZIP with an experimental candidate version, without changing the application update channel.
- [ ] Request fresh whole-branch review; fix important findings with regression evidence, rerun appropriate checks, record limitations/rulings.
- [ ] Deliver PR, tested source ZIP, changed-file/test report and explicit missing-user-artwork manual checks. Await user release approval.

## Execution record
Progress and verification evidence: docs/superpowers/plans/2026-10-19-artwork-workflow-ledger.md.
No test success or user-example success is implied by this plan.
