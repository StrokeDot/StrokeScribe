# Artwork workflow review — experimental.64

This candidate is on feature/artwork-workflow-draw-paint, PR #19. It is not merged or published to the installed-app update channel. Keep the existing installation and test this candidate in a separate folder after release approval or with its review source ZIP.

## What changed and why

Previously intake routes could replace artwork or build a copied scene before preparation succeeded. The shared artwork_workflow.py transaction now prepares first, validates the editing target and only then adds/replaces/starts a project. New Project has an explicit menu action; unsaved changes reuse the existing Save / Discard / Cancel policy.

Some Create Image/add-element paths lost the result kind and original source, and Library retained only the guide. artwork_assets.py now embeds immutable original/guide bytes with bounded validation. Project files and Library sidecars retain this pair, including managed recovery after moving/removing external files. Library keep-imports preferences are honored. Existing format-1 projects without metadata still use their embedded drawing/color image.

Guide images were unconditionally stretched to original-image proportions before alignment. Reconstruction now evaluates aspect-preserving fit/cover candidates and records the selected frame/registration score. This fixes the representative square-letterboxed portrait regression without claiming every AI guide matches its original.

SVG import previously retained only extracted stroke paths, so fills were unavailable to painting. It now also retains validated native source and viewport metadata. QtSvg renders a bounded appearance in the same frame as the stroke geometry, with explicit preserveAspectRatio mapping and ordinary stroke-inclusive bounds. The source stays native SVG; the raster is an internal paint derivative.

## Files to review

- artwork_workflow.py, app.py, menus.py: placement, New Project, async commit, source-aware timing and persistence.
- artwork_assets.py, library.py, projects.py, create_image_dialog.py: durable pair capture, validation, Library and project recovery.
- image_reconstruct.py: aspect-preserving guide framing.
- svg_appearance.py, engine.py, export_job.py: source preservation, bounded native appearance and saved-scene rendering.
- studio_workspace.py: explicit Drawing only choice.
- test_artwork_*.py, render_artwork_workflow.py, CI workflows: regression checks, actual frame/export comparisons and review artifacts.
- version.py, README.md and execution ledger: candidate identity and evidence.

## Manual test in a separate Windows folder

1. Extract the review source ZIP to a new writable folder. Run Setup.cmd, then Launch.cmd. The title should show v0.5.3-experimental.64. This is a source build requiring the existing pinned Python dependencies; it is not a published installer update.
2. Use File → New Project. Try Cancel, Save and Discard on a changed project. Cancel/failed Save must retain the project; successful New Project should show an empty preview and no exportable artwork.
3. Import an image, then another SVG/image. Keep Add selected. Confirm both timeline elements remain; Replace must affect only the selected element. Try an invalid file and cancel a chooser.
4. In Create Image → Line art for my image, choose an original and generate line art. Use Draw it in StrokeScribe. Scrub the drawing phase, 25/50/75% of painting and the end. The end should contain the original colored picture, with matching proportions, rather than the guide.
5. Repeat using the paired Library item. Save/reopen a .strokescribe project; move the external original/guide aside. Rendering should still work. The original external files are never deleted by the app.
6. Select Drawing only and confirm the painting phase disappears from both playback and timeline duration. Check Paint Only and Draw, then Paint again.
7. Import a plain filled controller SVG. Check the editable vector stroke list, progressively drawn contours, black/color fill painting and transparent holes at completion. Save/reopen and repeat. For an outline-only SVG there should be no unwanted automatic fill.
8. Export transparent PNG frames and, when FFmpeg is installed, WebM/ProRes. Check the first/mid/end frames in an editor at the same settings; transparency must remain transparent.

## Evidence and artifacts

The focused remote suite checks each actual intake route through reconstruction and compares exported PNG frames against the shared preview compositor. It checks monotonic painting progress and exact finished source-frame RGBA on representative transparent artwork. SVG tests include black compound fills, opacity, transforms, unequal viewport proportions, borders, persisted-source rejection and bounded caches. Broad existing suites include animation modes, fonts, project lifecycle, WebM/ProRes and update safety.

The remote workflow creates samples/artwork-workflow with original synthetic house, letterboxed portrait and controller fixtures, separate transparent PNGs at drawing/painting stages, and checkerboard contact sheets. Contact sheets are for review; the underlying PNGs retain alpha. These examples are test artwork, not substitutes for the user's originals.

## Remaining limitations / manual checks

- The actual Cain and Abel, beach-girl and Xbox controller source files were not available in this remote checkout. Their exact visual results still require the manual checks above. No access to the user's Windows installation or private image folders is implied.
- AI-generated line art can differ structurally from its original. Fit/cover registration helps framing; it cannot reliably repair a different pose, crop or composition. Poor-match warnings remain relevant.
- SVG support is the existing svgelements geometry subset plus QtSvg native appearance. Text/embedded images/external resources and some advanced clip/filter/CSS cases are unsupported or warned. Nonuniform transformed strokes, non-scaling strokes and sharp miter joins may need extra visual refinement; ordinary stroke bounds are not a complete SVG visual-extents solver.
- Old projects without the original/guide metadata still render from their embedded data. They cannot recreate missing external guide bytes for a fresh rebuild.
- Embedding source pairs increases project sizes. Managed caches and Library sidecars are retained for recovery; automatic orphan cleanup is not part of this change.
- Tests use remote headless Qt on Windows/Linux. This does not establish GPU preview performance or replace visual testing in Filmora on the user's PC.

No main merge or update publication is authorized by this document.
