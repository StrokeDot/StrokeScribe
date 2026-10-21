# Windows identity and project files — experimental.74 candidate

This candidate keeps the existing editor, Python packages, project format and
animation/export engines. It adds a small native Windows GUI host which embeds
the private CPython runtime in the real `StrokeScribe.exe` process. It does not
rename Python or freeze the editor into a second application architecture.

## Installation and everyday use

The first installation of this change requires the **full Windows installer**
from this PR's validated build artifact. A source-only in-app update cannot
create the executable or register Windows file associations. This candidate is
not a published update and has not been merged into main or the update branch.

1. Save your work and close StrokeScribe.
2. Run the candidate installer for the same Windows account and install folder.
   The usual settings, Library and separately installed AI engine/models remain
   in their existing locations. Keep personal projects outside the application
   installation directory, as with the existing installer.
3. Start **StrokeScribe** from the Start menu. If an old taskbar pin still points
   to Python, unpin it and pin the new Start menu entry.
4. Double-click an existing `.strokescribe` project. A running installed window
   receives the file; unsaved work still uses Save / Discard / Cancel. A busy
   export or reconstruction and an active modal dialog delay the request until
   it can be handled safely.
5. If another application is already the Windows default, choose StrokeScribe
   through **Open with → Choose another app** or Windows Default apps. The
   installer registers availability without overriding that choice.

Explorer uses the existing official multi-resolution ICO and the file type
**StrokeScribe Project**. File contents and the extension are unchanged.
Windows may retain an old icon in its cache until Explorer refreshes or the
desktop session restarts. Development launches through Python can still appear
as Python; render workers and separate AI processes may also legitimately show
their own interpreter process. The installed main editor is StrokeScribe.exe.

## Safety and updates

- File registration is per-user. The installer owns its ProgID, Open with entry,
  application capabilities and command. It never edits Windows UserChoice.
- An existing unrelated default is preserved on installation, repair and
  uninstall. Uninstall removes the extension default only if it still belongs
  to StrokeScribe, and removes StrokeScribe's own registrations.
- Project paths travel as Unicode arguments and bounded local JSON requests;
  they are never inserted into a command shell.
- A current-user/install native mutex elects the main instance before Python
  starts. A secondary launch never performs interrupted-update recovery.
- The primary recovers interrupted updates before loading the GUI/render code.
  Normal in-app restart waits for the old native process and local broker to
  close before the replacement claims them.
- The private interpreter remains `runtime/pythonw.exe` for Python subprocess
  and multiprocessing compatibility. Source updates preserve the installed
  native host; its file-version metadata identifies the installed host build,
  while the application's visible version identifies the current source build.
  A later change to native code itself requires another full installer.

## Verification and remaining manual acceptance

The PR adds Windows/Linux project routing and IPC tests, including Unicode paths,
unsaved-work cancellation, failed Save, recovery preservation, SVG arguments,
malformed projects, a second launch during a live update transaction and restart
selection. Existing regression suites remain required.

The disposable GitHub Windows runner builds and installs the candidate, checks
real PE version metadata and process identity, queries the Shell's project type
and icon, opens files through the same Shell API used by Explorer, checks a
second request reaches the existing process, verifies a modal dialog delays the
request and Cancel retains unsaved work, and checks registration repair and
uninstall behavior. A temporary installed-host harness exercises real parallel
PNG export, alpha pixels, a real AI-library subprocess and native restart.
It does **not** run Qwen/FLUX model inference or download model weights.

The runner verifies Windows API behavior; it does not visually operate Task
Manager or a user's desktop. Manually check Task Manager's friendly label, the
window/taskbar/Alt-Tab icons, Explorer's icon appearance after a desktop refresh,
and double-clicking a project while an unsaved document or modal dialog is open.
The user's installed app and personal files are not accessed by these tests.
