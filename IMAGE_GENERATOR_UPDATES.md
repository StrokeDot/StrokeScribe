# Image Generator Updates drawer — experimental.59

Based on experimental.58 from safety/controlled-refactor-phase6.
This change updates the existing Qt Create Image or Sound dialog.

## Try it
Use the existing Windows setup/launcher from this version's source ZIP.
Open Create Image or Sound (AI), then click **Check for updates** in the header.
The drawer stays open on repeat clicks. Close with X or Escape; prompts, selected
models, seeds and result images are preserved. On smaller windows, the form and
preview stack within a scrollable area. The drawer scrolls independently.

**Manage models…** beside Model opens the real registered model list (including
audio). Choose model opens its existing task, version, license and download
controls. It does not download or install anything automatically. Normal model
downloads and generation continue through the original worker and engine code.

## Demonstration only
The updates drawer is clearly marked **Demonstration data — no live update check**.
Its installed states, update revisions, compatibility and sizes are examples from
the UI brief, not measurements of the user's computer or verified current releases.
Update, Install and Keep current show inline feedback and never touch model files.
Details expand inline. Browse models opens Hugging Face's image-generation catalog;
compatibility still requires a separate check. Audio never appears in this drawer.

## Structure
image_generator_updates.py contains immutable ModelUpdateItem metadata, demo_items,
UpdatePanel, ModelStatusCard, SectionHeader and StatusBadge. Callers can inject
items into UpdatePanel; its presentation is independent of the generation engine.
A future live metadata provider and real update/install transactions are deliberately
not implemented. Such work must reuse the app's existing installation protections,
license acceptance and file-integrity checks.

## Verification
test_image_generator_updates.py exercises interaction, Escape, state preservation,
separation from downloads, real model selection, image-only sections, injected
metadata and narrow/wide layouts. The dedicated Image generator drawer review
workflow runs it alongside the existing CreateImageWindowTests and UI theme tests
on Linux Python 3.12 and Windows Python 3.14. The existing full regression workflow
also runs. No user's local model installation is used.

render_image_generator_updates.py creates wide/compact/closed screenshots and a
model-manager screenshot in samples/image-generator-updates. CI artifacts include
these and the Windows source ZIP; it is not a self-contained executable.
