# StrokeScribe v0.5.3 experimental.58 — Phase 0 reference

- **Pinned baseline:** `cd4ff3d298f9653239de45e447b84fa4c9249d80` on `fix/svg-guide-coverage-experimental12`.
- **Protected stable release:** `main` / v0.5.2, not modified by this sprint.
- **Work branch:** `safety/stability-sprint-phase0-phase1`; draft PR #5.
- **Cross-platform baseline CI:** the reference revision had successful **Image source reconstruction review** (Linux and Windows Python 3.14), **Adaptive painting**, **AI engine**, and **UI preview** checks on October 17, 2026.
- **Fixture contracts:** `test_svg_guide_cleanup.svg_fixture` has a transparent RGBA illustration with a true dark source line and misregistered temporary SVG outlines. `test_contour_transitions.fixture` is the reference for source-image animation.
- **Characterization:** `test_stability_baseline.py` checks that four SVG painting modes and both image animation modes finish with exactly the original PNG pixels (at source-aligned 320×240 dimensions), and start with a transparent image animation canvas. The more detailed existing tests check progressively disappearing guides, hand scale, and 25/50/75/100% frames.
- **Image tolerance:** final-frame source colors/alpha are byte-exact; intermediate antialiasing varies with Qt/backend and is tested geometrically rather than frozen to brittle SHA-256 raster hashes.
- **No production renderer changes are planned during Phase 0–1.** The full existing suite remains the guardrail.
- **Manual acceptance still needed:** Windows installer start/quit; save/discard/cancel on current project and changing projects; test export (PNG alpha / ProRes / VP9); representative white headset and vintage TV pair. Linux CI cannot establish Filmora compatibility.
