# Artwork workflow and Draw → Paint consistency

Date: 2026-10-19
Status: design for user review; implementation not started.
Repository: StrokeDot/StrokeScribe
Baseline: experimental.63, commit 36259c067c85890a242f5423cf24bdce77f51f92.
Work branch: feature/artwork-workflow-draw-paint
Execution: remote GitHub and CI only. Do not access the user's Windows installation.
Release rule: no merge to main and no publication to any application-update channel until tests pass AND the user explicitly approves the release. Design approval is not release approval.

## 1. Outcome and scope

A user can bring artwork into an existing project without losing existing elements, draw its contours, paint its original appearance, and reopen/export the same result later. Success requires the entire animation, not just importing a file.

Keep the three changes together as one workflow project, with separately verified implementation stages:
1. explicit project creation and consistent artwork placement;
2. durable original/guide pairing and a shared Draw → Paint pipeline;
3. native SVG appearance preservation.

Preserve existing drawing, painting modes, hands/calibration, AI model files and installation, font handwriting, audio, scene/page behavior, saved projects, transparent PNG/WebM/ProRes exports and existing resolutions. Retain the .63 adaptive SVG sampler and its complexity limits. Do not redesign the application or modify AI inference/model selection.

## 2. Investigation evidence and limits

The baseline has these concrete behaviors:
- File has Open/Save project actions but no explicit New Project action.
- app.Window.load(), use_library_item() and use_ai_result() normally take replacement paths and use confirm_leave_project().
- new_element('ai') receives (kind, path, original) from CreateImageDialog, then calls use_ai_result('image', path, None, as_element=True), losing a generated guide's type and original-image association.
- new_element() creates a copied scene before the selected asset is completely imported. A failed import can therefore leave a changed timeline.
- image_reconstruct.reconstruct() can use an original color image plus a separate guide; options_from_settings() already supplies image_result.image as the final paint image. Retain these working primitives.
- scene_state() embeds the processed color image but records a guide mainly as an external path. Library image entries do not reliably carry an original/guide relationship.
- guide preprocessing resizes a guide to the original file dimensions before cropping; mismatched aspect ratio and affine alignment need regression investigation. This is a candidate source of geometric differences, not a proven diagnosis for the user's two images.
- engine.import_svg() deliberately turns fills into stroke contours and warns that filled appearance is not retained. The .63 sampler fixes import performance, not fill appearance.

The repository tree has no clearly identified Cain-and-Abel, beach-girl or Xbox-controller originals. Use original synthetic fixtures for automated coverage. Do not claim the named examples are reproduced without their actual files. List them in the manual acceptance report.

## 3. User-visible placement contract

Add File → New Project (Ctrl+N), creating an empty untitled project rather than loading the sample as new user artwork. Keep the startup sample behavior separate from an explicit new project.

All artwork entry points share one placement choice:
- Add to current project: default when a project is open; append a new timeline element after the selected element without changing existing artwork. Use the existing scene/page placement rules; do not implicitly replace the current project.
- Replace selected artwork: explicitly identify the selected element. Disable when there is no eligible selection. Preserve other elements, their ordering, transitions, audio and global output settings.
- New Project: explicitly begin a separate project containing the prepared imported artwork.

The empty project accepts the first asset without creating a duplicate blank timeline element.

Show Save / Discard / Cancel only for potentially destructive operations: New Project, opening another project, or replacing unsaved artwork. Adding an element must not trigger a leave-project prompt. Save must succeed before a destructive action proceeds; cancellation or a failed save leaves the original project intact. A clean replacement needs no unsaved-work prompt. Reuse the existing project-leave policy rather than creating a competing save policy.

For replacement, keep the existing project's scope and unaffected elements. The prompt identifies that the selected artwork will be replaced. Saving first preserves the pre-replacement project.

Acquire the file, generate/select AI output, prepare its drawing and validate the required appearance before committing a timeline change. Cancellation, invalid input or reconstruction failure commits nothing. Capture the intended project/element identity before asynchronous work and prevent a late result from changing another project or element. Block conflicting intake operations during preparation; closing or cancelling must safely finish/cancel the worker.

Build the new element from clean artwork state, not a copy that accidentally inherits a different asset's image_result, final_image, guide or source-kind flags. Keep existing non-artwork defaults and placement controls.

