# Studio workspace review

The experimental v0.5.2 branch has a dark, original workspace with a blue accent:
source and stroke order on the left, a large central monitor, Animation/Hand/Export inspector tabs on the right, and an interactive stage timeline below.

Import → adjust → preview → export:
1. Select SVG or Image and import artwork on the left. Image reconstruction controls remain available.
2. Use the Animation inspector for drawing and painting timing; only source-appropriate painting controls are shown.
3. Load and calibrate the optional hand in Hand.
4. Scrub by clicking/dragging the timeline. When focused, Left/Right step, Home/End jump to the boundaries.
5. Export Animation in the header opens the Export inspector so formats are reviewable before choosing a destination.
6. PNG sequences, WebM and ProRes remain supported by the existing export engine. Progress/status are always visible beneath the timeline.

The monitor background selector affects preview only; exported pixels remain unchanged.
The version is visible in the header and About. Side panels are resizable and settings scroll on smaller windows.
This is a single-artwork stage timeline, not a multitrack editor. No decorative undo, audio or editing controls imply unavailable features.
Animation, tracing and encoding modules are unchanged by this UI refinement.

Remote CI covers old feature tests, source-sensitive controls, preview-background isolation, export navigation/busy protection and timeline interaction.
Screenshots for all inspector tabs, image import and a compact window are included in the review artifact.
Manual Windows review should check DPI scaling, display size, hand calibration and Filmora imports with representative artwork.
