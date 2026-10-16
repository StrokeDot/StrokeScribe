# StrokeScribe — Prototype v0.5.2

**Current official downloadable prototype:** [StrokeScribe-Prototype-v0.5.2.zip](https://github.com/StrokeDot/StrokeScribe/releases/download/prototype-v0.5.2/StrokeScribe-Prototype-v0.5.2.zip).

This version includes the StrokeScribe Studio UI, direct SVG animation, raster image source reconstruction (PNG/JPG/WebP/BMP), Adaptive Hand Painting, other painting modes, and compressed transparent VP9 WebM alongside ProRes 4444 and PNG export. Requires 64-bit Windows Python 3.12–3.14 and local Setup.cmd; FFmpeg is required for video encoding. Some image-specific tracing/painting alignment artifacts are still under refinement.

**Previous versions remain available:** [v0.5.1](https://github.com/StrokeDot/StrokeScribe/releases/tag/prototype-v0.5.1) and [v0.5.0](https://github.com/StrokeDot/StrokeScribe/releases/tag/prototype-v0.5.0). Always extract a new release into its own folder.


A small local desktop tool for short SVG drawing overlays. Built from original application code with PySide6/Qt and svgelements; no proprietary software was reverse-engineered.

## Run on this computer

Run **Setup.cmd** once in the extracted release folder, then double-click **Launch.cmd**. The local `.venv` directory stores this prototype's dependencies. A sample drawing loads automatically. Click **Play / pause** or **Restart**.

## Set up on another Windows computer

1. Extract the project ZIP into a normal writable folder.
2. Install 64-bit Python 3.12 or newer from https://www.python.org/downloads/windows/ . Include the Python launcher. Windows Python 3.14 and Linux Python 3.12 were also exercised in automated tests.
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

A new public-facing prototype version requires updating `APP_VERSION` in `version.py`. The GitHub Actions workflow packages a new release when the version file or packaging workflow changes on main. The archive contains editable Python source and Windows launch scripts (not a standalone executable); run `Setup.cmd` in each newly extracted folder before `Launch.cmd` or `Launch-headset.cmd`. Do not delete your older working prototype folder until the new one has been tested.

## Prototype v0.5.1 — Adaptive Hand Painting

This release combines the original v0.5.0 application with the **Adaptive Hand Painting** experiment developed on a separate branch and validated in GitHub Actions. It adds a color reveal based on short, shape-constrained brush strokes, adjustable stroke spacing and an optional hand that follows the painting path. The four existing reveal modes and initial SVG drawing are preserved.

The original v0.5.0 release remains independently downloadable: [StrokeScribe Prototype v0.5.0](https://github.com/StrokeDot/StrokeScribe/releases/tag/prototype-v0.5.0). For the new combined version use [Prototype v0.5.1](https://github.com/StrokeDot/StrokeScribe/releases/tag/prototype-v0.5.1).

This remains an experimental prototype. Automated tests passed on the feature branch, but the actual original-color headset PNG is not stored in this repository, so brush movement and full-color alignment need manual Windows visual testing.


## Several pictures on one page, smoother playback (v0.5.3-experimental.45)

- **Several pictures on one page:** in the scene strip, click **+ Add picture**. The new picture is drawn on the same page, and the pictures before it stay there. Import its artwork, then drag it on the preview to place it. In the strip, a "+" marks a picture on the same page. You can also choose "Same page" under "Then" for any scene.
- **Move a picture:** drag it on the preview, or set Position X / Y in the Animation tab. Click "Center" to put it back.
- **Smoother playback:** while the preview is idle, StrokeScribe makes the next frames ready, so Play runs smoothly at the video's frame rate. If a frame is not ready and your computer is busy, it is drawn a little smaller while playing.
- **Clean colour picture in saved projects:** the background clean-up (fake checkerboard, faint leftovers) also works on the colour picture stored in older projects. Untick "Clean the PNG's background" to see it as saved.

## Timeline, autosave and update banner (v0.5.3-experimental.44)

- **Tabs in order of work:** Animation, Hand, Sound, Export.
- **Drag the timeline:** drag the right edge of the Draw, Paint, Hold or Erase clip to make it longer or shorter.
- **Audio lane, like a video editor:** drop a voiceover or music file on the lower row of the timeline, drag the clip to choose when it starts, right-click it to remove it.
- **Bigger timeline, smaller preview:** drag the divider above the timeline.
- **Sound when the export is finished** (Export tab, on by default).
- **Autosave every minute and recovery:** if StrokeScribe closes by accident, it offers to bring your work back at the next start.
- **File > Recent projects.**
- **Update banner:** when a new version is ready, a banner shows at the top with "What's new", "Update now" and "Later".

## Sound tab and complete transparency (v0.5.3-experimental.43)

- **Sound tab** (Inspector: Animation | Hand | Export | **Sound**): the pencil/brush/eraser sounds, Create a sound with AI, and the voiceover / music track are all here now. Also View → Sound settings.
- **Clean the PNG's background** (Animation tab, under *Load matching colored PNG…*, on by default): the matching colored PNG of an SVG gets complete transparency. A painted checkerboard ("fake transparency") or a plain sheet behind the artwork, and faint leftovers, become transparent. Only background connected to the picture's edges is removed, so white or grey parts inside the artwork stay; photos and textured paper are left alone. The note under the button says how much was cleaned. Untick it to use the PNG exactly as it is.
- The image import option is now **Clean the background (fake transparency, leftovers)** and does the same, plus the faint-pixel clean-up it did before.

## Windows installer (v0.5.3-experimental.42)

- **StrokeScribe-Setup-<version>.exe** (GitHub → Releases): a normal Windows installer with the StrokeScribe logo. It needs no Python and no Setup.cmd: a private Python with every package is included. It installs for your user only (no administrator), into `%LOCALAPPDATA%\Programs\StrokeScribe`, adds StrokeScribe to the Start menu (and the desktop if you like), and appears in *Settings → Apps* to uninstall.
- StrokeScribe starts without a console window and has its own taskbar icon. If it ever cannot start, a message box says why.
- After installing, updates come through the app (File → Update StrokeScribe…). Running a newer installer over it also works.
- Your Library, projects, settings and AI models are never touched by installing or uninstalling.

## Menu bar, no built-in sounds, check marks, quieter loading (v0.5.3-experimental.40)

- **Menu bar** like other programs: **File** (open, save, import, Library, export, batch export, update, exit), **Edit** (undo, redo, delete/reverse lines, add/delete scene), **View** (dark mode, preview background, this scene / all scenes), **Effects** (paint mode, pen movement, camera follow, erase at the end, painting hand, sounds, Hand only export, MP4 background, Auto timing, AI) and **Help** (setup, updates, about). Menu choices are the same settings as in the panels.
- **No built-in sounds**: the generated pencil/brush/eraser sounds and the export chime are gone. Sound comes only from sounds you add (Export tab or Effects menu) or make with Create sound; a tool without a sound is silent.
- **Check marks**: ticked boxes and menu choices now show a white ✓.
- **Less loading**: changing Brush width or Stroke spacing re-plans the brush quietly in the background (the last picture stays; *Updating the brush route…* on the timeline). The loading card appears only for bigger changes: a new paint mode, a new image, or choosing an eraser style.

## Update in the app (v0.5.3-experimental.39)

- **Project menu → Update StrokeScribe…**: updates this installation in place. No unzipping, no Setup.cmd. It replaces only the app's own files; your `.venv` packages, Library, projects, settings and AI models stay. New Python packages are installed only when a version needs them. The previous version is kept (**Go back to the previous version**).
- **Online**: the newest version is read from the StrokeScribe GitHub project. Because the project is private, paste a read-only GitHub key once (the window shows the steps: fine-grained token, only StrokeDot/StrokeScribe, *Contents: Read-only*). With the key saved, StrokeScribe checks at start and shows **⬆ Update to exp.NN** in the top bar when a new version is ready.
- **Offline**: **Update from a ZIP file…** uses a StrokeScribe ZIP you already downloaded.

## Create a sound with AI (v0.5.3-experimental.38)

- **✦ Create a sound with AI…** (Export tab → Sound), or **Create a sound** in the Create window: describe a sound and **Stable Audio 3 Small-SFX** (Stability AI) makes it on your PC. Ready descriptions for **Pencil**, **Brush** and **Eraser**; change the words as you like. Choose the length (8 s is plenty: it is looped while the pen moves), click **Generate**, **▶ Listen**, and **Use as pencil sound** (or brush / eraser). Not right? Generate again: every try is different.
- Download: 3.5 GB once (model 2.3 GB + text encoder 1.2 GB), in the same AI engine as Create image. It is small enough to run without a graphics card; with an NVIDIA card it is faster.
- License: Stability AI Community License — free for personal use, and for creators and businesses under US$1 million revenue a year; you own the sounds. You accept it once before the download.
- Sounds you use are kept in the Library (Audio).

## Mute button and Hand-only export (v0.5.3-experimental.37)

- **Mute button** (speaker, next to the play controls): sound on / off for the pencil, brush and eraser sounds, in the preview and in the exported video. It is the same switch as Export tab → *Pencil and brush sounds*. (A voiceover/music track is separate: remove it in the Export tab.)
- **Export tab → Export**: *Drawing and hand* (as before), **Hand only (no drawing)** or **Drawing only (no hand)**. Hand only exports just the moving hand on a transparent background (PNG, WebM, MOV), so you can lay it over your own text or picture in Filmora, for example your name in any font. The preview shows the drawing faintly so you can see what the hand writes; the export does not contain it.

## Real recorded pencil sounds (v0.5.3-experimental.36)

- **Export tab → Sound**: choose a real recording for the **Pencil**, and if you like the **Brush** and **Eraser** (MP3, WAV, M4A…). A few seconds is enough: quiet parts at the start and end are cut off, and the recording is looped from different places so it never sounds repeated. It plays only while the pen moves (louder when it moves faster), silent during pen lifts.
- **Built-in** goes back to the generated sound. Sounds are now **off by default**; choosing a recording switches them on.
- Recordings are kept in the Library (Audio), saved with the project, used by batch export and by all scenes.

## Scenes: several drawings in one video (v0.5.3-experimental.35)

The **Scenes** strip in the Timeline panel holds the drawings of one video, in order:

- **+ Add scene** adds a scene after the current one. It starts as a copy; import its own SVG or image (Import, Library or Create image). Every scene keeps its own drawing, colours, hand, timing, painting, eraser, camera and voiceover.
- Click a scene to edit it. **◀ ▶** change the order, **Delete** removes a scene.
- **Then** sets how the video moves to the next scene: *Camera move* (zoom out, travel along the board, zoom in, like VideoScribe), *Pan left/right/up/down*, *Zoom in*, *Fade* or *Cut*. **Move (s)** sets how long the move takes.
- **Preview → All scenes** plays and scrubs the whole video, with one block per scene on the timeline. (That preview has no sound; the export does.)
- **Export → Export all N scenes as one video** (on by default with several scenes): one video with every scene and the moves. Each scene's pencil sounds and voiceover play with that scene. Resolution, frame rate, formats, background and sound settings come from the scene you are editing. Uses all CPU cores.
- Scenes are saved in the project file. Batch export turns a multi-scene project into one video. Older StrokeScribe versions open such a project as the edited scene only.

## Faster export on all CPU cores (v0.5.3-experimental.34)

- Longer exports (from about 4 seconds of video) are rendered on several processor cores at once, one group of frames per core. The frames are exactly the same as before, only faster. **Export tab → Use all CPU cores (faster export)** is on by default; turn it off if you need the computer to stay quick while exporting. Batch export uses it too.
- If the fast path cannot start for some reason, the export simply runs on one core as before.
- Clicking a line on the preview now scrolls the left panel to **Lines & order**, so Delete, Reverse, pace and pause are in view.

## Pencil, marker and a painting hand (v0.5.3-experimental.33)

- **Built-in tools** (Hand tab): **Built-in hand**, **Pencil** and **Marker** buttons. Each one sets its own pen tip and a fitting size. The pencil and marker are tools on their own, without a hand.
- **Painting hand** (Hand tab → Painting hand): *Same as drawing hand*, *Built-in paint brush*, or *From Hands library* (for example your own hand holding a brush). The animation switches to it automatically when painting starts. **Painting hand size** sets its width. The brush tip is found automatically, or the tip saved in the library is used.
- Saved in projects (a library painting hand is stored inside the project file too) and used by batch export. Undo works for these settings.

## Undo everything, edit lines on the preview, timing control (v0.5.3-experimental.32)

- **Undo / Redo for everything** (Ctrl+Z, Ctrl+Y or Ctrl+Shift+Z, and the ↶ ↷ buttons): every setting and every line change, not only the stroke order. Changing a value several times in a row counts as one step.
- **Click a line on the preview** to select it (Ctrl+click or Shift+click for more). It is outlined, with a dot where the pen starts. The **Lines & order** panel then offers **Delete** (or the Delete key), **Reverse** (draw it from the other end), **Line pace** (Very slow to Very fast) and **Pause after** (the pen rests before the next line). Drag lines in the list to change the drawing order.
- **Pen movement → Natural (ease in and out)** (Animation tab): every line starts and ends a little slower, like a real hand.
- Line changes are saved in projects and used by every export, the camera and the sound.

## Voiceover, camera follow, backgrounds and Auto timing (v0.5.3-experimental.31)

- **Voiceover / music** (Export tab): **Load audio…** (MP3, WAV, M4A, AAC, OGG, FLAC, Opus, WMA) or pick one from the new **Audio** section of the Library. Set the track volume and when it starts. It is mixed with the pencil/brush sounds into every video (and `soundtrack.wav`), cut at the end of the animation, heard in the preview, and saved in projects. **Fit animation to audio** stretches draw, paint, hold and erase times (keeping their proportions) so the video ends when the track ends.
- **Auto timing** (Animation tab): picks draw, paint, hold and erase times from how much there is to draw. With a voiceover loaded it fits them to the voiceover instead.
- **Camera follow** (Animation tab): *Gentle zoom* or *Close-up zoom*. The camera glides after the pen, then pulls back to show the whole picture at the end. Frames are rendered larger and cropped, so they stay sharp. Shown in the preview and used in every export.
- **Backgrounds**: Whiteboard, Paper, Chalkboard and Cork textures, besides White, Dark and Black, for the preview and the MP4. Transparent formats (PNG, WebM, MOV) stay transparent.

## Eraser (v0.5.3-experimental.30)

Animation tab → **Erase at the end** adds an **Erase** stage after the hold (Draw → Paint → Hold → Erase), so the picture is rubbed away and the video ends empty:

- **Zigzag (follows the shapes)** — the eraser finds where the picture actually is and scrubs back and forth over it along one route (the same planner as Zigzag sweep painting), so it never wastes time on empty areas.
- **Along the lines** — the eraser follows the drawn lines backwards, last line first; anything left between lines fades away at the very end.

Settings: erase time, eraser size, and what is shown rubbing (the built-in eraser or your pen hand). The rubbed edge is soft, the eraser makes a rubbing sound in the soundtrack, and the stage is saved in projects and used by batch export.

## Library and automatic pen tip (v0.5.3-experimental.29)

- **▤ Library** (top bar; **Hands library…** in the Hand tab): a safe home for your images, SVGs and hands, like Canva uploads. Files are *copied* into a folder you choose (default `Documents/StrokeScribe Library`, with `Images` and `Hands` sub-folders), so moving or deleting the originals is safe. Upload, drag and drop, search, rename, show in folder, and delete (deleted items go to a *Deleted items* folder, so they can be recovered). With **Keep a copy of every file I import or load** (on by default), everything you import is added automatically.
- **Automatic pen tip**: when you load a hand, StrokeScribe finds the pen tip itself (the sharpest point of the hand-and-pen shape, farthest from where the arm enters the picture) and sets Pen tip X/Y. **Find pen tip** repeats it; **Click to set…** shows the hand so you can click exactly on the tip. The tip is remembered with each hand in the library. Manual X/Y adjustment still works.

## Projects, pencil sound and batch export (v0.5.3-experimental.28)

- **Save / open projects** (project menu, Ctrl+S / Ctrl+O): one `.strokescribe` file keeps the drawing with your stroke order, the colour image, the hand and every setting. Images are stored inside the file, so it still opens if the originals move.
- **Pencil and brush sounds** (Export tab → Sound): a pencil scratch while the pen draws (silent during pen lifts, louder when it moves faster) and a soft brush sound while painting, panned with the hand. Generated to match the animation exactly; included in MP4, WebM and MOV, and saved as `soundtrack.wav` with PNG exports. You can hear it in the preview while playing.
- **Batch export** (project menu or Export tab): queue images, SVGs and projects and export them all, each into its own folder. Images and SVGs use the current settings (an SVG is coloured with `name_color.png` or `name.png` next to it); projects use their own. Failed items are reported and the batch continues; a chime plays at the end.

## Create Image: local AI models (v0.5.3-experimental.27)

**✦ Create image** (top bar, or **AI line art for this image…** in the Image source panel) runs open image models on your own PC:

- **Line art for my image** — the AI redraws your image as clean black line art; StrokeScribe lines it up with your image, traces each drawn line as one pen stroke, and paints your original colours. Best for objects (TVs, headphones, products).
- **Create from text** and **Edit an image** — new images or instruction-based edits, which you can then draw in StrokeScribe.

Models (chosen version depends on your graphics card memory and system RAM; you can override it):

| Model | License | Use |
|---|---|---|
| Qwen-Image-Edit 2511 (Alibaba) | Apache 2.0 | Line art and edits; best free editor |
| FLUX.2 [klein] 4B (Black Forest Labs) | Apache 2.0 | Fast text-to-image and edits |
| FLUX.2 [dev] (Black Forest Labs) | FLUX Non-Commercial (accept before download) | Highest quality, very large |

The first time, click **Install AI engine** (about 5 GB: ComfyUI v0.41.1 with PyTorch for NVIDIA cards, kept in its own folder that you can move to another drive), then **Download** a model (4–40 GB, resumable). The engine runs hidden on 127.0.0.1 only while you make an image and stops with the app. Nothing is sent to the internet when generating.

**Use my own line drawing…** traces a black line drawing you already have (for example from ChatGPT) over your colour image the same way.

## New look: dark and light themes (v0.5.3-experimental.26)

The Studio has a calmer, video-editor style layout: panels with title strips (Source, Program, Inspector, Timeline), a program monitor with transport buttons and a timecode underneath, and a timeline with a time ruler, coloured Draw / Paint / Hold clips and a playhead you can click or drag. **Dark mode is the default**; the ☀ / ☾ button in the top bar switches to light mode and the choice is remembered. Space plays and pauses.

While a drawing is being prepared (importing an image, applying image settings, loading an SVG, or planning a new brush route after changing the paint mode or brush settings), the monitor shows a loading card with a progress bar and the timeline is locked; it unlocks when the drawing is ready.

The hand is now drawn on its own layer after **Artwork size** is applied, so it is no longer cut off by an invisible box when the artwork is made smaller; it is only ever cropped by the real video frame.

## Zigzag sweep painting (v0.5.3-experimental.25)

**Paint mode** now offers **Brush painting**, **Adaptive Hand Painting** and the new **Zigzag sweep** (the old Fade option was removed from the menu). Zigzag sweep starts where the drawing ended and follows one logical route along the object's centre line (for a headset: one side of the band, the ear cup, across to the other cup, up the other side), scribbling colour back and forth across the shape: wide strokes on broad parts, narrow ones on thin parts. Side branches (a microphone, a handle) are painted as the route passes them, and any spot the sweep missed is touched up at the end, so every visible pixel is always painted. Image sources can choose Adaptive Hand Painting or Zigzag sweep; plain Brush painting stays SVG-only. Hand, guide-line retirement, timing and export work exactly as with Adaptive Hand Painting.

## Artist animation (v0.5.3-experimental.24)

Images now animate like a pencil artist by default (**Animation: Artist (layered)**), following lessons from a real face-drawing video: light guide shapes first, then the main lines area by area with the densest detail last and slowest, then darker accents. Strokes carry their own drawing speed (`pace`). **Standard** keeps the single-pass animation. Exported SVGs keep each layer's colour and line weight.

## Clean drawing style and SVG export (v0.5.3-experimental.23)

Line art now has two **Drawing styles**: *Clean drawing* (default), which keeps only the meaningful lines as fewer, longer, smooth strokes, the way an artist would draw it, and *Detailed (all lines)*. **Export drawing as SVG…** saves the strokes as an editable SVG plus the matching colour PNG, so any image can be polished in Inkscape and re-imported through SVG source, like a hand-made SVG. See [IMAGE_SOURCE.md](IMAGE_SOURCE.md).

## Images: Line art (v0.5.3-experimental.21+)

Imported PNG, JPEG, WebP and BMP images are turned into clean, artist-style pen strokes by **Line art**, now the only image method. A small built-in line model (TEED, MIT license, `models/teed.onnx`, run with ONNX Runtime) finds contours and inner detail lines; dark ink lines are detected directly so thick outlines become one line and pencil strokes survive; wood grain and paper texture are ignored; dense shading is left to the colour painting. Strokes are traced along line centres, joined smoothly, and drawn outline first, then long lines, then details. Detail: Low, Medium (recommended), High or Max. No Ollama or other AI download is needed.

The painting hand only visits pixels that are at least ~25% visible; nearly invisible leftovers from background removal appear together with their nearest painted area. **Clean faint background leftovers** (Image source panel) removes such pixels completely.

**Removed in experimental.22:** Auto trace, Stroke reconstruction and AI redraw (Ollama/Qwen), together with their settings. Line art replaced them with better and more consistent results. The setup window's Fast/Balanced/Quality/Max levels now set Line art detail. See [IMAGE_SOURCE.md](IMAGE_SOURCE.md).

## Experimental image sources (v0.5.2)

PNG, JPEG, WebP and BMP can now become contour animations or region-guided painted reconstructions. See [IMAGE_SOURCE.md](IMAGE_SOURCE.md) for controls, algorithm, setup and limitations. Existing SVG modes remain available. AI redraw is not implemented.

## Compact WebM (experimental .2)

StrokeScribe now offers **Compact VP9 WebM + transparency** with adjustable quality 18–42 (28 default) alongside the unchanged ProRes 4444 and transparent PNG sequence options. Encoding still uses temporary PNGs for each frame; by default these are removed *only after* successful video encoding so the saved video can be much smaller on disk. Check **Keep PNG frames alongside encoded videos** to retain the full sequence. If no video option is selected, PNG frames are always retained. FFmpeg is required for video export. Filmora may vary in how it imports external VP9 alpha; verify transparency in Filmora before relying on it. The native Filmora plugin remains a future idea.

## StrokeScribe Studio UI (experimental.3)

New source/paths sidebar, large preview monitor, task-based Animation/Hand/Export inspector, and interactive Draw/Paint/Hold timeline. All existing animation modes and exports remain. Export Animation is also available from the persistent toolbar. Refer to `IMAGE_SOURCE.md` for navigation; see the four cloud-generated workspace screenshots in `samples/studio-preview/` inside the GitHub Actions review artifact. This is an original StrokeScribe layout, not a copy of Filmora, Premiere, or VideoScribe.

## Official v0.5.2 release

Image reconstruction, compact VP9 WebM, the Studio workspace and the SVG-to-PNG line-retention repair are now bundled in official **Prototype v0.5.2**. Previous experimental.1–.4 labels refer to development snapshots only. GitHub release tags for 0.5.0 and 0.5.1 are not altered. Full image reconstruction and alpha/color-transition details and current known limitations are in [IMAGE_SOURCE.md](IMAGE_SOURCE.md).

## Optional local AI Redraw (v0.5.3 experimental)

The new third Image Source method **AI redraw (local model)** proposes meaningful object parts and drawing order using an optional Ollama vision model, then uses image segmentation and the existing adaptive painting renderer to create a plausible construction animation. It doesn't use a paid API or generate a replacement image. Auto Trace and Stroke Reconstruction remain available without AI. The model download is separate and can require several GB of disk/RAM. For exact setup steps, privacy details and limitations, read [AI_REDRAW.md](AI_REDRAW.md). The official v0.5.2 release remains unchanged.

## Experimental v0.5.3.2: handwriting fonts and artwork size

The Studio Text / Handwriting panel now supports ten recommended Google Fonts families available by optional one-click download, an editable family name field for other Google Fonts, and importing local TTF/OTF files. It estimates pen-centerline paths from font glyphs so the hand can follow them; they are still approximations rather than true author-provided single-stroke fonts. The original built-in single-line alphabet remains the default. Original font license notices are stored with every Google Fonts download; Google Fonts are open-licensed, not public domain. No font binary files are added to the app ZIP.

The right Animation panel now offers **Artwork size** 25%–200%, separate from export resolution. The whole animated artwork, painting layer and optional hand scale around the canvas center in preview *and* export. Sizes over 100% can crop the canvas. More detailed instructions: [FONTS_AND_ARTWORK_SIZE.md](FONTS_AND_ARTWORK_SIZE.md). This is an experimental branch; official v0.5.2 is unchanged.

## v0.5.3 experimental.3 — font legibility, Ollama JSON, Studio header

Fixed incomplete Google Font lettering: instead of displaying fragmented skeleton traces, the animation reveals the original font's complete character shapes in order. This is a readable typeface reveal, **not** a reconstruction of authentic pen trajectories; the built-in single-line alphabet is still recommended for genuine pen drawing. AI Redraw now retries malformed/empty local Qwen responses with a second constrained JSON request, and provides more detailed failure messages. The upper Studio toolbar now shows the current source/project and has functional stroke-order Undo/Redo, quick Help and Export Settings controls. The user's official v0.5.2 remains unchanged.

## v0.5.3 experimental.4 — TrueType pen-following and requested branding

Google Fonts now animate from **estimated centerline stroke paths** rather than simple left-to-right per-glyph wipes. Each genuine glyph pixel is revealed according to its nearest simulated stroke, so the finished text remains faithful to the actual font. An optional hand follows the path, with pen lifts between strokes. Ordinary TTF/OTF files contain outlines but no authentic writing history, so this is a best-effort path estimate; handwriting remains a visual experiment. The built-in single-line pen mode is unchanged. The Studio top-left now shows the three decorative brand circles, white **Stroke** and blue **Scribe** wordmark, and the current prototype version. The real Windows window controls are untouched. The experimental AI Redraw implementation is unchanged while its local Qwen test is pending.

### Experimental.5: deterministic one-stroke-at-a-time handwriting

The estimated font paths and the optional drawing hand now use **one shared timeline**: draw the current path, lift the pen, move to the next path, then draw it. Every original font-ink pixel is assigned to exactly one owning stroke and one time within that stroke's allotted interval, so later disconnected fragments cannot reveal simultaneously or during a pen-lift. The hand's cursor position and ink reveal derive from the same event schedule. The complete original TTF/OTF glyph appearance is retained on the final frame. Font path ordering is still an approximation—not a recovery of historical pen movement—and some complex joined glyphs may need manual correction. New regression tests check pauses and stroke order. Unrelated image reconstruction, AI Redraw, exports and official v0.5.2 are unchanged.

### v0.5.3-experimental.6 — smoother writing, ink/background colors, hand defaults

The inferred pen-tracing algorithm now filters very short redundant skeleton spurs situated next to already covered longer paths. This reduces little return twitches after a glyph has nearly finished, while independent dots and punctuation are kept. Font appearance is unchanged at the settled final frame; precise historical writing order still cannot be inferred from regular TTF/OTF files.

A new **Ink color** chooser applies to both Google Fonts and built-in single-line lettering; it updates the currently generated lettering live and is used on the next generated text. **Lettering background** offers Transparent (default), White, Black or a custom color. This choice affects actual PNG/WebM/ProRes export frames as well as the preview. Background is composited after scaling so it always covers the entire output canvas; choosing Transparent preserves alpha. Neither control recolors imported SVG drawings or image reconstruction. Studio's Hand panel defaults are now **Hand scale 0.75**, **Pen tip X 0.20**, **Pen tip Y 0.20**, with hand visibility enabled during drawing and painting. These are defaults, not a change to saved hand PNG geometry; users can adjust them.

The official v0.5.2 and AI image redraw algorithms are unchanged. New tests verify these settings, transparent/colored export pixels, and color changes after lettering has already been created.

## v0.5.3-experimental.9 — Balanced AI processing

Image Source → AI Redraw now offers **Fast**, **Balanced** (selected by default), and **Quality** AI processing profiles, independent of the Low/Medium/High contour Detail control. Balanced retains the existing 640px/8-part vision settings while using local-region OpenCV GrabCut instead of full-frame segmentation per object and keeping the local Ollama model warm for five minutes. A cached scene plan is reused when only Detail changes, and the cache now distinguishes processing profiles. [AI_PERFORMANCE.md](AI_PERFORMANCE.md) describes all settings, limitations and the CPU-only benchmark. Existing SVG, lettering, image import and output modes are unchanged. Official Prototype v0.5.2 remains available.
