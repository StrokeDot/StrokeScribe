# StrokeScribe — Windows prototype

A small local desktop tool for short SVG drawing overlays. Built from original application code with PySide6/Qt and svgelements; no proprietary software was reverse-engineered.

## Run on this computer

Double-click **Launch.cmd**. The tested environment has already been installed in the parent directory's `.venv`. A sample drawing loads automatically. Click **Play / pause** or **Restart**.

## Set up on another Windows computer

1. Extract the project ZIP into a normal writable folder.
2. Install 64-bit Python 3.12 or newer from https://www.python.org/downloads/windows/ . Include the Python launcher. This prototype was tested with Python 3.12.
3. Double-click **Setup.cmd**. It creates a local virtual environment and installs the pinned dependencies from PyPI. Internet is needed for this step.
4. Double-click **Launch.cmd**. Rendering and exports run locally and require no account or network service.
5. Optional MOV export: install an FFmpeg build containing `prores_ks`, following https://ffmpeg.org/download.html , and put its `bin` folder on PATH. Restart the app afterward. PNG export does not need FFmpeg.

No standalone EXE or installer is supplied. The source project and launcher are runnable after setup.

## Make an overlay

1. Import a plain SVG, or use the included house-and-sun sample. Artwork is automatically fitted and centered; the original SVG page margins are not retained.
2. Select strokes in the left list and use Move up / Move down. Separate SVG subpaths become separate strokes, preventing lines across pen lifts.
3. Set duration, speed, and thickness. Actual duration is base duration divided by speed. Time per stroke is proportional to its length; pen lifts are instantaneous.
4. Play or scrub the slider. The checkerboard indicates transparency and is never exported.
5. Optionally load your own transparent hand PNG. Set the pen tip X and Y fractions to the pen contact point inside that PNG. Example: a tip at pixel (100, 150) in a 500×600 PNG has X=0.20 and Y=0.25. Adjust hand width, or uncheck Show hand.
6. Choose resolution and frame rate. Export creates a new timestamped folder with numbered RGBA PNGs and a sequence.json file. It does not overwrite an earlier export.
7. Check the MOV option to additionally encode ProRes 4444 after the PNGs are written. The PNG sequence remains available if MOV encoding fails.

The first frame is empty and transparent. The last frame is the complete drawing. There is no extra hold at the end. Extend/freeze the final frame in your editor if desired. The hand disappears at completion. Export includes round(duration × fps) frames, with at least two frames; very short durations are quantized to this frame count.

## Text and hand limitations

- Create lettering replaces the current drawing. It uses an original, simple slanted single-line print alphabet. Lowercase becomes uppercase. This is not cursive, a font selector, or a reconstruction of a person's handwriting.
- Supported characters: A–Z, digits, spaces, line breaks, and basic punctuation. Unsupported characters are reported and skipped. Text is limited to 500 characters.
- Hand PNGs follow the active stroke with a fixed orientation. No animated hand sprites, wrist rotation, or interpolated travel between strokes. The test uses a synthetic overlay; no realistic hand asset is bundled.
- One drawing at a time. No project save/load, undo, multi-layer composition, audio, or video editing.

## SVG support and limits

Paths, straight segments, cubic/quadratic curves, arcs, and basic shapes are handled by svgelements, including ordinary group transforms. Curves are sampled densely and animated by accumulated geometric distance. This is path-following animation, not a screen-direction wipe. Sampling is an approximation, not an analytic partial Bézier renderer.

For best results, use plain SVGs with single-line strokes. Filled shapes are traced around their outlines rather than filled in. A bitmap converted to filled vector silhouettes will not automatically become natural pen strokes. SVG text should be converted to paths first (but font outlines will still be outlines). Embedded bitmaps are not traced by this app.

Complex CSS, gradients, masks, clipping, filters, nested SVG viewports, and opacity compositing are unsupported. Import warnings cover common unsupported elements, but this is not a complete SVG conformance checker. Stroke caps and joins use round styling. Imported dash patterns are not preserved. Artwork is fitted to a fixed safe area; extreme thickness and oversized hands may reach the frame edges. Large/complex SVG imports may take time on the UI thread.

