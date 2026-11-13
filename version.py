"""Single source of truth for StrokeScribe version information.

Official releases: RELEASE_CHANNEL = "Release" and a plain version (1.0.0).
Prototypes between releases: RELEASE_CHANNEL = "Prototype" and an experimental version
(1.0.1-experimental.1, .2 ...); an experimental build comes before its release.
"""
APP_NAME = "StrokeScribe"
APP_VERSION = "1.0.1-experimental.6"
RELEASE_CHANNEL = "Prototype"
RELEASE_DATE = "2026-11-12"
DISPLAY_NAME = (f"{APP_NAME} v{APP_VERSION}" if RELEASE_CHANNEL == "Release"
                else f"{APP_NAME} — {RELEASE_CHANNEL} v{APP_VERSION}")
PACKAGE_NAME = (f"{APP_NAME}-v{APP_VERSION}.zip" if RELEASE_CHANNEL == "Release"
                else f"{APP_NAME}-{RELEASE_CHANNEL}-v{APP_VERSION}.zip")
