# HANDOFF-002
Date: 2026-11-26 · Written by: HENRY II · Previous: HANDOFF-001

## Current state
- App unchanged: 1.0.1-experimental.71. Dev branch at `4d1ffee` when this started.
- D:\Programs\StrokeScribe (the installed app) is now also the git checkout of
  StrokeDot/StrokeScribe, on the dev branch. Every installed file matched the
  repo exactly; nothing was changed or deleted to set it up.
- This setup is on branch `docs/henry-rules` with a PR against the dev branch.
  Merging it is the owner's call.

## What I did this session
- `git init` in the app folder, fetched the repo, and pointed it at the dev branch
  with `git reset --mixed`, so no file was touched. Restored `.github/` (the updater
  never copies it).
- `.git/info/exclude` (this PC only, not committed) ignores the installed-app files:
  `StrokeScribe.exe`, `unins000.*`, `runtime/`, `Images/`, `_previous_version/`, and
  leftovers. Those are the sound files removed from the app after exp.6 (the updater
  doesn't delete removed files) and the Windows-host files from the 21 Oct installer
  (branch `test/experimental75-native-blending-preview`).
- Added AGENTS.md (shared rules plus StrokeScribe's own rules and how-to), CLAUDE.md,
  and the handoffs/ chain. HANDOFF.md moved unchanged to handoffs/HANDOFF-001.md.

## Decisions made
- The old rule "update HANDOFF.md in the repo and the copy in
  `Documents\StrokeScribe Projects\HANDOFF.md`, and send it at task start" is replaced
  by the numbered handoff chain. The copy in Documents was left as it is.
- The owner's StrokeScribe rules moved from the handoff into AGENTS.md, where every AI
  reads them first. The technical notes stay in HANDOFF-001.
- Changes are made and tested locally first. The in-app updater must not be used while
  this folder has uncommitted changes, because it would overwrite them.

## Open problems
1. Still open from HANDOFF-001: "Through / Near the corner" sticker options, resting
   hand missing in the "This element" preview, action logging (needs the owner's OK).
2. ~20 older open PRs (experimental67–75, safety/*) were never reviewed.

## Next steps
1. Owner reviews and merges (or not) the rules PR.
2. Wait for the owner's feedback on exp.70 (hand timing and Edit path).

## Key files
- `AGENTS.md`, `handoffs/`, `.git/info/exclude` (local)