## Performance

CPU preview and export use Qt's raster painter. Preview is rendered at 960 pixels wide and scaled to the window. Output is rendered at the chosen full resolution: 1920×1080, 2048×1080, or 2560×1440. No explicit GPU preview backend is implemented. Export runs in a worker thread. Cancel stops after the current PNG; already-written frames remain. Once FFmpeg encoding begins, cancellation waits for encoding to finish.

## Filmora 14

The sample ProRes MOV has been encoded and decoded with FFmpeg and its transparency verified. Import/alpha interpretation inside Filmora 14 has **not** been tested. Try `test-output/sample-1080p/animation_prores4444.mov` above a colored/video clip in Filmora and check that the background disappears. If Filmora rejects it or interprets it as opaque, keep the PNG sequence as the verified lossless source. Do not assume every editor imports PNG sequences or ProRes alpha identically.

## Tests and evidence

From a terminal in this folder after Setup.cmd:

```
.venv\Scripts\python.exe test_prototype.py
.venv\Scripts\python.exe verify_delivery.py
```

On the original computer use `..\.venv\Scripts\python.exe` instead. The verification script creates `test-output/sample-1080p` and deliberately refuses to overwrite it. Move that output aside before repeating verification.

Five automated tests cover reverse-direction geometry, transformed strokes and pen lifts, growing coverage and alpha, text/hand rendering, export sizes/cancellation/overwrite protection, and UI playback/scrubbing/reordering. The app window was also launched on Windows.

The delivery includes a 48-frame 1920×1080, 24 fps sample, a ProRes 4444 MOV, representative 2048×1080 and 2560×1440 images, a UI screenshot, a contact sheet, and machine-readable verification.json. Full-HD PNG rendering took about 2.32 seconds for the test drawing on this machine; that is a sample measurement, not a guarantee for other artwork.

## Open-source components

- PySide6 / Qt 6.10.2: https://doc.qt.io/qtforpython-6/ — LGPLv3/GPL/commercial licensing as applicable. Installed package includes upstream licensing information. No Qt binaries are redistributed in the source ZIP.
- svgelements 1.9.6: https://github.com/meerk40t/svgelements — MIT.
- Pillow 12.1.0: https://python-pillow.github.io/ — HPND; used for verification.
- FFmpeg: https://ffmpeg.org/ — optional separate installation; licensing depends on build.

The original application code and sample SVG are provided under the MIT license in LICENSE. Review dependency license obligations before redistributing a packaged executable.

## Branding

The `assets/strokescribe_icon.png` file is the StrokeScribe S/pen-nib logo with a transparent background. The Windows application uses it for its window/taskbar icon and displays it in the header of the running interface. This asset ships with the source and is loaded relative to `app.py`, so it works from either Windows launcher and from any working directory. The `.cmd` launcher file itself keeps the default Windows command-script icon; a packaged `.exe` can receive its own embedded `.ico` later.

## Final Artwork Reveal (new optional feature)

To preserve the full colors of a detailed PNG without degrading them through SVG tracing:

1. Import a **drawable stroke SVG** with **Import SVG…**. The SVG controls the hand's drawing movement, not the final colors.
2. In the left panel, click **Load original colored PNG…**. Choose the high-quality **transparent PNG** used to make the SVG.
3. Keep **Reveal PNG after drawing** enabled. Set the **Color crossfade** and **Final image hold** durations as desired (defaults: 0.4 and 0.6 seconds).
4. Press **Restart** to preview the SVG strokes, then the transition to the original PNG. Scrub through the entire timeline.
5. Export the usual alpha PNG sequence and optionally ProRes 4444 MOV. The exported final frame is the actual colored PNG rendered over transparency.