## 4. Shared artwork record and persistence

Introduce one prepared artwork record used by file import, Library import, Create Image results and replacement/addition:
- source kind and display name;
- original raster image or retained SVG source;
- optional generated/user line-art guide;
- drawable vector stroke geometry;
- source coordinate frame, crop/fit and guide registration information;
- default presentation mode and any alignment/unsupported-feature warning.

Preparation produces this record without mutating the current project. Placement commits it once. Preview and export consume the same record and render settings.

Add an optional, versioned artwork metadata block to each scene. Keep existing version-1 fields (drawing, source, image/color_png and settings) as valid compatibility representations. Do not change the outer project format version solely for this additive extension. New readers load old projects with no metadata through an adapter. Do not silently invent a missing guide for an old project: its saved stroke geometry and embedded final image remain usable.

Embed enough data to reopen without external paths: original image, guide when present, retained SVG text and registration/frame information. External paths are provenance, not the only durable copy. Keep derivative render caches out of serialized drawing attributes. Preserve faithful existing image/color_png fallback fields for older project readers.

Library imports with a pairing preserve a managed copy of both assets and metadata using the Library's existing safe storage rules. Existing single-file Library entries remain valid. Adding or updating metadata must not rewrite unrelated Library assets, downloaded models or existing projects. Existing project files are unchanged until the user explicitly saves.

Use the existing atomic project writer. Validate embedded sizes and structure on loading. Deduplicate immutable image data within an in-memory artwork record; do not keep another full-size copy for every animation frame.

## 5. Draw → Paint behavior

For Create Image → Line art for my image → Draw it in StrokeScribe:
- preserve the result kind and original argument through every placement path;
- trace the generated guide for the drawing phase;
- paint from the original input image, not from the monochrome guide;
- apply the same crop/fit/registration frame to drawing and paint;
- retain original proportions, alpha and color values.

Use Draw → Paint by default for newly imported assets with an original appearance and drawing. Provide explicit Drawing only and retain Paint Only. Existing saved projects keep their saved mode; do not override it on load or every refresh. Adding a new asset must not inherit an unrelated previous element's drawing-only setting.

Normalize guide framing without stretching a different aspect ratio to fit. Evaluate registration against representative shifted, scaled, letterboxed and low-contrast fixtures. Keep the original raster pixels immutable; transformations apply to the guide and coordinate metadata. Reject non-finite or extreme transforms. If the AI changed the illustration too much for reliable registration, report that limitation and keep a non-destructive choice; do not silently distort the original or substitute another tracing method while claiming a successful match.

Use the existing painting modes and shared frame renderer. Drawing is initially empty and progressively follows stroke order. Painting reveals original pixels with existing mode semantics. At completion, the entire intended original artwork is visible, temporary guides do not protrude outside it, and the hand is absent when the completed state requires it. Drawing only suppresses original-color painting.

Test pairing at the intake, scene serialization and renderer boundaries. Preview, single export and batch/scene export must produce the same completed appearance.

## 6. Native SVG drawing and appearance

SVG remains an SVG source:
- retain validated original SVG content and coordinate framing;
- retain vector stroke geometry and user-editable stroke order for drawing;
- use Qt's bundled SVG renderer for the supported original filled appearance during painting;
- use an internal raster appearance cache only as a derivative, never as a substitute for retained SVG source and paths.

The same SVG-source-to-canvas transform must position both outlines and appearance. Account for viewBox origin, source margins, transforms and StrokeScribe's recorded frame attribute. Preserve aspect ratio, fill colors, fill opacity, holes and supported fill rules. A supported black-filled controller-like fixture must finish as a filled controller-like shape, not just its border.

For fill-bearing SVGs, default new artwork to Draw → Paint. For an explicitly outline-only SVG (fill=none), preserve the existing drawing behavior and avoid an unnecessary second paint stage. Drawing only remains selectable for filled SVGs. Do not infer that every closed stroke has a fill: honor SVG style/inheritance.

Qt supports a subset of SVG. Unsupported appearance features must produce an accurate warning and must not be claimed as faithfully preserved. Do not convert an import failure into a successful PNG-import operation. Do not fetch external images, stylesheets, fonts or DTDs. Retain the existing document-entity protections; use the validated/sanitized source consistently for both parsing and rendering.

