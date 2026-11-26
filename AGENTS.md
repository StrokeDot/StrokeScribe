Written by: HENRY II · Date: 2026-11-26
Synced from RULES.md: 2026-11-26 by sync-rules.ps1

# Shared rules for all my AIs (all projects)
Master copy: D:\Programs\AI RECORDS\RULES.md. Each project's AGENTS.md carries a copy
of this file plus a short project section at the bottom. When this file changes,
run sync-rules.ps1 (next to this file) to update every project's copy.

## Who is who
Four AIs work on my projects and hand work to each other:
- HENRY I   = OpenAI
- HENRY II  = Claude
- HENRY III = DeepSeek
- HENRY IV  = Google Antigravity
Any of them may continue work another one started. Sign your work with your Henry name.

## Where things live
- Every app has ONE project folder. Its source code lives there and only there.
- Work locally first: make and test changes in that folder on this PC before anything
  goes to GitHub. When possible the app's own folder is also its git checkout (for
  example StrokeScribe), so what I test is exactly what will be pushed.
- If the project has a GitHub repo, GitHub `main` is the shared copy. Some AIs only
  see GitHub, so work committed only on this PC is invisible to them and can be
  overwritten. Pull before you start. Push only after I have tested and said OK
  (see "Testing and updating GitHub").
- Every project folder has a `handoffs/` folder holding the shared handoff chain.
- D:\Programs\AI RECORDS\HENRY ... holds each AI's own notes. No project code there.

## Handoff chain
- One file per work session, numbered with three digits:
  handoffs/HANDOFF-001.md, HANDOFF-002.md, HANDOFF-003.md ...
- Never edit or delete an older handoff. Always add a new one.
- Each handoff is under ~150 lines and starts with:
    # HANDOFF-00N
    Date: YYYY-MM-DD · Written by: HENRY __ · Previous: HANDOFF-00(N-1)
  Sections: What I did (exact files) · Current state · Decisions and why ·
  Open problems · Next steps (in order) · Key files.
- Write it before the session ends, or as soon as you're near a usage limit.
  Mark unfinished work as unfinished.

## Starting a session
1. Pull from GitHub if there is a repo. Check the newest handoff for "NOT PUSHED"
   work on this PC and keep it — never overwrite or discard it.
2. Read ONLY the newest handoff. Go back through "Previous:" only if you need more.
3. Tell me in 2–3 lines where things stand before working.
4. No handoffs/ folder yet? Create HANDOFF-001.md describing the current state first.

## Signing files
- Every .md file you create starts with: `Written by: HENRY __ · Date: YYYY-MM-DD`
- Editing someone else's .md (never a handoff): add under the signature
  `Updated by: HENRY __ · Date: YYYY-MM-DD · What changed: <one line>`

## Version control
- No git repo? `git init` and commit a baseline before changing anything.
- Commit messages start with your Henry name: "HENRY II: fix double lock in render loop".
- List commit hashes in your handoff.
- Never push to GitHub (main or release) or publish a release without my OK.
- Never commit keys, passwords or tokens.

## Testing and updating GitHub (all Henrys)
Who tests depends on the change. Say up front which case you're using, so I know
what you will and won't check.

| Kind of change | Who tests | How |
|---|---|---|
| Every change | You | It builds and the existing automated tests pass. Seconds, no window. |
| Hidden logic (counting, detecting, saving data) | You | Add a small automated test for the new logic. No window. |
| Startup crash, or a fix for a crash | You, after asking me | One short launch (max ~30 s), read the log, close it. Ask first: "May I start it once to check X?" |
| Anything I see or feel (looks, menus, controller, speed, games, FPS) | Me | You install it without starting it and tell me in a few lines what to try. |

Always:
- Never force-close an app or emulator that may be running — I might be using it.
  If it's in the way, ask me to close it.
- Never test with my real saves or settings; use a separate copy.
- No repeated launch loops: at most one launch per change, and only with my OK.
- No big new test suites or automated click-throughs unless I ask.

Remember it:
- When I settle who tests a case, save that in your own memory (or in your notes
  folder in AI RECORDS if your app has no memory), so you don't ask me again.

PC apps vs Android apps:
- PC apps: the app is tested locally on this PC. GitHub gets updated later, when I
  decide. Don't spend time or tokens on GitHub (pushing, CI checks, releases) until
  I ask.
