# v0.5.3-experimental.7 — local Ollama analysis repair

The reported empty content with done_reason=length confirms generation reached its limit. It does not by itself prove reasoning consumed the budget. The new diagnostic includes finish reason, eval_count, generation limit and answer/thinking character counts. It never prints image data or reasoning text.

## Changes
- Compact object/part prompt with short names, normalized boxes and drawing order.
- Simple schema, temperature 0, top-level think:false, and a /no_think prompt hint. Neither control guarantees disabling reasoning in a thinking-only model.
- Two attempts maximum. First: 3072 output tokens. Only token exhaustion increases the second budget to 6144; malformed JSON uses the same limit. Retry requests at most four major parts.
- Schema/grammar rejection (HTTP 400/422) retries JSON mode. Other HTTP failures stop immediately.
- Length-stopped or explicitly incomplete responses are rejected, even if a prefix looks valid. JSON in reasoning blocks is never accepted as an answer.
- Network unavailable and timeout messages are distinct. Timeouts are not retried automatically, avoiding overlapping inference.
- 768px analysis thumbnail, fixed 8192-token context, bounded 1MB HTTP response, 180s maximum socket timeout per request and at most two requests. A deadline prevents starting further work after the overall request budget. Socket timeouts are not a guaranteed hard wall-clock kill of inference; Ollama may finish server-side after disconnection.
- One-minute model keep-alive reduces idle residency. These bounds limit workload but cannot guarantee a specific RAM/VRAM use; hardware and model architecture determine memory.
- Semantic extraction must produce real AI-part contours; ordinary detail tracing cannot silently become successful AI Redraw.
- No model download, model switching, paid API or remote inference added.

## Evidence and limits
Official documentation: https://docs.ollama.com/capabilities/thinking
https://docs.ollama.com/capabilities/structured-outputs
https://docs.ollama.com/api/chat
https://docs.ollama.com/modelfile

Ollama documents that think:false requests no thinking only if the model permits it. Qwen3-VL model variants can differ. An upstream report with the same empty-content pattern is https://github.com/ollama/ollama/issues/14798; it is evidence of a possible cause, not proof about this user's installed 4B model.

CI uses mocked protocol responses and real reconstruction code. No real Qwen3-VL inference is claimed. The supplied headset remains a manual model-quality test.
The existing Google Fonts, calibration, animation and export modules are unchanged.

## Manual Windows verification
Extract the entire experimental.7 source ZIP into a fresh folder, run Setup.cmd then Launch.cmd.
Keep Ollama running with the already installed qwen3-vl:4b selected. Import an image, choose AI Redraw and Analyze with local AI.
Check AI-prefixed part names, preview, original colors and transparency. If analysis still fails, copy the complete new diagnostic plus Ollama logs/version and model details from ollama show qwen3-vl:4b. Do not repeatedly retry while Ollama is still busy.
The build cannot promise that a model which ignores no-thinking requests will always finish within the bounded budget.
