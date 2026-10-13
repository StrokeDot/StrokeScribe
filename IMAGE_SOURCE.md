# Image source reconstruction — v0.5.2 experimental

Choose **Image** in the source selector, import a PNG/JPEG/WebP/BMP, then press Play.
Choose Auto trace or Stroke reconstruction and Low/Medium/High detail, then **Apply image settings** to rebuild.
Preserve original colors adds an Adaptive Hand Painting phase; turn it off for contour-only drawing.
Painting duration is separate from line drawing duration. Brush width, spacing and optional painting hand use the existing controls.
Export resolution, 1–60 fps, transparent PNG and optional FFmpeg ProRes 4444 are unchanged.
Switching back to SVG restores the SVG drawing and optional original PNG.

## Algorithm
The analysis image is reduced and smoothed; alpha silhouettes, simplified color-region boundaries and Canny detail contours become ordered polylines.
Auto trace prioritizes silhouette then detail. Stroke reconstruction also traces color boundaries and prioritizes large, medium and accent regions after the first region.
Small color fragments merge spatially into nearby major regions. Original RGBA pixels are kept separately and never quantized for export.
Transparent margins are cropped consistently before both tracing and painting; opaque backgrounds are retained.
Adaptive painting begins at the final ordered contour endpoint. Color-region labels constrain the existing brush plan, while original alpha constrains coverage.
The same brush path and timestamps drive reveal and hand position. Transfers between disconnected regions hide the hand; contour transitions also include hidden pen-lift time.
Preview and export share these functions. SVG Drawings without raster metadata retain the original engine.

## Experimental limitations
This reconstructs plausible contours and brush order, not the artist's original strokes. It does not recognize objects or use an AI model.
Photos, gradients, textured or noisy images may produce distracting doubled contours and many small regions. Low detail is a useful first attempt.
The planner uses a bounded 224-cell analysis grid; very fine strands can have coarse masks. Brush width cannot exceed the region's usable interior.
Image decoding, tracing and the initial brush route run in a worker. Later brush/spacing/order changes can pause preview while a new route is computed.
Original colors and alpha are preserved in the settled image, subject to normal output scaling and Qt premultiplied-alpha rounding.
Analysis refuses images above 24 megapixels. Animated WebP uses its first frame. AI redraw is a disabled placeholder.
There is no manual region editor yet. A future tool could split/merge and prioritize regions, then let the user choose a brush direction.
Windows usability, taskbar, real artwork quality and Filmora interpretation require user testing; remote CI is Linux offscreen Qt.
The headset colored PNG is not assumed available from local Windows paths. CI uses a clearly labeled synthetic transparent illustration.
Review 25/50/75/100% painting samples in the GitHub Actions artifact, including a contact sheet and runnable source ZIP.

## Setup
Extract the entire prototype ZIP into a new folder and use the existing Windows setup/launch scripts.
Run setup again to install the new pinned NumPy and OpenCV dependencies; do not reuse an incomplete old dependency folder.
For manual Python setup: Python 3.12, install requirements.txt, then run app.py.
For tests: QT_QPA_PLATFORM=offscreen and python -m unittest -v test_prototype test_adaptive test_image_source.
FFmpeg on PATH enables MOV export.
