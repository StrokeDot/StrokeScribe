# AI resource awareness — experimental.66 candidate

Base: PR22 tested head e88d468936aad708d3aebc30cccf24478a0fb5e1, including integrated .65 at31783a4.
Remote GitHub/Actions only; preserve PR22 branch and .65. No main merge or publication without explicit approval.

1. Resource warning: measure available RAM and selected NVIDIA dedicated free memory off the UI thread; unknown measurements stay unknown. Default advisory limits8GB RAM/2GB VRAM, configurable and disableable. Inline warning allows Continue/Cancel, once per dialog session. Never change model quality or other applications.
2. Stages: preserve PR22 output forwarding and indeterminate loading. Observe prompt-scoped ComfyUI WebSocket events; only recognized sampler progress can produce sampling percentages. Missing monitoring falls back to unknown progress and existing HTTP history polling. Elapsed/inactivity do not infer a crash.
3. Diagnostics: bounded nonblocking queue and bounded lines/files; lifecycle PID/timestamps/exit, stages and elapsed, stdout/errors. Open raw local log or copy sanitized bounded diagnostics; no workflow prompts/config secrets deliberately logged.
4. Regression RED→GREEN, all Windows/Linux workflows, real CPU ComfyUI procedural checks (not model inference), workflow equality and lifecycle. Prepare .66 review artifacts; report unavailable GPU/model testing.

Primary API evidence: official ComfyUI websocket example and pinned v0.41.1 server/execution event code. Preserve render/export/model definitions.
