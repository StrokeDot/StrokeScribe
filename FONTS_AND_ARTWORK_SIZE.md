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