Maintain the 5 MB source limit and 500,000 sampled-point limit. Bound appearance cache dimensions and total pixels independently of hostile SVG intrinsic dimensions; cap a cached surface at 8 million pixels and all retained SVG appearance surfaces at 128 MiB using an eviction policy. Render at the requested output resolution within the supported application resolutions. Account for intermediate surfaces, avoid allocating a surface from untrusted width/height attributes, and do not serialize renderer objects or frame caches.

A project compatibility color_png may hold a bounded appearance derivative, but reopening in the new application must use retained SVG source for rendering at the selected resolution. Document older-reader fallback limitations without changing existing files.

Reference: Qt 6.10 QSvgRenderer documentation:
https://doc.qt.io/qtforpython-6.10/PySide6/QtSvg/QSvgRenderer.html

## 7. Implementation boundaries

Expected integration points:
- app.py and menus.py: New Project, placement selection and committing prepared artwork;
- a small shared artwork-intake/persistence module: prepared records, adapters and transactional placement support;
- CreateImageDialog result/Library integration: preserve complete pairing and managed asset copies;
- image_reconstruct.py / ai_lineart.py: measured framing/registration corrections only;
- projects.py / scenes.py / export_job.py: backward-compatible scene persistence and consistent render-mode selection;
- engine.py plus a small SVG-appearance helper: native geometry and bounded original-appearance rendering;
- shared rendering integration: preview/export consistency, without parallel rendering implementations.

Exact helper names are implementation choices. Do not perform unrelated refactors or replace working animation engines.

## 8. Regression and visual acceptance matrix

Stage 1:
- All four entry points offer the same placement choices.
- Add retains two or more distinct original elements, order, transitions and settings; no leave prompt.
- Replace changes exactly the selected artwork; unrelated elements stay byte-equivalent in saved state where applicable.
- New Project produces an empty project; explicit import-as-New Project creates one element.
- Save success, Save cancellation, failed Save, Discard and Cancel behave correctly.
- Cancelled chooser, invalid SVG, failed raster preparation and late asynchronous completion do not alter the current timeline.
- Undo/history and autosave remain coherent after committing an intake operation.

Stage 2:
- Generated-guide intake and add-AI-element retain guide + original.
- Repeat using direct import, Library, selected replacement, added element and saved/reopened project.
- Delete/move external original and guide paths, then reopen the self-contained saved project and render it.
- Test transparent/opaque art, non-square dimensions, shifted/scaled guide, letterboxing and low-contrast mismatch.
- For every entry point verify: empty frame, partial drawing, completed drawing, 25/50/75 percent painting, and final original.
- Check drawing-only and Paint Only; preserve modes in old projects.
- Compare final RGBA pixels to independently transformed original pixels, allowing only documented resampling tolerances at edges.

Stage 3:
- Synthetic black controller-like filled SVG; multicolor fill; compound path holes; fill-opacity; inherited fill; nonzero viewBox; transforms; source margins; outline-only SVG.
- Vector stroke progression remains sequential and editable; source SVG retained after save/reopen.
- Painting-phase intermediate frames and final appearance verified against an independently rendered SVG reference.
- Transparent background remains transparent; no residual temporary outlines outside the completed artwork.
- Complexity limits, huge intrinsic dimensions, forbidden external references/entities and repeated preview sizes stay bounded or fail clearly.
- Preview and PNG export frames match for fixed options; exercise existing WebM/ProRes alpha/export regression tests with FFmpeg.

Run focused tests after each stage and the existing full Windows/Linux suites before completion. Record exact tested commits and all skips/failures. Do not claim real local-model inference or user-PC testing from mocks/headless CI.

Produce labeled sample frames for drawing, painting at 25/50/75 percent, and completion. The named user examples require actual-file manual verification; representative fixtures do not replace that acceptance.

## 9. Delivery and approval gates

First deliver this design for user review. After design approval, write the implementation plan, review it with the user and select the execution method required by the development workflow.

Implementation delivery includes:
- experimental feature branch and review PR, with stage commits;
- source ZIP and visual artifacts from the tested revision;
- summary of actual root causes, files changed, tests and remaining limitations;
- explicit manual checklist for the user's named images and SVG if absent from the repository.

Do not advance the installed-app update branch, create/publish a release, or merge to main as part of implementation. Tests passing makes the candidate ready for user release review, not authorized for release.
