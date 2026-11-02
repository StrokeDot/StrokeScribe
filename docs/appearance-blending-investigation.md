# Appearance & Blending: findings and draft acceptance plan

Base: published experimental.73, independently of native Windows-host PR #35 for experimental.74. This branch is NOT a release.

## Expected mathematics
Multiply against pure white is neutral; white pixels reveal the destination only if an opaque destination exists. Against transparency, Multiply cannot manufacture alpha. Off-white paper alters the color below, so two off-white drawings can retain visible rectangles. These are mathematical limitations, not extra missing blend modes.

## Confirmed renderer bug
The Program monitor and some full-scene preview/export paths previously blended a completed frame containing both the illustration and moving hand. The hand was therefore blended against the background too. Blend Mode was already saved per scene but its main control was exposed in the Inspector rather than the per-element dialog.

## Candidate solution
1. Use separate artwork and hand layers. Apply the selected mode and artwork opacity to the current art only, then draw the hand with normal SourceOver.
2. Element Editor offers Appearance & Blending with existing modes, opacity 0–100%, optional paper cleanup, tolerance and edge softness. Preserve saved per-scene mode; old projects default to 100% and cleanup disabled. Cancel restores the full prior snapshot.
3. Remove only near-white/off-white paper connected to the outer image border on a derived QImage, keeping the original stored source intact and preserving enclosed white regions. Painting plans, times and source strokes continue to use original imagery.
4. Unit pixel tests and real-scene preview/export consistency checks, including partially painted scenes, independent elements, colored backgrounds and hand overlays.

## Known risks before release
Border-connected intentional white/light details may be affected by aggressive cleanup, so users must tune threshold and softness. Video editor compositing with a truly transparent output remains separate from the preview background. Full Windows display scaling, saved older projects, multi-scene alpha export and Filmora must be manually accepted. Experimental.74 host/installer changes are on another branch and must be integrated, not overwritten.

No change to published update channel or main until validated and explicitly approved.
