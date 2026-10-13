# StrokeScribe — Image to Drawing Roadmap

**Status:** Design specification / planned feature. Not implemented yet.
**Priority:** Image import and conversion first; AI-generated new illustrations later.

## User goal

Import an existing PNG, JPG, or similar illustration and produce a **draw-able SVG** whose paths can be animated using StrokeScribe's existing pen-stroke engine. Users must have a choice of three separate conversion methods.

## Three conversion modes (keep all three)

### 1. Automatic — Preserve original drawing

- Try to preserve the original artwork's visual form and line work as faithfully as practical.
- Analyze the image and attempt conversion to SVG suitable for drawing animation.
- Assess suitability (line complexity, overlapping/fill regions, disconnected features, likely path quality), with clear explanations rather than claiming guaranteed accuracy.
- If quality is poor, offer the user mode 2 or mode 3. Do not silently replace the source.

### 2. Stroke reconstruction — Extract pen-like centerlines

- Extract and clean line art, then skeletonize / estimate centerline paths.
- Simplify, smooth, separate at junctions and pen lifts, and heuristically order strokes.
- Let the user preview, reverse or reorder paths, set duration, and correct mistakes.
- Prefer actual drawing trajectories over merely tracing filled outlines.

### 3. AI redraw — Reinterpret as simple line art

- For complicated inputs, offer a **new stroke-friendly interpretation** of the uploaded illustration.
- Optimize for clear outlines and few drawable strokes, not photorealism.
- Explain that the redraw may alter details, proportions, or composition.
- Let the user compare and approve the original and redrawn versions before vectorizing or replacing anything.
- Plan optional backends: a local/open-weight image generator (e.g. ComfyUI with a compatible model), plus an independently billed OpenAI API integration. No API credentials in the repository.

## End-to-end flow

1. Import image. Retain the original untouched.
2. Choose **Automatic**, **Stroke reconstruction**, or **AI redraw**.
3. Present a comparison/preview and warnings for unsuitable images.
4. Produce an SVG with drawable paths and inspect/reorder pen strokes.
5. Preview the handwriting animation using the existing StrokeScribe engine.
6. Export with transparency to PNG sequence and optionally ProRes 4444 MOV.
7. User can try another mode without losing the source.

## Technology candidates, not commitments

- Traditional raster-to-vector outlines: VTracer or equivalent.
- Centerline extraction: OpenCV/scikit-image morphology, skeletonization, contour tracing, path simplification.
- AI preprocessing/redraw: local ComfyUI API with suitable model(s).
- OpenAI image API: optional, separately billed; user's ChatGPT plan is not an automatic API allowance.
- Validate licenses before distributing third-party models/libraries.

## Reverse Engineer Anything (REA)

REA (https://github.com/morluto/rea) is **an optional software-research/development tool**, not an image generator, core library, user-facing feature, or required StrokeScribe dependency.

Where lawful and authorized, developers may use REA with a coding agent to investigate behavior of existing software (e.g., SVG stroke handling, animation ordering, drawing previews) and inform an independent implementation. First prefer standards, open-source source code, libraries, and documented APIs. Do not copy proprietary code, proprietary asset packs, or bypass access controls.

## Initial milestone

Implement an offline, non-AI **PNG/JPG → stroke-oriented SVG** prototype and preview its animation. Support a quality warning when the conversion would look unnatural. Preserve all three modes in the interface/architecture even if some initially show 'coming later'.

**Out of scope for this milestone:** Training an image model, shipping local model weights, automatic perfect reconstruction of human drawing intent, or replacing Filmora.
