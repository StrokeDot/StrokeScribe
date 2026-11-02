# AI resource awareness and diagnostics — experimental.66 review candidate

This dedicated branch includes the already-tested PR22 diagnostics and preserves
experimental.65. Neither .65 nor PR22's branch is overwritten. This candidate is
not published to the installed update channel and must not merge to main or
release without explicit approval.

## Use

Open Create Image and choose your normal Qwen or FLUX workflow. Before generating,
the app checks available system RAM and the first visible NVIDIA GPU's dedicated
free memory in the background. It never closes applications or changes Windows
or model settings. GPU monitoring is optional; missing nvidia-smi, timeouts and
invalid measurements remain unknown.

The initial warning levels are less than8GB available RAM or2GB free GPU memory.
The display uses1024³ bytes per GB, matching the usual Windows memory display.
These are advisory thresholds, not universal model requirements. **Memory limits…**
lets you change or disable warnings and set the no-progress notice interval
(default30seconds). Settings persist between launches.

A low-memory banner offers **Generate anyway** or **Cancel generation**. It appears
at most once per Create Image session unless you deliberately change the warning
settings. Further generations still refresh the measured available memory.

## Accurate activity

Starting engine → preparing input → loading/preparing model → generating
(actual sampler progress) → saving (when reported) → completed/failed.

Execution events are scoped to the submitted prompt and recognized sampler nodes
(KSampler/advanced and SamplerCustom/advanced, including current Qwen and FLUX
graphs). Loader/download stdout percentages never become sampling progress.
If the local event connection is missing, unsupported or disconnects, the app
continues existing HTTP history monitoring with an indeterminate stage rather
than inventing progress. No-progress notices say the owned process is still alive
and may be loading/offloading; they do not diagnose a crash. The elapsed clock
continues. Existing cancellation and owned process cleanup remain in place.

## Logs

Engine log continues showing captured ComfyUI output. The app records lifecycle
PID/start time/exit status, stages, elapsed times and errors. On Windows it
distinguishes the owned launcher PID from the actual ComfyUI child PID.

Persistent logs live in StrokeScribe configuration/logs/ai-engine.log with one
rotated backup, each limited to4MiB. The nonblocking queue holds at most512 items,
limits long lines, and reports omitted lines during overload. The pipe reader
uses bounded reads. Disk failures never stop generation or output draining.
The visible log retains at most1200 text blocks.

**Open log file** opens the local raw log. **Copy diagnostics** copies a bounded
64KiB excerpt with local folders and common credentials redacted, including quoted
JSON/Python dictionary errors and escaped Windows user paths. Review copied text
before sharing; automatic redaction is not a universal secret classifier. Nothing
is uploaded automatically. Model prompts, seeds and workflows are not intentionally
logged by the new diagnostics.

## Verification scope

The Windows/Linux focused workflow exercises resource limits, missing monitoring,
the inline gate, warm reuse/cancellation, actual loopback WebSocket/HTTP event
observation, loading/sampling cancellation, file rotation/privacy, disk failure
and slow writers. It also reruns existing AI, drawer and process lifecycle tests.
The existing full Windows/Linux suites and installer run unchanged plus these tests.

The real CPU ComfyUI check submits two distinct EmptyImage → SaveImage jobs,
verifies execution-event observation, a shared owned PID and final process exit.
These are procedural images, not AI model inference. Remote hosted runners do
not establish real Qwen/FLUX image quality, GPU VRAM behavior or PC responsiveness
under the user's actual installed weights. Model-equipped Windows testing is
still needed for that evidence.

No changes were made to ai_workflows.py, ai_models.py, weights/download choices,
drawing, painting, SVG import, saved projects or video-export engines. The small
websocket-client dependency only observes the local ComfyUI server.

## Manual model-equipped Windows acceptance

1. Cold-start Qwen and FLUX, then generate twice warm. Watch loading with elapsed
   time, real sampling, saving and result. Open Engine log if preparation is slow.
2. Lower the configurable warning limits to avoid a warning, then raise them
   above available memory to exercise Generate anyway/Cancel. Confirm one warning
   per session, unchanged model/seed/quality and unknown GPU values when monitoring
   is unavailable.
3. Cancel during model loading and during sampling; check existing safe close and
   memory-release preference. Unrelated apps must remain running.
4. Copy diagnostics, review redaction, and reopen an existing .65 project to check
   drawing/painting and normal transparent export.

## Installer compatibility

Accurate local progress observation adds websocket-client 1.9.2. Older .65 and
earlier installs therefore require the verified full Windows installer when this
candidate is approved. Their existing source-only updater correctly refuses a
package with changed Python dependencies; this safeguard is preserved and tested
without touching a real installation. No update has been published. The remote
installer job provisions the dependency in its bundled runtime. Source users must
install the candidate requirements in their environment.
