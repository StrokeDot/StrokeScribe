# Candidate .65 AI engine lifecycle

The Create Image window keeps its owned ComfyUI server warm across repeated
successful generations and recoverable workflow errors. The default-on
**Release AI memory when I close Create Image** preference is saved in
ai_engine.json. Unchecking it retains the server between dialog sessions.
The application still explicitly stops its engine on application shutdown.

Every genuine dialog exit (title-bar Close, Escape/reject, accept, direct done,
and use-result acceptance) checks both generation/install/download workers and
live model workers. Neither isRunning() becoming false nor finished() alone
proves native QThread cleanup is complete; wait(0) must also succeed. An attempted
exit requests cancellation and leaves the dialog open for a later close.
Escape that only closes the updates drawer keeps the dialog and server alive.
Use-result delivery waits for this same safeguard, preserving the original and
line-guide pairing captured by experimental.64.

The engine owns one process launch and its output reader. Readers capture their
specific process instead of following mutable self.proc. Start and stop are
serialized; stopping waits the root, joins the reader and closes its stdout
before clearing ownership. Failed cleanup retains ownership so it can be retried.

On Windows, an anonymous Job Object has KILL_ON_JOB_CLOSE. A Python launcher
waits for a one-byte stdin gate; the parent assigns it to the job before opening
that gate. Only then can it spawn ComfyUI. Descendants inherit the job, and the
job remains usable after the original server/root exits. Shutdown terminates
only the owned job, waits the launcher and observes ActiveProcesses reaching
zero before closing the handle. No executable-name or port-based killing occurs.
There is no fallback to an uncontained process when job assignment fails.

On Linux/POSIX, the server starts in a new session/process group. Stop signals
that exact group, escalates TERM to KILL after a bounded grace interval and
waits the root. This handles children retaining memory after their parent exits;
as with ordinary process-group containment, deliberately escaping into a new
session is outside this boundary. The local engine does not request such an escape.

## Verification and limits

test_owned_process.py launches actual CPU parent/child/grandchild processes,
each allocating and touching 12 MiB, measures their resident memory, stops the
owned tree and verifies those exact processes have exited. An unrelated Python
sentinel must remain alive. Coverage includes children ignoring TERM on Linux,
an original root exiting first, and repeated stop/restart ownership.

test_source_ai_lifecycle.py runs Engine against a real local CPU HTTP fixture.
It verifies two requests share one server PID, all exit routes release the owned
tree, opt-out persists across reopened dialogs, and readers finish on restart.
It also covers active QThreads and the native cleanup interval for both worker
types. The process fixture is deliberately isolated from ComfyUI and model files.

The optional tools/verify_comfy_lifecycle.py runs real installed ComfyUI on CPU
and submits two EmptyImage -> SaveImage workflows through the real Engine.
It records stable process identity, per-process RSS and completed shutdown.
Those are procedural image jobs, not model inference. It requires ComfyUI's
installed dependencies and psutil, and writes samples/source-editing/comfy-lifecycle.json.

These checks prove process ownership, warming and release of process memory.
They do not establish real AI weight loading, inference quality, CUDA VRAM
recovery or performance with multi-gigabyte models. A model-equipped Windows
machine is still needed for that acceptance evidence.
