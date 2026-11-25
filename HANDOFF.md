# StrokeScribe — Handoff

Last updated: 2026-11-25. Current version: **1.0.1-experimental.71** (Prototype channel).

**Keep this file current (the owner's rule):** after every change, update HANDOFF.md in the repo
(same PR as the change) and the copy on the owner's PC (`Documents\StrokeScribe Projects\HANDOFF.md`),
and send it to the owner when a new task starts. If you see an error, fix it.

## What it is

StrokeScribe is a Windows desktop app (Python 3.12 + PySide6) that makes whiteboard-style
"drawing hand" videos from SVG/artwork. Elements (drawings, texts, pictures, stickers, resting
hands, camera steps) sit on a timeline; a hand draws them and the result is exported as video.
It has a built-in updater: new versions install from inside the app (Help → updates).

## Current state

- Dev branch: `fix/svg-guide-coverage-experimental12`. It is what the in-app updater reads,
  so every merge to it is effectively a release to the owner.
- exp.56–71 are merged (PRs #273–#289). Recent work, newest first:
  - exp.71: Quick checks green again. Picking a "Goes out" mode now un-greys the Exit settings;
    stale tests updated (card times live in the tooltip since exp.66; Move in must be on before
    its button works); `test_line_order` cleans up Qt windows so Windows doesn't crash at exit.
  - exp.70: sticker hand timing goes to the right; Edit path uses the sticker's own page;
    a camera move that starts during a Hand motion ends the hand's parking.
  - exp.69: `WheelGuard` (the mouse wheel only changes a control you clicked first);
    clearer wording ("Back to its corner (and waits there)", "Hand way in and back…").
  - exp.68: resting hands (a second, still hand; photo picked from the computer; under/over layer).
  - exp.67: sticker animation and hand in sync. exp.66: compact element strip.
  - exp.65: hand menus agree with each other. Earlier: copy/paste, camera step, rotation,
    sticker window, shadows.
- No open PRs from this work. The ~20 older open PRs (experimental67–75, safety/*) predate it
  and were not touched.

## Decisions made (keep these)

**The owner's rules**
- Be careful with changes: "I like how the program is running right now."
- Fix the underlying principle, so it can't happen in any scenario, not just the one case shown.
- No automatic behaviour the owner didn't ask for. When unsure, ask.
- Every panel section is closed by default.
- Any adjuster with a gradual bar (slider or number box) must be selected before the wheel moves it.
- Explain every option in the UI with a short line. Don't invent new jargon.

**Workflow and safety**
- Never install WSL, change system settings, run remote install scripts, or spend tokens on
  keep-warm pings without approval.
- The repo is public: never commit the owner's artwork, photos or projects.

**Technical decisions**
- Sticker timing (exp.70): with a hand, the clip starts when the hand starts moving.
  `stickers.draw_start(item)` = start + way-in seconds.
  - Stickers from before exp.70 lack `clip_v2`. `stickers.migrate()` moves their clip earlier
    when the project opens, so they draw at the same second as before.
  - Always use `draw_start` for "when is it drawn", never `item['start']`.
- The writing hand is always drawn last (on top). Resting hands: under = -1e6, over = +1e6
  in `rest_hands.layer_key`.
- Hand-motion parking ends at the next hand start or camera move
  (`camera_clips.parked_until` / `parked_glide`); the hand glides back to its corner.
- Stickers on a non-sequential (track) layout are drawn inside the whole-video frame.
  `titles_split` returns `([], shown)` in that case.

## Open problems

1. **Watch Quick checks after each merge.** On a push it runs every test, not only the ones for
   the changed files. It had been failing for weeks (fixed in exp.71) without blocking merges,
   because the PR run only picks tests for the changed files.
2. **"Through / Near the corner"** options for sticker hands are not done
   (finding 5 of the menus audit).
3. The **resting hand** is not shown in the "This element" preview of multi-element projects.
4. The **log** (`applog.py`) records errors but few user actions. A few code paths swallow
   errors silently (`except Exception: pass`). Proposed but not approved: log the main actions
   ("breadcrumbs") and route swallowed errors to the log.
5. `app.py` (~9.5k lines) and `studio_workspace.py` (~5k lines) are very large; edit carefully.

## Next steps

1. Wait for the owner's feedback on exp.70 (hand timing and Edit path) in the real app.
2. Confirm Quick checks passes on the dev branch after the exp.71 merge (open problem 1).
3. Ask whether to add action logging (open problem 4).
4. Through / Near the corner for stickers.

## How to work on it

**Setup**
- Clone, then create a venv with `python3.12 -m venv venv`
  (Python 3.13 breaks `svgelements`) and run `pip install -r requirements.txt`.

**Run tests (headless)**
```
export STROKESCRIBE_TEST_AUTODISCARD=1 QT_QPA_PLATFORM=offscreen
venv/bin/python -m unittest test_hand_timing test_sticker_hand ...
```
- Run modules one at a time or a few at a time; one big run can exceed time limits.
- Prove a new test catches the bug: `git stash push <changed source files>`, run the test
  (it must fail), then `git stash pop`. Never stash the test file itself.

**Shipping a version**
1. Branch `proto/1.0.1-expN` from `origin/fix/svg-guide-coverage-experimental12`.
2. Bump `APP_VERSION` in `version.py`.
3. Add a README section above the previous top one.
4. Add new test modules to the test chain in `.github/workflows/image-source.yml` and
   `windows-installer.yml` (2 occurrences each).
5. Push and open the PR against the dev branch (REST API; `gh pr view` / GraphQL is blocked).
6. When all checks pass, squash-merge.

**Merge conflicts**
- PRs are squash-merged, so a branch made before the previous PR merged will conflict on
  `version.py`, `README.md` and the workflows. Merge the base and keep this branch's side,
  then check `git diff --stat origin/<base> HEAD` shows only this version's changes.

**Windows-only crash at exit**
- Windows CI can crash with an access violation at exit after all tests passed, when Qt dialogs
  stay alive. Fix: `deleteLater()` on dialogs plus a `tearDownModule` that sends DeferredDelete.

**Logs (on the owner's PC)**
- `%APPDATA%\StrokeScribe\logs\strokescribe.log`; also `startup.log` (start steps and hard
  crashes) and `ai-engine.log`.
- Help → "Copy the log (for a bug report)" copies the last 300 lines.

## Key files

| File | What it holds |
|---|---|
| `app.py` | Main window: timeline, preview, sticker/hand/camera logic, dialogs (sticker window, Edit path) |
| `studio_workspace.py` | Studio layout: panels, element strip, Camera tab, `WheelGuard`, `CopyKeys` |
| `menus.py` | Menu bar (Help → log actions, updates) |
| `stickers.py` | Sticker model: `new`, `draw_start`, `migrate`, `busy`, `ways`, `phases`, `hand_tip`, `pen_point` |
| `sticker_art.py` | Drawing of the rich stickers (Clock, Marker ellipse…), `pen_at` |
| `sticker_dialog.py`, `sticker_panel.py` | Sticker window and side panel |
| `rest_hands.py` | Resting hands and their layer order |
| `camera_clips.py`, `camera.py`, `scenes.py` | Camera steps, Hand-motion parking/glide, scenes and export hand starts |
| `frame_render.py`, `timeline_render.py` | Frame drawing: hand motion, track layering |
| `overlays.py` | Texts/pictures/stickers drawing: rotation, flip, shadow |
| `clipboard_edit.py` | Ctrl+C / Ctrl+V for elements, the whole video, the board |
| `applog.py`, `startup.py` | Logging, error hook, startup log and crash dump |
| `updater.py`, `update_dialog.py` | In-app updater |
| `version.py` | `APP_VERSION`, `RELEASE_CHANNEL` |
| `.github/workflows/` | CI; `image-source.yml` and `windows-installer.yml` hold the test chain |
| `test_*.py` | One module per feature/fix (e.g. `test_hand_timing`, `test_wheel_and_words`) |
