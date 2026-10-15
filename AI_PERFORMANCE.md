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

## v0.5.3-experimental.9 — Balanced processing profile (default)

The **AI Processing** selector is visible only in Image Source → AI Redraw. It offers three functioning processing profiles while keeping the separate Low/Medium/High contour **Detail** selector. The default is **Balanced + Medium detail**, based on observed results.

| Profile | Vision thumbnail | Suggested AI parts | OpenCV segmentation | Model stays warm |
| --- | --- | --- | --- | --- |
| Fast | up to 448px | up to 4 | cropped local GrabCut ROI, 2 iterations | 2 minutes |
| **Balanced** | **up to 640px** | **up to 8** | **cropped local GrabCut ROI, 3 iterations** | **5 minutes** |
| Quality | up to 896px | up to 12 | previous full-frame GrabCut, 3 iterations | 10 minutes |

Balanced preserves experimental.8's 640px recognition resolution and eight-part prompt. The main improvement is less repeated OpenCV work for each semantic object: cropped image regions around model-proposed boxes are processed instead of applying full-frame GrabCut for every object. It also extends Ollama's model keep-alive from 1 to 5 minutes to reduce reloading between successive different images. Keeping Qwen warm can retain its VRAM allocation longer; no model weights are duplicated, and no new model is downloaded.

A model's prompt, input size and contour segmentation can affect visual quality, even at identical Detail settings. **Profiles aren't guaranteed to rank by quality on every image.** Each image and model's cached recognition is keyed by profile as well, preventing stale cross-profile reuse. Changing only Detail retains the model analysis for that profile.

### Performance evidence and limits

The test suite validates each profile's exact local request settings, segmentation method, scene caching, unchanged Auto Trace and Stroke Reconstruction modes, and preservation of original colored pixels. GitHub Actions additionally runs `benchmark_ai_profiles.py`: a *CPU-only* synthetic image benchmark of local OpenCV segmentation using the same illustration and parts for Balanced vs Quality. The measured absolute seconds and ratio can vary by runner; no speed guarantee or fabricated GPU benchmark is made.

**Real Qwen3-VL 4B performance on the user's RTX 4070 Ti SUPER must be measured in StrokeScribe's status footer.** First-run model inference may still be lengthy, and keep-alive is intended to improve repeated analyses of different images rather than magically speeding one prediction. Analysis remains local; this release does not change fonts, hand calibration, SVG, color exports or the official v0.5.2.
