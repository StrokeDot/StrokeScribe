# StrokeScribe — Local AI Redraw (experimental v0.5.3)

**Goal:** A different construction process from Auto Trace and Stroke Reconstruction. A local vision-language model identifies meaningful elements in ordinary artwork—such as a cowboy's hat, face, shirt, hands, and belt—and proposes a logical drawing order. StrokeScribe refines the model's approximate locations into pixel regions, traces named contours, and uses the existing adaptive brush renderer to reveal the unchanged source colors.

This is genuinely **AI-assisted scene analysis**, but the result is still an **approximate reconstruction**, not the real brush history. Pixel masks can be imperfect, especially on complex photographs, overlapping subjects, or soft shading. The AI does not synthesize a new cowboy image or alter the source PNG/JPG.

## Getting started on Windows

1. Download/install [Ollama](https://ollama.com/download) separately and start it. This is **optional**; Auto Trace, Stroke Reconstruction, SVG, and all existing exports continue to work without it.
2. In Windows Terminal, run `ollama pull qwen3-vl:4b` once (approximately **3.3 GB** downloaded). The smaller `qwen3-vl:2b` is about **1.9 GB** and may fit computers with less RAM, but could make less accurate analyses. These are local model files, **not** installed inside StrokeScribe's `.venv`.
3. Launch StrokeScribe normally with `Launch.cmd`; select **Image source**, import a PNG/JPEG/WebP/BMP, choose **AI redraw (local model)**, then select the model and **Analyze with local AI**. First run can take a while depending on CPU/GPU and image complexity.
4. Inspect the **named AI parts** in Stroke Order. Play the draw/paint animation and compare it with Auto Trace on the same image. Keep **Preserve original colors** enabled to paint the exact imported image.

## Privacy and cost

This experimental mode connects only to **http://127.0.0.1:11434/api/chat**, the local Ollama server, through Python's standard HTTP library. No OpenAI API, AI subscription or cloud image upload is needed by StrokeScribe. It doesn't automatically download models or contact a cloud endpoint. You are responsible for installing Ollama and choosing its local model. Please use local model tags, not cloud tags.

The selected image is scaled to at most 1024 px for analysis and sent to Ollama on the same computer. Full image pixels stay within StrokeScribe and are used for output.

## Technical implementation

- `semantic_redraw.py` requests structured JSON: scene description, part names, normalized bounding boxes, and proposed draw order.
- Validates names, rectangle coordinates, scene part count and model name; errors are shown to the user rather than quietly reverting to ordinary Auto Trace.
- Uses OpenCV GrabCut to refine broad boxes to pixel regions; falls back to existing color segmentation on problematic regions.
- Generates visible strokes with meaningful labels (for example `AI 02 / cowboy hat`) followed by fine details. Brush strokes follow semantic paint-region priorities. Remaining color pixels are still included.
- Uses original image bytes for final color rendering; unrelated drawing modes and exports are not changed.

## Current limitations

- The vision model is optional and **must run locally**; CI uses simulated model answers, not a real local AI model.
- AI bounding boxes are approximate, and OpenCV color-based segmentation cannot reliably discover every true object boundary. Some overlapping parts or fine details may be drawn in the wrong order; model hallucinations and mislabeled parts are possible.
- AI Redraw currently changes the **stroke planning and region ordering**, but doesn't generate a new stylized source image. A future image generator or segmentation model could add that separately.
- A true manual mask/region editor is not yet built. For a given complex illustration, traditional Auto Trace can still look better.
- Model downloads and CPU/GPU use can be substantial. This is not a one-click built-in neural network.
- The preview/export are still deterministic and use the standard transparent PNG/WebM/ProRes workflows.

**Development:** Run CI on Linux and Windows Python 3.14. The `test_ai_redraw.py` suite mocks local model responses so tests don't need an actual AI server. The final visual comparison on your cowboy artwork must be carried out manually.

**Stability:** Based on official v0.5.2. Work is isolated on `feature/ai-redraw-v0.5.3`, not merged.
