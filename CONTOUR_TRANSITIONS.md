# Advanced drawing and painting transitions — experimental.10

Image sources only. Animation inspector: Drawing visibility, Contour transition,
Retirement direction. Legacy remains the default. Existing SVG/font rendering,
AI processing, hand calibration and encoding are unchanged.

## Behavior
- Reveal strokes as drawn starts empty. Completed strokes persist, only the
  current path grows, and pen lifts create no ink. Image imports now open at
  time zero; press Play. Show full outlines is an explicit debug option.
- Legacy uses the previous color renderer without the new transition.
- Fade with painting removes temporary outlines using the actual brush
  coverage, not the original PNG opacity. Semi-transparent source pixels
  therefore do not leave permanent dark ink. Stray contours outside the
  coverage retire along their own paths during cleanup.
- Retire stroke by stroke keeps contours while painting, then removes exactly
  one path at a time in the user's stroke order, weighted by length.
  Forward erase removes the beginning first; reverse removes the end first.
- Original source pixels are preserved. The hand follows the paint mask's tip
  and is hidden during cleanup. Preview, scrubbing and export share a pure
  renderer; export deep-copies the chosen settings.

## Deliberate first-version limitation
New modes allocate 70% of image paint time to existing brush painting, 28% to
ordered cleanup, and 2% to the settled result. Retirement conservatively waits
for the entire image to be painted. It does NOT yet start each contour as soon
as its particular region is ready. This prevents holes with imperfect traces,
but long cleanup may look mechanical. Increase image paint time for review.
No additional global color fade is introduced in Adaptive Hand Painting.

At 98% the image is already settled; 100% does not force remaining outlines
away. Fade-with-painting can hide several already-painted contours as the brush
crosses them; only the explicit retirement phase is strictly one at a time.
A changing background or custom matte is not introduced.

## Validation and manual review
CI runs test_contour_transitions plus the existing suite on Linux and Windows.
render_contour_samples.py produces an RGBA synthetic headset-like illustration,
drawing-stage frames, six paint-stage frames for each mode/direction, and a
checkerboard comparison. This synthetic fixture is NOT the user's original
headset PNG. Review the real headset manually with its matching trace.

Download the workflow artifact, extract dist/StrokeScribe-Prototype-v0.5.3-experimental.10.zip,
then use the existing Windows launcher. Select Image source, import/reconstruct
an image, and open Animation. Compare Legacy, Fade with painting and Retire
stroke by stroke. Test both directions, reorder paths, scrub backward, and
compare exported PNG frames. No local files were modified to prepare this build.

Outstanding visual refinements: per-region retirement readiness, the perceived
speed of short contours, and real-headset misalignment. New modes remain optional.