Color reveal is **off** until a PNG is loaded and does not affect traditional stroke-only exports. The original PNG is not altered or quantized; transparent external margins are cropped only for alignment. The colored artwork is aspect-fitted to the SVG's visible bounds and centered. For best alignment, both must depict the same object/view. If a traced SVG's proportions differ substantially, the reveal may shift slightly; precise registration tools are a possible later enhancement. A PNG with an opaque background will also produce an opaque background in the final artwork (use a transparent PNG for transparent video).

This feature does **not** automatically create strokes from a PNG. Use a separately traced/constructed SVG for now. Generated project ZIPs do not include the user's private colored art; load your own copy.


## Brush Painting reveal (experimental)

For **SVG drawing first, then hand-painted color**, import a drawable SVG, load the matching original colored PNG, and enable **Reveal PNG after drawing**. Choose **Brush painting** under **Reveal mode**. StrokeScribe draws the SVG first, then sweeps an invisible round brush vertically, down/up in a serpentine pattern, to reveal the original PNG without converting its shading into low-quality vectors. The last frame always shows the complete original PNG.

- **Reveal duration (seconds)** sets how long the painting sweep takes (or fade duration when Fade is selected).
- **Brush width / artwork** sets the sweep width as a fraction of the artwork width. Wider brushes mean fewer passes at the same duration.
- **Show hand during painting** independently enables the user's uploaded hand overlay to follow the moving brush. The existing **Show hand** checkbox controls the earlier SVG drawing stage only. Painting works normally with no hand uploaded.
- **Final image hold (seconds)** controls how long the finished PNG remains on screen.
- **Fade** remains available as the original alternative mode.
- Both the preview and exported PNG sequence / optional ProRes MOV use the same rendering function.

The source PNG itself remains unchanged and transparent edges are preserved. The coloring effect is an image-reveal mask (it is *not* a paint simulation); the SVG and PNG still need similar proportions for convincing alignment. During the sweep the SVG strokes are erased from painted regions. The moving hand uses the same PNG, size, and tip-anchor controls as the drawing phase, but is optional during painting.

The brush prototype is CPU-rendered with Qt and may export more slowly at 1440p. **The code is experimental and requires local visual testing.** It does not yet include precise SVG/PNG registration, variable brush angles, or physically realistic paint strokes.


## Continuous Drawing → Painting (experimental)

A third **Reveal mode** is **Continue from last stroke**, alongside Fade and Brush painting. After the last SVG path finishes, the brush-painting mask begins at that path's **actual final canvas position**, using the current **Stroke order** (including edits made with Move up/Move down). The path covers the artwork with connected, alternating vertical passes, sweeping from the starting position toward the nearer edge and then across the opposite side. No hand teleportation is introduced when moving between passes, though the brush may backtrack across the artwork. The user can choose independent hand visibility for drawing and painting. Painting works without any hand PNG.

The SVG-to-canvas projection matches the current vector renderer. If the colored PNG has proportions different from the SVG, the starting endpoint may lie outside the PNG's fitted rectangle: the painting hand travels from that exact SVG endpoint to the image edge rather than jumping. For best results, use matching PNG/SVG artwork. Color reveal still uses the unmodified original PNG, and the complete image appears after the mask finishes. Duration, width and hold are adjustable. The rendering and export use the same path generator.

This is a continuity experiment, **not** an AI-derived object-aware coloring route. It still uses a serpentine brush sweep after the start point and has not yet been visually validated on Windows.

## Stroke-guided painting (experimental)

Select **Stroke-guided painting** in the Reveal mode dropdown after loading both a stroke SVG and matching original colored PNG. This replaces the previous **Continue from last stroke** menu entry; Fade and Brush painting remain available. The previous "continue" rendering implementation stays in code for compatibility.

The new mode starts at the endpoint of the final stroke in the editable Stroke order list. It follows the last SVG path backward, then visits nearby SVG contour paths, progressively growing the PNG-color reveal outward from those paths. It is **not** a rectangular up/down brush sweep. Optional **Show hand during painting** makes the hand follow this vector route; the color effect also works without a hand. A disconnected path transfer can still produce a visible hand movement across empty space, but it does not paint during that transfer.

