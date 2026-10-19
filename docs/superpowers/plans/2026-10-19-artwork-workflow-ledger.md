# Artwork workflow execution ledger

- Baseline: experimental.63 at 36259c067c85890a242f5423cf24bdce77f51f92.
- Spec: docs/superpowers/specs/2026-10-19-artwork-workflow-draw-paint-design.md.
- User approved the design and explicitly delegated remaining implementation judgment; no repeated plan-approval pause.
- Execution method: inline, with a fresh whole-branch review before delivery.
- Release gate: no main merge and no published update without separate user release approval.
- Ruling: preserve additive project format 1 fields and immutable source bytes; raster intake uses explicit 64 MiB / 16 million pixel bounds — avoids unbounded embedded sources; unusually large assets are rejected clearly.
- Plan self-review: shared signatures consistent; placement, pairing, SVG appearance, persistence, rendering and CI acceptance all have owning tasks. No runtime changes yet.

- Task 1 RED: run39233729114 job117997639953 — all four new asset tests failed because durable storage is absent; existing19 policy/SVG tests passed.

- Ruling: during staged implementation, scope full-suite jobs off this feature branch only; artwork-focused CI remains active. Restore original workflows before final validation. This reduces redundant heavy runs; no final check is waived.

- Task 2 diagnostics: placement assertions passed, but three teardown errors exposed queued fill_scenes callbacks touching a deleted QListWidget after close. Added an accepted-close guard; no errors are suppressed while the window is active. The fixture now restores environment even on errors.

- Task 1/2 GREEN: run39235908173, Windows job118004790795 and Linux118004791199: all29 tests passed with normal exits. Includes all placement transactions, cancelled asynchronous completion, empty clean New Project, and existing SVG/policy checks.
- Task 3 start: add pairing/Library/project/mode/guide-framing regressions before implementation.
- Ruling: align durable raster intake with the existing reconstruction limit of24 million pixels instead of tightening it to16 million; preserve supported user artwork. Source bytes remain bounded at64 MiB. A regression checks existing16–24 MP inputs.

- Task 3 RED: Linux job118005526404 reproduced lost AI kind/original, missing Library pairing, missing project metadata, absent Drawing only and unrecorded portrait-guide framing. The additional compatibility test correctly rejected16–24 MP input under the temporary16 MP cap.
- Ruling: ask destructive-placement confirmation before preparation, and re-confirm only if edits occur during preparation. This preserves the existing cancellation-before-builder contract while preventing stale save decisions from discarding later edits.

- Task 3 GREEN: run39236419454 Windows118006469738/Linux118006469358: all35 focused tests passed. Pairing survives Library migration and external removal; the Add-AI result kind/original, old projects, Drawing only/Paint Only, portrait guide framing and24 MP compatibility are covered.
- Task 4 start: reproduce native filled SVG loss, coordinate frames, resource/size limits, cache bounds; additionally cover existing same-page placement semantics before integrating.

- Task 4 RED: run39236707337 Linux118007419560: five native-appearance tests and same-page join failed, existing35 passed. Task 4 GREEN: run39237112607 Windows118008830769/Linux118008831060 all42 tests passed, normal exits. Includes persisted native appearance, viewBox/group transforms, compound transparent holes, opacity, resource rejection and cache budget.
- Task 5 start: real frame acceptance added for Image/AI-lineart/Library intake, exact completed source appearance and exported PNG equality; synthetic house, letterboxed portrait and filled-controller review frames follow.

- Whole-branch review found native SVG viewport aspect mismatch, cropped outer strokes, persisted-source validation bypass, Library keep-imports preference regression, Drawing-only element timing, and corrupt sidecar exception handling. Added regressions and fixed the shared boundaries; source-filter dropdown no longer controls actual-source timing. Native appearance cache validates restored SVGs too. Ordinary SVG stroke boxes are included without double scaling; exotic nonuniform/vector-effect/miter strokes remain a documented visual limitation.
- Task 5 frame test initially failed due to test-only Library callback signature (missing category); corrected. Actual Image/AI frame/export assertions passed before that fixture failure. Drawing-only time mismatch then reproduced independently in review regression.
- All six original broad CI workflows restored for final checks; new artwork test modules included in existing full Windows/Linux suites. Early logging initialization keeps test logs outside temporary fixture directories. No release channel/publish condition changed.
