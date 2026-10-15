"""Create a self-contained, VERSIONED source ZIP for Windows prototype testers.

Run: python package_prototype.py
Output: dist/StrokeScribe-Prototype-vX.Y.Z.zip
The ZIP contains source, launch/setup scripts, icon, and SVG samples.
Dependencies are installed by Setup.cmd; this is not a standalone EXE.
"""
from __future__ import annotations

import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from version import APP_VERSION, DISPLAY_NAME, PACKAGE_NAME, RELEASE_DATE

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
FOLDER_NAME = PACKAGE_NAME.removesuffix(".zip")
SOURCE_EXTENSIONS = {".py", ".cmd", ".md", ".txt"}
SOURCE_FILES = (
    [p for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS]
    + [ROOT / "LICENSE"]
    + [p for folder in ("assets", "samples") for p in (ROOT / folder).rglob("*")
       if p.is_file() and p.suffix.lower() in {".png", ".svg", ".wav"}]
    + [p for p in (ROOT / "models").glob("*")
       if p.is_file() and p.suffix.lower() in {".onnx", ".txt"}]
)


def main():
    DIST.mkdir(exist_ok=True)
    package = DIST / PACKAGE_NAME
    revision = os.environ.get("GITHUB_SHA", "local-package")
    details = (f"{DISPLAY_NAME}\n"
               f"Version: {APP_VERSION}\n"
               f"Release date: {RELEASE_DATE}\n"
               f"GitHub revision: {revision}\n"
               "Repository: https://github.com/StrokeDot/StrokeScribe\n")
    with ZipFile(package, "w", compression=ZIP_DEFLATED, compresslevel=8) as zipfile:
        for path in sorted(set(SOURCE_FILES)):
            if not path.is_file():
                raise FileNotFoundError(f"Required package file is missing: {path}")
            zipfile.write(path, arcname=f"{FOLDER_NAME}/{path.relative_to(ROOT).as_posix()}")
        zipfile.writestr(f"{FOLDER_NAME}/BUILD_INFO.txt", details)
    print(f"Created: {package}")
    print(f"Archive folder: {FOLDER_NAME}")
    return package


if __name__ == "__main__":
    main()
