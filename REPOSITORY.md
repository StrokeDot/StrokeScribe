# Source repository

This repository contains the existing StrokeScribe source, Windows launchers,
pinned dependencies, tests, sample SVGs, and original documentation.

## Fresh checkout on Windows

1. Install Python 3.12 with the Python launcher.
2. Run `Setup.cmd` from this folder.
3. Run `Launch.cmd`, or `Launch-headset.cmd` for the headset example.
4. Optionally install FFmpeg on PATH for transparent ProRes MOV export.

The original README describes the initial local delivery, including references
to generated example videos and screenshots. Those generated files and the
original machine's virtual environment are intentionally not in Git.
Run `test_prototype.py`, `verify_delivery.py`, or `render_headset.py` with the
configured environment to produce test artifacts and sample exports locally.

The headset SVG is a manual contour reconstruction. Automatic PNG conversion
is not implemented. Existing application source has been preserved unchanged
during this initial repository import.