- Android apps: the same testing table applies, but getting the app onto my phone
  works differently:
  1. Phone connected by USB (`adb devices` lists it): build the APK and install it
     with `adb install -r` (keeps the app's data). No GitHub needed, same as a PC app.
  2. No USB: ask me to plug the phone in. Only if I say no, the update goes through
     GitHub (a release my phone's in-app updater picks up), and that needs my OK
     like any release.
  3. Never uninstall the app on my phone (that deletes its data). If the install
     fails (for example, a different signature), stop and ask me.

Then:
1. I test it and decide. Only after my OK is the work pushed to GitHub, and a
   release is made only if I ask for one.
2. If the session ends before my OK, write in the handoff, at the top of "Current
   state": `NOT PUSHED: <commit hashes>` so the next Henry knows the work exists
   only on this PC.

## Sub-agents and token use (all Henrys)
- A sub-agent (helper, worker, parallel agent) uses the SAME model and the SAME
  reasoning level as the session I started. Never move a sub-agent to a bigger model
  or a higher reasoning level on your own. Only go higher if I ask for it.
- HENRY I (OpenAI): this rule is mandatory. Do not default sub-agents to the highest
  model or reasoning setting.
- Use sub-agents only when they save real work (wide searches, independent pieces).
  Small tasks are done directly.
- Give each sub-agent a short, focused brief and ask for a short answer.

## Cache and context (same for every Henry)
- Every session starts the same way: rules (AGENTS.md / CLAUDE.md), then the newest
  handoff. A fixed, unchanged start lets each app reuse its cache instead of paying
  for the same text again.
- Don't change the rules files in the middle of a session. Collect rule changes and
  make them at once.
- Read only what the task needs: search first, then read the relevant part of a file,
  not whole folders. Don't re-read a file you just read or wrote.
- Keep long outputs (logs, test runs, big files) out of the conversation: show only
  the lines that matter.
- When a session gets very long, write the handoff and start a fresh session instead
  of carrying a huge context.
- Per-app notes: HENRY III (DeepSeek) and HENRY IV (Antigravity): no extra rules yet;
  the rules above apply. Add notes here when we learn how each app caches.

---

# How we build

## Programming principles
- **Keep it simple (KISS).** The simplest solution that fully works wins.
- **You aren't gonna need it (YAGNI).** Build what is asked now, not what might be asked later.
- **Don't repeat yourself (DRY) / single source of truth.** Each fact, setting or piece
  of logic lives in one place.
- **Separation of concerns.** Each file or module has one clear job.
- **Least astonishment.** Code and app behave the way a reader or user expects.
- **Fail fast and loudly in development, gracefully for the user.** Errors are never
  swallowed silently; the user sees a plain message that says what to do.
- **Minimal change.** Touch only what the task needs; no drive-by rewrites.

## Storage: use only what's needed
- Don't ship or keep unused files, assets or dependencies.
- Images are stored at the size they are shown, in an efficient format.
- Every cache has a size limit and cleans itself up. Backups are bounded (keep the last few).
- Data is stored once, not copied into several places.
- Saving space must not make the app noticeably slower. When in doubt, measure.
- Note the app's install size and data size in the handoff when they change noticeably.

## Speed: as fast as possible for the resources used
- The window appears first; heavy work (scans, downloads) runs in the background.
- Never block the UI. Inputs respond immediately.
- Do work once and reuse it: cache results, only redo what changed.
- CPU, memory and GPU use stay proportional to what the user is doing; idle means idle.
- Measure before and after optimizing. Keep a change only if it measurably helps.

## Easy to use
- Fewest steps to do the common thing. Detect automatically instead of asking.
- Sensible defaults; settings exist for overrides, not for basic use.
- Plain words in the UI. No jargon, no error codes without an explanation.
- Never lose the user's data: migrate old data on updates, back it up before risky changes.
- Destructive actions ask first or can be undone.
- Works with every input the app supports (mouse, keyboard, controller, touch).

## Visually appealing
- One consistent look: same spacing, fonts, colors and corner styles everywhere.
- Clear hierarchy: the most important thing on a screen is the most visible.
- Readable at the distance it's used from (e.g. a TV across the room).
- Motion is short, smooth and has a purpose; it must never cost performance.
- Polish matters: alignment, empty states, loading states, icons.

## Apps I build
- Always include an in-app updater, so new versions install from inside the app.

## Working style
- Don't trust a handoff blindly: check it against the code.
- Before changing work that another AI or I left half-finished, report what you
  found and wait for my OK.
- Ask before deleting files or doing anything that can't be undone.
- When principles conflict (e.g. smaller vs faster), say which you chose and why
  in the handoff.

---

# This project: StrokeScribe (whiteboard "drawing hand" video maker)
**Where the code lives**
- Folder: D:\Programs\StrokeScribe. This is BOTH my installed app AND the git
  checkout. Make changes here, locally, first; I test them here with `Launch.cmd`.
- Repo: StrokeDot/StrokeScribe (public). Dev branch:
  `fix/svg-guide-coverage-experimental12`. The in-app updater reads that branch, so
  every merge into it is a release to me: merge only with my OK.
- Work on a branch `proto/1.0.1-expN` made from the dev branch. Push it and open the PR
  only when I say so (after I've tested locally).
- Don't use the in-app updater (Help → updates) while there are uncommitted changes
  here: it would overwrite them. Get new versions with `git pull` instead.
- Files only on this PC are ignored through `.git/info/exclude` (installer files,
  `runtime/`, `Images/`, leftovers). Never commit them.

**My rules for this app**
- Be careful with changes: "I like how the program is running right now."
- Fix the underlying principle, so it can't happen in any scenario, not just the case shown.
- No automatic behaviour I didn't ask for. When unsure, ask.
- Every panel section is closed by default.
- Any adjuster with a gradual bar (slider or number box) must be selected before the
  mouse wheel moves it.
- Explain every option in the UI with a short line. Don't invent new jargon.
- Never install WSL, change system settings, run remote install scripts, or spend
  tokens on keep-warm pings without approval.
- The repo is public: never commit my artwork, photos or projects.

**How to work on it**
- Python 3.12 only (3.13 breaks `svgelements`). On this PC `Setup.cmd` makes the
  environment; `Launch.cmd` starts the app from this folder.
- Automated tests (no window): set `STROKESCRIBE_TEST_AUTODISCARD=1` and
  `QT_QPA_PLATFORM=offscreen`, then `python -m unittest test_<name>`, a few modules
  at a time.
- Shipping a version (after my OK): bump `APP_VERSION` in `version.py`, add a README
  section above the previous top one, add new test modules to the test chain in
  `.github/workflows/image-source.yml` and `windows-installer.yml` (2 places each),
  push, open the PR against the dev branch, squash-merge when checks pass.
- More technical notes (sticker timing, hand layers, merge conflicts, Windows exit
  crash, logs, key files): handoffs/HANDOFF-001.md.
