# v0.5.3-experimental.8 — Faster AI Redraw iteration

## User-observed bottleneck

Running local Ollama Qwen3-VL 4B on an RTX 4070 Ti SUPER can drive high GPU utilization and remain at the prior unhelpful `0%` indicator while inference runs. User testing finds **Medium** reconstruction detail more useful than Low or High for current illustration examples. Detail controls OpenCV segmentation and outline density; it does not select a larger vision model.

## Improvements

1. **Reuse local semantic analysis in this session.** The image's canonical file path, file size, nanosecond modification timestamp, and chosen Qwen model are the cache key. When the user changes Low/Medium/High or related local brush settings on the same image, the AI's recognized object list and approximate boxes are reused; only contours and brush planning are rebuilt. This does not change the source pixels or guarantee identical SVG traces across details. Importing different images, changing the image file in place, or selecting a different model invalidates the cache. Four latest analyses are retained in memory only, until the app exits. No analysis cache is persisted.
2. **Explicit processing stages.** The footer now shows preparation, active model inference, local contour building, and brush-route planning. Ollama uses an indeterminate progress indicator while the model is busy (rather than pretending that a precise percentage is available) and shows actual elapsed seconds. Other stage percentages are stage milestones, not a measured share of work.
3. **Measurements.** After successful AI Redraw the footer displays elapsed seconds for **Ollama**, **contour reconstruction**, and **brush planning**, allowing targeted future profiling. Cached model analysis is labeled *reused (0s)*. Errors keep their message instead of being replaced by a generic success message if an older image remains in the preview.
4. **Smaller 640px analysis image.** The model input thumbnail is capped at 640 × 640 rather than 768 × 768; original full-quality image pixels still provide the painting output. This can reduce GPU/vision-token workload, but could lose small semantic details and is not guaranteed to improve accuracy for every image.
5. **Medium recommended.** The detail selector still exposes Low/Medium/High; Medium stays the default. The interface explains that detail changes can reuse AI analysis.

## Limits and testing

- The first local AI inference for each image/model **still runs on the user's GPU**; high utilization is expected and need not indicate overheating. The cache improves repeated iteration, not first-run latency.
- Ollama request/retry behavior from experimental.7 remains intact. If a vision response fails before yielding a valid structured analysis, no invalid answer is cached and the error remains visible.
- Models are not downloaded or switched automatically, and no cloud API is involved.
- The local cache reuses only scene-structure metadata and does not store large image pixels.
- CI tests use mocked Qwen replies, real OpenCV contour and brush planning, and UI stage checks. They cannot measure real Ollama latency or GPU load on a Windows workstation. Compare first and repeat analysis times with the same source image and Medium/High detail after installing.

**Release channel:** experimental `feature/ai-redraw-v0.5.3`. Official main v0.5.2 remains unchanged.
