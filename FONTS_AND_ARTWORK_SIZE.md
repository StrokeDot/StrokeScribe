# StrokeScribe Handwriting Fonts and Artwork Size

**Added in v0.5.3-experimental.2.** These controls are separate from official v0.5.2 and do not replace the existing built-in pen alphabet.

## Handwriting fonts

The Source & Paths panel now includes **Text / Handwriting**, an editable font-family selector, and four actions:

- **Animate lettering** — creates strokes from the entered text using the chosen source.
- **Download selected Google Font** — enter or select a family name and download one font file from the official Google Fonts GitHub repository.
- **Download 10 handwriting fonts** — installs ten curated handwriting fonts in one operation: Caveat, Kalam, Patrick Hand, Indie Flower, Dancing Script, Sacramento, Gochi Hand, Architects Daughter, Shadows Into Light, and Reenie Beanie.
- **Import local TTF / OTF…** — choose an existing font file that you have permission to use.
- **Browse Google Fonts catalog ↗** — opens Google's handwriting-family catalog in your browser. You can type a selected family's name into the font selector to download it.

The **Built-in single-line pen** remains available without any font download and has more natural pen-lift geometry. Google Fonts letters are converted into **approximate centerline paths**, rather than tracing each glyph's thick outer outline. That can make a more handwriting-like animation, but automatic skeleton tracing still creates imperfect strokes, unusual joins, and occasional extra pen lifts. It is not a reconstruction of the font designer's real drawing sequence.

The font size input labeled **Glyph detail size** adjusts the raster-to-centerline tracing resolution (24–128 pixels); it is not the final size on the video canvas. Use **Artwork Size (%)** in the Animation inspector for the final visual size.

Fonts are **open-licensed, not generally public domain**. Source fonts and their corresponding original license files are downloaded only on request and saved in `%LOCALAPPDATA%\StrokeScribe\fonts`, shared across different StrokeScribe app versions. Do not remove or rewrite the license files if redistributing fonts. StrokeScribe itself does not include those ten binary fonts in the downloaded application ZIP, keeping it small. Google Fonts' complete repository exceeds 1 GB, so downloading all families is deliberately not the default. Fonts imported directly from your PC remain subject to their own licenses. The user is responsible for compliance with each font's license.

**Online access:** Downloading fonts requires access to GitHub's public API and raw font files. Animation itself is offline after installation. The app only downloads fonts when you click a download control; no automatic font installation or hidden API token is used. Unsupported families or connectivity errors display an explanatory message.

## Artwork size vs export resolution

In the right **Animation** inspector, **Artwork size** defaults to 100%. The valid range is **25%–200%**. At 50%, the image is half the normal scale, leaving more blank/transparent canvas; at 150%, it is enlarged and may be cropped by the canvas edges. The aspect ratio and output resolution remain unchanged. This applies equally to SVG line drawing, colored PNG transitions, raster AI/image reconstruction, handwriting and the optional hand.

The same scaling function operates in **preview and export**, preserving relative positioning of all layers. The hand is scaled with the scene; a future independent hand-size adjustment could separate that behavior. If the preview looks cropped above 100%, reduce the percentage. Transparency of the unused canvas remains intact.

The output's `sequence.json` includes the `artwork_scale` value for repeatability.

## Testing

- `test_font_features.py` checks font names, mocked official Google Fonts downloads with matching licenses, font-to-centerline conversion when a system TTF is available, output scaling and preview/export consistency.
- Cloud CI runs those tests on Linux and Windows Python 3.14.
- The full Google Fonts catalog and actual artist-quality handwriting need user testing; no paid AI or Codex credits are used in font rendering.

GitHub pull request #3 remains experimental; official v0.5.2 is unchanged.

### v0.5.3 experimental.3 legibility fix

The initial centerline extraction broke visible letterforms into small marks. StrokeScribe now animates the complete font's genuine ink progressively per character rather than pretending fragmentary skeleton paths are finished lettering. The font looks like its true typeface when a word is completed; the hand follows an approximate left-to-right reveal rather than authentic pen strokes. The built-in single-line pen mode continues to trace genuine authored strokes.

### Experimental.4: stroke-following for actual typefaces

Google Fonts no longer rely on horizontal clipping to show each letter. A thinning algorithm builds approximate centerline paths per glyph, orders them for plausible writing, assigns original font pixels to the nearest pen-path position and draws the actual glyph ink as the hand follows each estimated stroke. Finished letters preserve their complete true font shape. This **cannot recover the original typographer's pen movements from TTF/OTF files**; dotted letters, loops, intersections, and cursive ligatures may still have unusual movement. The legacy built-in pen follows its original handcrafted vector paths unchanged. The previously downloaded ten Google Fonts still work without redownloading.

### Experimental.5: deterministic one-stroke-at-a-time handwriting

The estimated font paths and the optional drawing hand now use **one shared timeline**: draw the current path, lift the pen, move to the next path, then draw it. Every original font-ink pixel is assigned to exactly one owning stroke and one time within that stroke's allotted interval, so later disconnected fragments cannot reveal simultaneously or during a pen-lift. The hand's cursor position and ink reveal derive from the same event schedule. The complete original TTF/OTF glyph appearance is retained on the final frame. Font path ordering is still an approximation—not a recovery of historical pen movement—and some complex joined glyphs may need manual correction. New regression tests check pauses and stroke order. Unrelated image reconstruction, AI Redraw, exports and official v0.5.2 are unchanged.

### v0.5.3-experimental.6 — smoother writing, ink/background colors, hand defaults

The inferred pen-tracing algorithm now filters very short redundant skeleton spurs situated next to already covered longer paths. This reduces little return twitches after a glyph has nearly finished, while independent dots and punctuation are kept. Font appearance is unchanged at the settled final frame; precise historical writing order still cannot be inferred from regular TTF/OTF files.

A new **Ink color** chooser applies to both Google Fonts and built-in single-line lettering; it updates the currently generated lettering live and is used on the next generated text. **Lettering background** offers Transparent (default), White, Black or a custom color. This choice affects actual PNG/WebM/ProRes export frames as well as the preview. Background is composited after scaling so it always covers the entire output canvas; choosing Transparent preserves alpha. Neither control recolors imported SVG drawings or image reconstruction. Studio's Hand panel defaults are now **Hand scale 0.75**, **Pen tip X 0.20**, **Pen tip Y 0.20**, with hand visibility enabled during drawing and painting. These are defaults, not a change to saved hand PNG geometry; users can adjust them.

The official v0.5.2 and AI image redraw algorithms are unchanged. New tests verify these settings, transparent/colored export pixels, and color changes after lettering has already been created.
