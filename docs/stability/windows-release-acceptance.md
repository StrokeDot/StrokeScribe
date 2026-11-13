# StrokeScribe — Windows release acceptance (manual evidence gate)

**Status: NOT EXECUTED.** This checklist is not an approval, CI result, Filmora compatibility claim, or authorization to merge/publish.

## Record before testing

- Candidate commit SHA (exact 40 characters):
- GitHub Actions run URL showing passed Linux and Windows tests at that SHA:
- Windows version, GPU, Python/runtime version, app version:
- Installer artifact URL and SHA-256:
- Filmora version:
- Tester/date:
- Baseline project/sample paths and backup location:

Use a disposable Windows test installation, a copy of representative user projects,
and an isolated test library. Never test destructive update/rollback scenarios
against the user's only copy of data. Simulate power loss only in a disposable VM
with a snapshot.

## Data integrity and existing functionality

- [ ] Open/save/reopen existing multi-scene projects, imported PNG/SVG artwork,
      library images and hands, overlays, audio, and custom settings without
      losing data. Compare to untouched baseline copies.
- [ ] Exercise Save / Discard / Cancel when closing, switching projects and
      replacing artwork. Cancel must leave the project open; failed/cancelled
      saving must prevent leaving; Discard must require explicit selection.
- [ ] Migrate a library into a different existing library with colliding names:
      retain both non-identical files and their correct metadata; test a
      deliberate copy failure and confirm the original remains intact.
- [ ] Verify PNG source fidelity at the final animation frame for both
      Draw → Paint and Paint Only. In Draw → Paint, visible guide strokes
      disappear only as the corresponding region is painted. In Paint Only,
      invisible paths guide painting without an initial visible draw.
- [ ] Change artwork size and verify hand size remains independent. Adjust
      brush width during preview and animation; check for UI hangs or crashes.

## Updates, workers, recovery

- [ ] Cancel a slow update download and close the update dialog while a worker
      runs: no half-downloaded file replaces a verified download.
- [ ] Try an invalid/traversal ZIP in a disposable installation. Reject the ZIP
      before any live file is replaced; existing projects and app still open.
- [ ] Apply a valid update. Verify its version, relaunch, and preservation of
      user library, projects and settings.
- [ ] Simulate an interrupted update and an interrupted manual Go Back in
      a snapshotted Windows VM. On restart, recover the previous working
      installation and retain useful diagnostic information.
- [ ] Confirm manual rollback target and test a failed app restart. Do not
      discard a working installation, backup, or unsaved project.
- [ ] In a disposable AI setup, cancel ComfyUI archive extraction and model
      downloads, and verify previous engine/model assets remain intact.
      Verify an interrupted ComfyUI.previous swap is recoverable.
- [ ] Install, launch and uninstall the packaged Windows installer, checking
      that the private runtime works and user data outside the installation
      directory survives.

## Rendering and Filmora acceptance

- [ ] Export SVG + source PNG through scenes, a camera transition and audio.
      Confirm rendered PNG frame files remain available when Keep PNG is on.
- [ ] Export a VP9-alpha WebM. Confirm the source transparency is genuine
      with checkerboard inspection or alpha-channel extraction, not merely
      the `alpha_mode` metadata tag.
- [ ] Import that exact WebM into Filmora on Windows. Place an obviously
      colored video/image behind it. Play and render a short sample. Record
      whether the background shows through throughout the animation and
      transition; attach screenshots or video and the Filmora version.
- [ ] Export H.264 MP4 with an intentionally opaque background and audio;
      confirm dimensions, playback and sound sync in an external player.
- [ ] Test alternate hand assets and scale, painting colors, and a longer
      representative project for regressions or unexpectedly slow preview.

## Review and sign-off

Record each item as PASS, FAIL (with reproduction and logs), or NOT TESTED.
Do not equate GitHub mergeability, passed unit tests, VP9 metadata, or a
CI-built installer with manual Filmora compatibility. Block merging or release
until all release-critical items pass at the **same candidate commit** and the
complete stacked PR changes are reviewed.

- Final CI evidence:
- Manual test evidence and known limitations:
- Blocking failures and linked fixes:
- Reviewer:
- Final decision: **NOT APPROVED** until documented evidence is added.
