# Create Image — functional model updates (experimental.61)

The former demonstration update drawer now performs actual local model inventory and
checks official Hugging Face file metadata. Each registered image model appears once.

## Using the drawer

- Check for updates scans the configured StrokeScribe AI folder in a background thread.
- The official Hugging Face weight URL must provide SHA-256 and byte size. Local
  file hashes are compared. A large file check may take minutes. Unknown publisher
  revisions are shown as unverified, not as available updates.
- Different official revision means different weights at the registered publisher
  URL, not necessarily a newer or better trained model. Confirm before updating.
- Update downloads a complete candidate with resume and SHA-256 verification
  before switching the original. The original weights stay in a filename.previous
  backup. Canceled or failed downloads never replace installed weights.
- A small manifest in the AI root records verified updated checksums and sizes,
  permitting revised files to run even if their bytes differ from the static
  registry size. Interrupted file-renames are restored at next inventory scan.
- A previous-version backup blocks additional updates until that backup is resolved.
  This intentionally avoids silently deleting large model backups.
- Install or Repair selects the real model and uses the pre-existing download
  worker. The user may need to install the AI engine or accept a model license first.
- Model checks cover the installed variant's primary weights. Text encoders and
  VAEs remain managed by the existing model downloader.
- Sound models do not appear. This feature is separate from app version updates.

## Limits and verification

The release is experimental. Remote model checks depend on accessible, trustworthy
Hugging Face HEAD metadata and an internet connection. No unknown URLs or arbitrary
third-party model files are installed through the updater. Existing model files are
hashed locally; the weights are not uploaded.

Automated tests simulate tiny model files and network metadata. They check duplicate
prevention, safe cancel/failure, checksums, recovery, and UI button wiring. Actual
multi-gigabyte downloads and GPU/ComfyUI generation require manual Windows tests.