The original PNG is used at its original colors and alpha without vectorizing its shading. The final frame always displays the complete colored image. A reduced-resolution timing mask is cached for performance. It is geometrical approximation, **not** recognition of each headset component, and may show premature color spread or visual jumps if the stroke SVG and PNG do not align. Windows preview, PNG-sequence export, and MOV import need manual validation. The initial mask computation can take time on the CPU.

## Clean contour painting (new experimental mode)

Choose **Clean contour painting** in Reveal mode to test smoother color-animation hand movement. The existing **Stroke-guided painting** mode is preserved unchanged. The new mode starts at the last SVG stroke endpoint, then groups similarly labeled SVG paths (e.g. headset headband, left, right, microphone) before transferring to nearby paths. Transfers are pen-lifts: the painting hand is hidden during each repositioning movement. Hand visibility remains optional. A guided wavefront grows color from the SVG contours; the original colored PNG supplies every actual color.

**Temporary dark-outline artifact mitigation:** During this mode's painting phase, residual SVG strokes are clipped to the original PNG's visible alpha, rather than allowed to extend beyond the picture. This is especially useful if the tracing SVG has stray lines around the headset. The final frame is the unchanged original colored PNG. The initial line-drawing animation is untouched and may still show any stray SVG paths that exist in the source.

This is a geometry-and-label heuristic, not semantic object detection. Some path ordering or hand timing may still look unnatural. For meaningful tests set Reveal duration to 5–8 seconds and use a matching traced SVG and original transparent PNG. Python / Windows UI tests still require manual execution.

## Prototype version and versioned ZIP downloads

The current app shows **StrokeScribe — Prototype v0.5.1** in the title bar and **Prototype v0.5.1** in the header. Click **About • v0.5.0** for the release date and exact revision (when a versioned ZIP is used).

For the unmistakably named download, visit **GitHub → Releases** and select the newest **StrokeScribe Prototype** prerelease. Its asset is named `StrokeScribe-Prototype-v0.5.1.zip`, and extracting it creates a matching `StrokeScribe-Prototype-v0.5.1` folder. The included `BUILD_INFO.txt` records the release version and exact GitHub commit SHA.

**GitHub Code → Download ZIP will always use GitHub's standard branch-based name (`StrokeScribe-main.zip`).** For a version-named ZIP, use the release asset; do not confuse the two. If the GitHub Actions release workflow is unavailable, run `python package_prototype.py` from a source checkout to create `dist/StrokeScribe-Prototype-v0.5.1.zip` locally using only Python's standard library.

A new public-facing prototype version requires updating `APP_VERSION` in `version.py`. The GitHub Actions workflow packages a new prerelease when the version file or packaging workflow changes. The archive contains editable Python source and Windows launch scripts (not a standalone executable); run `Setup.cmd` in each newly extracted folder before `Launch.cmd` or `Launch-headset.cmd`. Do not delete your older working prototype folder until the new one has been tested.

## Prototype v0.5.1 — Adaptive Hand Painting

This release combines the original v0.5.0 application with the **Adaptive Hand Painting** experiment developed on a separate branch and validated in GitHub Actions. It adds a color reveal based on short, shape-constrained brush strokes, adjustable stroke spacing and an optional hand that follows the painting path. The four existing reveal modes and initial SVG drawing are preserved.

The original v0.5.0 release remains independently downloadable: [StrokeScribe Prototype v0.5.0](https://github.com/StrokeDot/StrokeScribe/releases/tag/prototype-v0.5.0). For the new combined version use [Prototype v0.5.1](https://github.com/StrokeDot/StrokeScribe/releases/tag/prototype-v0.5.1).

This remains an experimental prototype. Automated tests passed on the feature branch, but the actual original-color headset PNG is not stored in this repository, so brush movement and full-color alignment need manual Windows visual testing.


## Experimental image sources (v0.5.2)

PNG, JPEG, WebP and BMP can now become contour animations or region-guided painted reconstructions. See [IMAGE_SOURCE.md](IMAGE_SOURCE.md) for controls, algorithm, setup and limitations. Existing SVG modes remain available. AI redraw is not implemented.
